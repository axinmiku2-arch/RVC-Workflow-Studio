"""Persistent conversion tasks without touching the standalone wizard's manager."""
import copy
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from rvc_separation.models import ROOT, read_json, atomic_json, sha256
from rvc_separation.audio import probe, process_options
from tools.process_utils import kill_process_tree
from rvc_wizard.backend import ProcessGuard
from .settings import normalize, check_models, LABELS
from .audio import export

BUSY = {"running", "waiting", "stopping"}


class Manager:
    def __init__(self, directory=None):
        self.directory = Path(directory or ROOT / "logs" / "conversion_pipeline")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs, self.processes = {}, {}
        for path in self.directory.glob("task_*/job.json"):
            job = read_json(path)
            if job and job.get("acceptance_only"):
                continue
            if job:
                if job["status"] in BUSY:
                    job.update(status="interrupted", message="上次任务中断，点击重试可复用已完成阶段。")
                    atomic_json(path, job)
                self.jobs[job["id"]] = job

    def snapshot(self, identifier=None):
        with self.lock:
            if not identifier and self.jobs:
                identifier = max(self.jobs, key=lambda key: self.jobs[key]["updated"])
            return copy.deepcopy(self.jobs.get(identifier))

    def _save(self, job):
        job["updated"] = time.time()
        atomic_json(self.directory / job["id"] / "job.json", job)

    def _idle(self):
        if any(job["status"] in BUSY for job in self.jobs.values()):
            raise ValueError("当前转换任务尚未结束，请等待完成或停止后再开始。")

    def start(self, source, model, params, settings, mode="full", start=0):
        settings = normalize(settings)
        check_models(settings, model)
        source = Path(source or "")
        if not source.is_file():
            raise ValueError("请先上传待处理音频。")
        if mode not in {"preview", "full"} or not math.isfinite(float(start)) or float(start) < 0:
            raise ValueError("试听起点无效。")
        with self.lock:
            self._idle()
            report = probe(source)
            if not math.isfinite(report["duration"]) or report["duration"] <= 0:
                raise ValueError("音频时长无效，请重新上传可解码的音频。")
            if start >= report["duration"]:
                raise ValueError("试听起点已超过音频时长。")
            identifier = "task_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
            directory = self.directory / identifier
            directory.mkdir()
            if shutil.disk_usage(directory).free < source.stat().st_size + 256 * 1024**2:
                raise OSError("任务目录磁盘空间不足。")
            target = directory / ("source" + source.suffix)
            shutil.copyfile(source, target)
            model_path = Path(model).resolve()
            params = dict(params, model=str(model_path), model_sha256=sha256(model_path))
            index = Path(str(params.get("index") or "").strip().strip('"'))
            params["index"] = str(index.resolve()) if index.is_file() else str(params.get("index") or "")
            params["index_sha256"] = sha256(index) if index.is_file() else None
            entry = dict(id="single", name=source.stem, path=str(target), sha256=sha256(target), track=0, **report)
            job = dict(id=identifier, name=source.stem, entry=entry, settings=settings, conversion=params, mode=mode,
                       start=float(start) if mode == "preview" else 0, duration=30, status="ready", progress=0,
                       message="准备处理", created=time.time(), updated=time.time(), version=0, result=None)
            self.jobs[identifier] = job
            self._launch(job)
            return identifier

    def _launch(self, job, post_only=False):
        directory = self.directory / job["id"]
        job["version"] += 1
        version = directory / f"run_{job['version']}"
        version.mkdir()
        core = read_json(directory / "core.json") if post_only else None
        if post_only and not core:
            raise ValueError("尚无完整转换干声，请先完成转换。")
        job.update(status="running", progress=0, message="更新效果／合成…" if post_only else "等待开始…", result=None)
        request = dict(id=job["id"], entry=job["entry"], settings=job["settings"], conversion=job["conversion"], mode=job["mode"],
                       start=job["start"], duration=job["duration"], cache=str(self.directory / "cache"),
                       core_path=str(directory / "core.json"), core=core, post_only=post_only,
                       stop_path=str(version / "stop"), result_path=str(version / "result.json"))
        request_path = version / "request.json"
        atomic_json(request_path, request)
        job["request_path"] = str(request_path)
        self._save(job)
        thread = threading.Thread(target=self._run, args=(job["id"], request_path), daemon=True)
        thread.start()

    def _run(self, identifier, request_path):
        request = read_json(request_path)
        process, guard = None, None
        try:
            environment = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", GRADIO_ANALYTICS_ENABLED="False")
            process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", "-m", "rvc_conversion.worker", str(request_path)],
                cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", **process_options())
            guard = ProcessGuard(process)
            with self.lock:
                self.processes[identifier] = process
                if self.jobs[identifier]["status"] == "stopping":
                    kill_process_tree(process, "单次转换")
            with (request_path.parent / "worker.log").open("w", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if line.startswith("CONVERSION_EVENT "):
                        import json
                        event = json.loads(line[len("CONVERSION_EVENT "):])
                        with self.lock:
                            job = self.jobs[identifier]
                            if job["status"] == "stopping":
                                continue
                            job["message"] = event.get("message", job["message"])
                            if event["event"] == "waiting":
                                job["status"] = "waiting"
                            else:
                                job["status"] = "running"
                            phase = event.get("stage")
                            if event["event"] == "stage":
                                job["stage"] = phase
                            phase = phase or job.get("stage")
                            base, span = {"separate": (5, 25), "harmony": (30, 15), "dereverb": (45, 15), "denoise": (60, 10),
                                          "conversion": (70, 15), "effects": (85, 8), "mix": (93, 6)}.get(phase, (0, 0))
                            if event["event"] == "progress" and event.get("total"):
                                job["progress"] = base + span * min(1, event["done"] / event["total"])
                            elif phase:
                                job["progress"] = base
                            if event["event"] == "error":
                                job["error"] = event["message"]
                            self._save(job)
            code = process.wait()
            result = read_json(request["result_path"])
            with self.lock:
                job = self.jobs[identifier]
                stopped = job["status"] == "stopping" or Path(request["stop_path"]).exists()
                if stopped:
                    job.update(status="stopped", message="已停止；点击重试可复用已完成阶段。")
                elif code or not result:
                    job.update(status="failed", message=job.get("error") or "处理失败，请检查任务日志后重试。")
                else:
                    job.update(status="completed", progress=100, result=result, message="短段试听完成（不是整首）。" if job["mode"] == "preview" else "整首处理完成，可以试听并导出。")
                self._save(job)
        except Exception as error:
            with self.lock:
                self.jobs[identifier].update(status="failed", message=str(error))
                self._save(self.jobs[identifier])
        finally:
            with self.lock:
                self.processes.pop(identifier, None)
            if guard:
                guard.close()

    def stop(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job["status"] not in BUSY:
                return
            job.update(status="stopping", message="正在停止本任务…")
            request = read_json(job["request_path"])
            Path(request["stop_path"]).touch()
            self._save(job)
            process = self.processes.get(identifier)
        if process:
            kill_process_tree(process, "单次转换")

    def retry(self, identifier):
        with self.lock:
            self._idle()
            job = self.jobs.get(identifier)
            if not job:
                raise ValueError("没有可重试的任务。")
            check_models(job["settings"], job["conversion"]["model"])
            self._launch(job)
            return identifier

    def update_post(self, identifier, settings):
        with self.lock:
            self._idle()
            job = self.jobs.get(identifier)
            if not job or job["status"] != "completed":
                raise ValueError("请先完成转换，再更新效果／合成。")
            updated = normalize(settings)
            for key in ("separate", "separator", "harmony", "karaoke", "dereverb", "denoise"):
                if updated[key] != job["settings"][key]:
                    raise ValueError("分离选项已变化，请点击转换重新处理。已完成阶段会按需复用。")
            job["settings"] = updated
            self._launch(job, post_only=True)
            return identifier

    def export(self, identifier, kinds, folder, fmt):
        job = self.snapshot(identifier)
        if not job or job["status"] != "completed" or not job["result"]:
            raise ValueError("请先完成处理。")
        if job["mode"] != "full":
            raise ValueError("当前是30秒试听，正式导出请先点击转换处理整首。")
        if not kinds:
            raise ValueError("请选择要导出的结果。")
        receipts = []
        for kind in kinds:
            source = job["result"]["outputs"].get(kind)
            if not source:
                raise ValueError(f"{LABELS[kind]} 尚未生成。")
            receipts.append(export(source, folder, job["name"], LABELS[kind], fmt))
        with self.lock:
            self.jobs[identifier].setdefault("exports", []).extend(receipts)
            self._save(self.jobs[identifier])
        return receipts
