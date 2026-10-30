"""Persistent separation projects, immutable runs and explicit folder export."""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from .models import ROOT, MODELS, STATE, atomic_json, read_json, sha256, download_models, register_validation, available
from .audio import probe, decode, export_audio, process_options
from .engine import signature, stages
from tools.process_utils import kill_process_tree
from rvc_wizard.backend import ProcessGuard

DEFAULTS = dict(separate=True, separator="leap", keep=["vocals"], harmony=False, karaoke="karaoke", dereverb="gentle", denoise=False)
BUSY = {"running", "waiting", "stopping"}


def normalize(settings):
    result = dict(DEFAULTS, **settings)
    result["keep"] = sorted(set(result["keep"]) & {"vocals", "instrumental"})
    if not result["keep"]:
        raise ValueError("请至少保留人声或伴奏。")
    if result["separator"] not in {"leap", "deux", "viper"} or result["karaoke"] not in {"karaoke", "old_karaoke"}:
        raise ValueError("模型选择无效。")
    if result["dereverb"] not in {"off", "gentle", "fused"}:
        raise ValueError("去混响档位无效。")
    if not result["separate"]:
        result["keep"] = ["vocals"]
    if "vocals" not in result["keep"]:
        result.update(harmony=False, dereverb="off", denoise=False)
    return result


def fingerprint(job):
    return signature(dict(files=[dict(id=f["id"], sha256=f["sha256"], track=f["track"]) for f in job["files"]], settings=normalize(job["settings"])))


class JobManager:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.directory = self.root / "logs" / "separation"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.preview_lock = threading.Lock()
        self.jobs = {}
        self.active = None
        self.process = None
        self.thread = None
        self.model_thread = None
        self.model_stop = threading.Event()
        self.model_status = "模型就绪后可开始试听。"
        self.model_error = ""
        for path in self.directory.glob("job_*/job.json"):
            job = read_json(path)
            if not job:
                continue
            if job["status"] in BUSY:
                job.update(status="interrupted", message="上次任务中断，已完成阶段保留；点击继续。")
                atomic_json(path, job)
            self.jobs[job["id"]] = job

    def path(self, job_id):
        if job_id not in self.jobs:
            raise ValueError("请先导入素材或载入一个任务。")
        return self.directory / job_id

    def _save(self, job_id):
        self.jobs[job_id]["updated"] = time.time()
        atomic_json(self.path(job_id) / "job.json", self.jobs[job_id])

    def snapshot(self, job_id):
        with self.lock:
            return copy.deepcopy(self.jobs.get(job_id))

    def list_jobs(self):
        with self.lock:
            return sorted((copy.deepcopy(j) for j in self.jobs.values()), key=lambda j: j["updated"], reverse=True)

    def update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)
            self._save(job_id)

    def create(self, uploads):
        if not uploads:
            raise ValueError("请先拖入歌曲音频或视频。")
        job_id = "job_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        directory = self.directory / job_id
        (directory / "source").mkdir(parents=True)
        entries = []
        try:
            for item in uploads:
                source = Path(item if isinstance(item, (str, Path)) else item.name)
                if not source.is_file():
                    raise ValueError("上传素材不存在，请重新拖入。")
                if shutil.disk_usage(directory).free < source.stat().st_size + 256 * 1024**2:
                    raise OSError("素材目录磁盘空间不足。")
                identifier = uuid.uuid4().hex[:12]
                name = Path(getattr(item, "orig_name", None) or source.name).name
                target = directory / "source" / (identifier + source.suffix)
                shutil.copyfile(source, target)
                report = probe(target)
                if not math.isfinite(report["duration"]) or report["duration"] <= 0:
                    raise ValueError(f"{name} 的时长无法读取。")
                entries.append(dict(id=identifier, name=name, path=str(target), sha256=sha256(target), track=0, **report))
            with self.lock:
                self.jobs[job_id] = dict(id=job_id, name=entries[0]["name"], created=time.time(), updated=time.time(), files=entries,
                    settings=copy.deepcopy(DEFAULTS), versions=[], current_preview=None, current_full=None, latest=None,
                    status="ready", message="已导入素材。选择功能后，先试听 30 秒。", progress=0, pid=None, error=None, exports=[])
                self._save(job_id)
            return job_id
        except BaseException:
            # Keep failed import copies for diagnosis; don't touch other task files.
            atomic_json(directory / "import-error.json", dict(files=entries, error=traceback.format_exc()))
            raise

    def configure(self, job_id, settings):
        normalized = normalize(settings)
        with self.lock:
            job = self.jobs[job_id]
            if job["settings"] == normalized:
                return
            if job["status"] in BUSY:
                raise ValueError("请等待当前处理完成，或先停止，再更改选项。")
            if job["settings"] != normalized:
                job.update(settings=normalized, current_preview=None, current_full=None, latest=None, status="ready",
                           message="选项已更新，旧版本保留；下一次处理会复用相同的已完成步骤。", progress=0)
                self._save(job_id)

    def track(self, job_id, file_id, track):
        with self.lock:
            job = self.jobs[job_id]
            entry = next(f for f in job["files"] if f["id"] == file_id)
            track = int(track)
            if track < 0 or track >= len(entry["tracks"]):
                raise ValueError("音轨选择无效。")
            if entry["track"] == track:
                return
            if job["status"] in BUSY:
                raise ValueError("处理进行中，请先停止再切换音轨。")
            if entry["track"] != track:
                entry["track"] = track
                job.update(current_full=None, current_preview=None, latest=None, status="ready", message="音轨已更改，请重新处理。")
                self._save(job_id)

    def source_preview(self, job_id, file_id):
        job = self.snapshot(job_id)
        entry = next(f for f in job["files"] if f["id"] == file_id)
        path = self.path(job_id) / "source-preview" / f"{file_id}_{entry['track']}.wav"
        with self.preview_lock:
            if not path.exists():
                decode(entry["path"], path, entry["track"])
        return str(path)

    def start(self, job_id, mode="full", file_id=None, start=0, duration=30):
        with self.lock:
            if self.active:
                raise ValueError("已有分离任务正在运行；请等待完成或停止它。")
            job = self.jobs[job_id]
            job["settings"] = normalize(job["settings"])
            if mode not in {"full", "preview"}:
                raise ValueError("任务模式无效。")
            selected = job["files"] if mode == "full" else [f for f in job["files"] if f["id"] == file_id]
            if not selected:
                raise ValueError("请先选择试听文件。")
            if not math.isfinite(float(start)) or not math.isfinite(float(duration)) or start < 0 or duration < 1 or duration > 300:
                raise ValueError("试听起点须大于等于 0，时长须在 1–300 秒之间。")
            if mode == "preview" and start >= selected[0]["duration"]:
                raise ValueError("试听起点超过素材时长。")
            missing = [MODELS[model]["label"] for _, model, _ in stages(job["settings"]) if not available(model)]
            if missing:
                raise ValueError("模型尚未就绪：" + "、".join(missing) + "。请在模型管理中下载 / 重试验证。")
            version_id = "run_" + uuid.uuid4().hex[:12]
            directory = self.path(job_id) / "runs" / version_id
            directory.mkdir(parents=True)
            version = dict(id=version_id, mode=mode, fingerprint=fingerprint(job), settings=copy.deepcopy(job["settings"]),
                           files=[f["id"] for f in selected], start=float(start), duration=float(duration), status="running", results=[], created=time.time())
            job["versions"].append(version)
            job.update(latest=version_id, status="running", message="准备处理…", progress=0, error=None)
            if mode == "preview":
                job["current_preview"] = None
            else:
                job["current_full"] = None
            request = dict(job_id=job_id, files=copy.deepcopy(selected), settings=copy.deepcopy(job["settings"]), mode=mode,
                start=float(start), duration=float(duration), cache=str(self.path(job_id) / "cache"), stop_path=str(directory / "stop.request"),
                result_path=str(directory / "result.json"))
            atomic_json(directory / "request.json", request)
            self.active = job_id
            self._save(job_id)
            self.thread = threading.Thread(target=self._worker, args=(job_id, version_id, directory), daemon=True)
            self.thread.start()

    def _worker(self, job_id, version_id, directory):
        guard = None
        proc = None
        try:
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                proc = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", "-m", "rvc_separation.worker", str(directory / "request.json")],
                    cwd=self.root, stdout=subprocess.PIPE, stderr=log, encoding="utf-8", errors="replace", bufsize=1,
                    env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), **process_options())
                guard = ProcessGuard(proc)
                with self.lock:
                    self.process = proc
                    self.update(job_id, pid=proc.pid)
                    if (directory / "stop.request").exists():
                        kill_process_tree(proc, "Separation")
                file_index, file_count, stage_index, stage_count = 0, 1, 0, 1
                for line in proc.stdout:
                    if not line.startswith("SEPARATION_EVENT "):
                        log.write(line)
                        log.flush()
                        continue
                    event = json.loads(line[len("SEPARATION_EVENT "):])
                    log.write(json.dumps(event, ensure_ascii=False) + "\n")
                    log.flush()
                    kind = event["event"]
                    values = dict(message=event.get("message", "处理中…"))
                    if kind == "waiting":
                        values["status"] = "waiting"
                    elif kind == "file":
                        file_index, file_count = event["file_index"], event["file_count"]
                        values.update(status="running", current_file=values["message"], progress=100 * file_index / file_count)
                    elif kind == "stage":
                        stage_index, stage_count = event["stage_index"], max(1, event["stage_count"])
                        values.update(stage=event["stage"], progress=100 * (file_index + stage_index / stage_count) / file_count)
                    elif kind == "progress":
                        fraction = min(1, max(0, event["done"] / max(1, event["total"])))
                        values["progress"] = min(99.9, 100 * (file_index + (stage_index + fraction) / stage_count) / file_count)
                    elif kind == "settings":
                        values["actual_settings"] = event
                    elif kind == "file_done":
                        values["progress"] = 100 * (file_index + 1) / file_count
                    elif kind == "error":
                        values["error"] = values["message"]
                    with self.lock:
                        if self.jobs[job_id]["status"] == "stopping":
                            values.pop("status", None)
                        self.update(job_id, **values)
                code = proc.wait()
            result = read_json(directory / "result.json", {}) or {}
            stopped = (directory / "stop.request").exists()
            with self.lock:
                job = self.jobs[job_id]
                version = next(v for v in job["versions"] if v["id"] == version_id)
                version["results"] = result.get("results", [])
                version["status"] = "stopped" if stopped else "completed" if code == 0 and result.get("complete") else "failed"
                if version["status"] == "completed":
                    job["current_" + version["mode"]] = version_id
                    job.update(status="completed", progress=100, message="短段试听完成，请比较效果后处理整首。" if version["mode"] == "preview" else "整首处理完成，请试听并选择需要导出的结果。")
                elif stopped:
                    job.update(status="stopped", message="已停止，完成阶段保留；点击继续 / 重试。")
                else:
                    detail = (directory / "worker.log").read_text(encoding="utf-8", errors="replace")[-5000:]
                    job.update(status="failed", message=job.get("error") or detail[-1800:], error=job.get("error") or detail)
                self._save(job_id)
        except Exception as error:
            self.update(job_id, status="failed", error=traceback.format_exc(), message=str(error))
        finally:
            if proc and proc.poll() is None:
                kill_process_tree(proc, "Separation")
            if guard:
                guard.close()
            with self.lock:
                self.process = None
                self.active = None
                self.update(job_id, pid=None)

    def stop(self):
        with self.lock:
            if not self.active:
                return
            job_id = self.active
            version_id = self.jobs[job_id]["latest"]
            (self.path(job_id) / "runs" / version_id / "stop.request").touch()
            self.update(job_id, status="stopping", message="正在停止本任务；完整阶段会保留。")
            proc = self.process
        if proc:
            kill_process_tree(proc, "Separation")

    def resume(self, job_id):
        job = self.snapshot(job_id)
        old = next((v for v in job["versions"] if v["id"] == job["latest"]), None)
        if old and old["fingerprint"] == fingerprint(job):
            self.start(job_id, old["mode"], old["files"][0], old["start"], old["duration"])
        else:
            self.start(job_id)

    def results(self, job_id, mode):
        job = self.snapshot(job_id)
        if not job:
            return []
        version = next((v for v in job["versions"] if v["id"] == job.get("current_" + mode)), None)
        if not version or version["status"] != "completed" or version["fingerprint"] != fingerprint(job):
            return []
        return version["results"]

    def export(self, job_id, kinds, folder, fmt, mono, file_ids=None):
        with self.lock:
            results = self.results(job_id, "full")
            if not results:
                raise ValueError("请先完成整首处理；短段试听不能正式导出。")
            if not kinds:
                raise ValueError("请勾选至少一个导出结果。")
            if not str(folder).strip():
                raise ValueError("请填写导出文件夹。")
            exported = []
            names = {"final": "干声", "instrumental": "伴奏", "vocals": "分离人声", "lead": "主唱", "harmony": "和声及移除部分",
                     "dereverb": "去混响", "reverb": "混响回声", "denoise": "降噪人声", "noise": "噪声", "original": "原声"}
            for result in results:
                if file_ids is not None and result["file_id"] not in file_ids:
                    continue
                for kind in kinds:
                    if kind in result["outputs"] and kind in names:
                        exported.append(export_audio(result["outputs"][kind], folder, result["original_name"], names[kind], fmt, mono))
            if not exported:
                raise ValueError("所选文件没有对应结果，请检查导出选择。")
            self.jobs[job_id]["exports"].extend(exported)
            self._save(job_id)
            return exported

    def log_tail(self, job_id):
        job = self.snapshot(job_id)
        if not job or not job.get("latest"):
            return "等待处理。"
        path = self.path(job_id) / "runs" / job["latest"] / "worker.log"
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-10000:]
        except OSError:
            return "正在准备任务…"

    def download(self):
        if self.model_thread and self.model_thread.is_alive():
            return
        self.model_stop.clear()
        self.model_error = ""
        self.model_thread = threading.Thread(target=self._download_worker, daemon=True)
        self.model_thread.start()

    def _download_worker(self):
        try:
            def progress(done, total, name):
                self.model_status = f"{name} · {done / 1e6:.1f} / {total / 1e6:.1f} MB"
            download_models(progress, self.model_stop.is_set)
            # Each model is tested in a separate process so GPU memory is freed.
            for key, spec in MODELS.items():
                if spec.get("existing") or available(key):
                    continue
                if self.model_stop.is_set():
                    raise InterruptedError("模型准备已停止，可以继续。")
                self.model_status = "兼容验证 · " + spec["label"] + "（若显卡忙，会等待）"
                command = [sys.executable, "-I", "-X", "utf8", "-u", "-m", "rvc_separation.validate_models", "--model", key]
                with (self.directory / "model-validation.log").open("a", encoding="utf-8") as log:
                    process = subprocess.Popen(command, cwd=self.root, stdout=log, stderr=log, **process_options())
                    guard = ProcessGuard(process)
                    try:
                        while process.poll() is None:
                            if self.model_stop.wait(.2):
                                kill_process_tree(process, "Model validation")
                                raise InterruptedError("模型验证已停止，可以继续。")
                    finally:
                        if process.poll() is None:
                            kill_process_tree(process, "Model validation")
                        guard.close()
                if process.returncode:
                    raise RuntimeError(spec["label"] + " 兼容验证失败，详情见模型验证日志。")
            self.model_status = "全部新增模型下载与真实推理验证完成。"
        except Exception as error:
            self.model_status = "模型准备未完成；可点击继续下载 / 验证。"
            self.model_error = str(error)

    def shutdown(self):
        self.model_stop.set()
        self.stop()
