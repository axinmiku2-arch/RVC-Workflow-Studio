"""Persistent jobs and subprocess orchestration for the portable RVC scripts."""
import atexit
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

import numpy as np
from .common import DEFAULTS, ROOT, STAGES, atomic_json, duration_text, inside, now, read_json
from tools.gpu_task_lock import GPUTaskLock

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".aiff", ".aif", ".wma"}
BUSY = {"checking", "running", "stopping", "previewing"}


class Cancelled(Exception):
    pass


class CommandFailed(RuntimeError):
    def __init__(self, code, tail):
        self.code, self.tail = code, tail
        super().__init__(tail)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(data)
    return value.hexdigest()


def hidden_process(args, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(args, **kwargs)


class ProcessGuard:
    """Windows Job Object kills only this subprocess tree if the wizard crashes."""
    def __init__(self, process):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if handle and kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) and kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle))):
            self.handle, self.kernel = handle, kernel
        elif handle:
            kernel.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def kill_tree(process):
    from tools.process_utils import kill_process_tree
    kill_process_tree(process, "训练向导")


def analyze_audio(path, root=ROOT, on_process=None, cancelled=lambda: False):
    """Stream decoded mono audio; never load an entire long recording into RAM."""
    path, root = Path(path), Path(root)
    report = {"ok": False, "duration": 0, "voiced_seconds": 0, "warnings": []}
    if not path.is_file() or path.stat().st_size == 0:
        return {**report, "error": "文件为空或已经不存在，请重新导入。"}
    args = [str(root / "ffprobe.exe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    probe = hidden_process(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    guard = ProcessGuard(probe)
    if on_process:
        on_process(probe)
    try:
        data, error = probe.communicate(timeout=30)
        if cancelled():
            raise Cancelled()
        if probe.returncode:
            raise ValueError(error.decode("utf-8", errors="replace")[-1000:])
        meta = json.loads(data)
        audio = next(s for s in meta["streams"] if s.get("codec_type") == "audio")
        report.update(sample_rate=int(audio.get("sample_rate", 0)), channels=int(audio.get("channels", 0)))
    except Cancelled:
        raise
    except Exception:
        if probe.poll() is None:
            kill_tree(probe)
        return {**report, "error": "无法解码这个音频。请重新导出为 WAV 或 FLAC。"}
    finally:
        guard.close()
    args = [str(root / "ffmpeg.exe"), "-nostdin", "-v", "error", "-i", str(path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    # A file avoids stderr pipe backpressure on malformed inputs.
    import tempfile
    with tempfile.TemporaryFile() as errors:
        process = hidden_process(args, stdout=subprocess.PIPE, stderr=errors)
        guard = ProcessGuard(process)
        if on_process:
            on_process(process)
        count = clipped = silent = windows = 0
        carry = np.zeros(0, dtype=np.float32)
        peak = 0.0
        try:
            while True:
                if cancelled():
                    kill_tree(process)
                    raise Cancelled()
                block = process.stdout.read(65536)
                if not block:
                    break
                values = np.frombuffer(block, dtype="<f4")
                if not np.isfinite(values).all():
                    raise ValueError("音频包含无效数值")
                count += len(values)
                peak = max(peak, float(np.max(np.abs(values), initial=0)))
                clipped += int(np.count_nonzero(np.abs(values) >= 0.999))
                values = np.concatenate((carry, values))
                full = len(values) // 320 * 320
                frames = values[:full].reshape(-1, 320)
                rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
                silent += int(np.count_nonzero(rms < 10 ** (-55 / 20)))
                windows += len(rms)
                carry = values[full:]
            process.wait(timeout=15)
            if process.returncode or not count:
                raise ValueError("解码失败")
            if len(carry):
                windows += 1
                silent += int(np.sqrt(np.mean(carry.astype(np.float64) ** 2)) < 10 ** (-55 / 20))
            seconds = count / 16000
            silence = silent / max(1, windows)
            report.update(duration=seconds, voiced_seconds=seconds * (1 - silence), silence_ratio=silence,
                          clipping_ratio=clipped / count, peak=peak, ok=silence < 1 and peak > 1e-6)
            if not report["ok"]:
                report["error"] = "未检测到有效声音，请换成有清晰干声的文件。"
            if silence > 0.6:
                report["warnings"].append("静音比例较高，建议检查大段间奏或空白。")
            if clipped / count > 0.005:
                report["warnings"].append("检测到疑似削波；请试听是否失真。")
            if report["sample_rate"] < 32000:
                report["warnings"].append("采样率较低；升采样不会恢复已丢失的细节。")
            return report
        except Cancelled:
            raise
        except Exception:
            return {**report, "ok": False, "error": "音频解码不完整或数据无效，请重新导出 WAV / FLAC。"}
        finally:
            if process.poll() is None:
                kill_tree(process)
            process.stdout.close()
            guard.close()


def validate_voice(path, sr=None):
    import torch
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not checkpoint.get("weight") or len(checkpoint.get("config", [])) != 18:
        raise ValueError("音色模型不完整。")
    if checkpoint.get("version") != "v2" or checkpoint.get("f0") != 1:
        raise ValueError("音色模型版本或音高配置不一致。")
    if sr and checkpoint.get("sr") != sr:
        raise ValueError("音色模型采样率不一致。")
    if any(not torch.isfinite(value).all().item() for value in checkpoint["weight"].values()):
        raise ValueError("音色模型出现无效数值，请检查训练日志和素材。")
    match = re.search(r"(\d+)epoch", checkpoint.get("info", ""))
    return {"epoch": int(match.group(1)) if match else 0, "sr": checkpoint["sr"]}


def validate_index(path):
    from tools.faiss_io import read_index
    value = read_index(path)
    if value.d != 768 or value.ntotal < 1:
        raise ValueError("索引内容为空或特征维度不正确。")
    return value.ntotal


class JobManager:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.logs = self.root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.active_id = None
        self.process = None
        self.thread = None
        self.stop_event = threading.Event()
        self._load()
        atexit.register(self.shutdown)

    def _load(self):
        for file in self.logs.glob("wizard_*/wizard.json"):
            try:
                job = read_json(file)
                if not re.fullmatch(r"wizard_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}", job["id"]) or file.parent.name != job["id"]:
                    continue
                if job["status"] in BUSY:
                    job.update(status="interrupted", message="程序上次中断。可从已完成阶段与完整检查点继续。", pid=None)
                    atomic_json(file, job)
                self.jobs[job["id"]] = job
            except (ValueError, KeyError, TypeError, OSError):
                continue

    def directory(self, job_id):
        if job_id not in self.jobs:
            raise ValueError("请先导入素材或选择已有项目。")
        return inside(self.logs / job_id, self.logs)

    def snapshot(self, job_id):
        with self.lock:
            return copy.deepcopy(self.jobs.get(job_id))

    def list_jobs(self):
        with self.lock:
            return [copy.deepcopy(j) for j in sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)]

    def update(self, job_id, **changes):
        with self.lock:
            self.jobs[job_id].update(changes, updated_at=now())
            atomic_json(self.directory(job_id) / "wizard.json", self.jobs[job_id])

    def _editable(self, job_id):
        job = self.snapshot(job_id)
        if job["status"] in BUSY or any(s != "check" for s in job["completed_stages"]):
            raise ValueError("素材已经用于处理或训练。更换素材请新建项目。")

    def create(self, name, files):
        name = (name or "我的音色").strip()[:80]
        if not files:
            raise ValueError("先把一个或多个干声音频拖入导入框。")
        with self.lock:
            job_id = "wizard_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
            self.jobs[job_id] = {"schema": 1, "id": job_id, "name": name, "created_at": now(), "updated_at": now(),
                "status": "draft", "stage": "import", "message": "素材已导入，等待体检。", "files": [],
                "settings": copy.deepcopy(DEFAULTS), "completed_stages": [], "progress": {}, "saved_epoch": 0,
                "models": [], "index": None, "preview": None, "error": None, "pid": None, "events": []}
            self.directory(job_id).mkdir()
            self.update(job_id)
        self.add_files(job_id, files)
        return job_id

    def add_files(self, job_id, files):
        self._editable(job_id)
        directory = self.directory(job_id) / "source"
        directory.mkdir(exist_ok=True)
        entries = self.snapshot(job_id)["files"]
        existing = {f["sha256"] for f in entries}
        for file in files or []:
            path = Path(file.name if hasattr(file, "name") else file)
            original = Path(getattr(file, "orig_name", str(path))).name
            suffix = Path(original).suffix.lower()
            if suffix not in AUDIO_EXTENSIONS:
                raise ValueError(f"不支持 {original}。请导入 WAV、FLAC、MP3 等音频。")
            hash_value = digest(path)
            if hash_value in existing:
                continue
            file_id = uuid.uuid4().hex
            destination = inside(directory / (file_id + suffix), directory)
            temp = destination.with_suffix(suffix + ".copying")
            try:
                shutil.copyfile(path, temp)
                if digest(temp) != hash_value:
                    raise ValueError("复制时音频发生变化，请重新导入。")
                os.replace(temp, destination)
            finally:
                temp.unlink(missing_ok=True)
            entries.append({"id": file_id, "original_name": original, "path": str(destination),
                            "sha256": hash_value, "bytes": destination.stat().st_size, "report": None})
            existing.add(hash_value)
            self.update(job_id, files=entries, completed_stages=[], status="draft", error=None)
        if not entries:
            raise ValueError("没有可导入的音频。")

    def remove_file(self, job_id, file_id):
        self._editable(job_id)
        files = self.snapshot(job_id)["files"]
        for entry in files:
            if entry["id"] == file_id:
                inside(entry["path"], self.directory(job_id) / "source").unlink(missing_ok=True)
        self.update(job_id, files=[f for f in files if f["id"] != file_id], completed_stages=[], status="draft", error=None)

    def configure(self, job_id, preset, sr, epochs, batch_size, workers, save_every):
        job = self.snapshot(job_id)
        if not job or job["status"] in BUSY:
            raise ValueError("任务运行中，暂时不能修改训练参数。")
        if sr not in ("40k", "48k"):
            raise ValueError("采样率请选择 40k 或 48k。")
        settings = {"preset": preset, "sr": sr, "epochs": int(epochs), "batch_size": int(batch_size),
                    "workers": int(workers), "save_every": int(save_every)}
        if not (1 <= settings["epochs"] <= 1200 and 1 <= settings["batch_size"] <= 40 and
                1 <= settings["workers"] <= min(16, os.cpu_count() or 1) and 1 <= settings["save_every"] <= 50):
            raise ValueError("训练参数超出允许范围，请使用推荐方案或调整高级选项。")
        if "prepare" in job["completed_stages"] and job["settings"]["sr"] != sr:
            raise ValueError("已经开始处理素材，不能更换采样率。请新建项目。")
        if job["saved_epoch"] and settings["epochs"] < job["saved_epoch"]:
            raise ValueError(f"已经保存到第 {job['saved_epoch']} 轮，总目标不能低于此值。")
        completed = job["completed_stages"][:]
        if settings["epochs"] > job["settings"]["epochs"] and "train" in completed:
            completed.remove("train")
        status = "ready" if job["status"] == "completed" and "train" not in completed else job["status"]
        self.update(job_id, settings=settings, completed_stages=completed, status=status, error=None)

    def _set_process(self, process):
        with self.lock:
            self.process = process
            if self.active_id:
                self.update(self.active_id, pid=process.pid if process else None)

    def _start(self, job_id, action, *args):
        with self.lock:
            if self.active_id is not None:
                raise ValueError("已有任务正在运行。请等待或先停止当前任务。")
            self.directory(job_id)
            self.active_id = job_id
            self.stop_event.clear()
            self.update(job_id, status="checking" if action == "check" else "previewing" if action == "preview" else "running", error=None)
            self.thread = threading.Thread(target=self._worker, args=(job_id, action, args), daemon=True)
            self.thread.start()

    def check(self, job_id):
        self._editable(job_id)
        if not self.snapshot(job_id)["files"]:
            raise ValueError("请先导入至少一个音频。")
        self._start(job_id, "check")

    def start(self, job_id):
        job = self.snapshot(job_id)
        if not job or "check" not in job["completed_stages"] or not all(f["report"] and f["report"]["ok"] for f in job["files"]):
            raise ValueError("请先完成素材体检，并移除或替换无效音频。")
        self._start(job_id, "train")

    def preview(self, job_id, model, audio, semitones, index_rate, protect):
        # Reserve before copying: a second click must not overwrite an in-flight input.
        with self.lock:
            if self.active_id is not None:
                raise ValueError("已有任务正在运行。请等待或先停止当前任务。")
            job = self.snapshot(job_id)
            if not job or model not in [m["path"] for m in job["models"]] or not audio:
                raise ValueError("先选择音色模型，再拖入独立的测试干声。")
            if not job["index"]:
                raise ValueError("索引尚未完成，请先重试生成索引。")
            source = Path(audio)
            destination = self.directory(job_id) / ("test-input" + source.suffix.lower())
            shutil.copyfile(source, destination)
            self.update(job_id, test_source=str(destination))
            self._start(job_id, "preview", model, str(destination), int(semitones), float(index_rate), float(protect), job["status"])

    def stop(self, immediate=False):
        with self.lock:
            job_id, process = self.active_id, self.process
            if not job_id:
                return
            self.stop_event.set()
            (self.directory(job_id) / "wizard-stop.request").touch()
            self.update(job_id, status="stopping", message="正在等待当前轮次完成并保存…" if not immediate else "正在立即停止，保留最近完整进度…")
            if process and (immediate or self.jobs[job_id]["stage"] != "train"):
                kill_tree(process)

    def shutdown(self):
        if self.active_id:
            self.stop(immediate=True)

    def _worker(self, job_id, action, args):
        original_stage = self.snapshot(job_id)["stage"]
        try:
            if action == "check":
                self._check(job_id)
            else:
                with GPUTaskLock("训练向导 · " + job_id, self.stop_event.is_set,
                                 lambda owner: self.update(job_id, message="等待其他分离 / 训练任务释放显卡…"), root=self.root):
                    if action == "preview":
                        self._preview(job_id, *args)
                    else:
                        self._pipeline(job_id)
        except Cancelled:
            self.update(job_id, status="stopped", message=f"已停止。最近保存到第 {self.snapshot(job_id)['saved_epoch']} 轮；可继续 / 重试。", pid=None)
        except Exception as error:
            if self.stop_event.is_set():
                self.update(job_id, status="stopped", message="任务已停止，可以继续 / 重试。", pid=None)
            else:
                detail = traceback.format_exc()
                (self.directory(job_id) / "wizard-error.log").write_text(detail, encoding="utf-8")
                message = self._friendly_error(error)
                self.update(job_id, status="failed", error=message, message=message, pid=None)
        finally:
            with self.lock:
                self.active_id = None
                self.process = None
                if action == "preview":
                    self.update(job_id, stage=original_stage)
                self.update(job_id, pid=None)

    @staticmethod
    def _friendly_error(error):
        if isinstance(error, CommandFailed):
            text = error.tail.lower()
            if "out of memory" in text or "alloc_failed" in text:
                return "显存仍然不足。请关闭其他占用显存的程序，再点击继续 / 重试。"
            if "no space" in text or "disk full" in text or "not enough space" in text:
                return "磁盘空间不足。请释放空间后继续 / 重试。"
            return "这个阶段执行失败，已保留完成的步骤。请查看详细日志中的末尾错误，再继续 / 重试。"
        return str(error) or "任务失败，请查看详细日志。"

    def _check(self, job_id):
        files = self.snapshot(job_id)["files"]
        self.update(job_id, stage="check", message="正在逐个读取并检查音频…")
        for i, entry in enumerate(files):
            if self.stop_event.is_set():
                raise Cancelled()
            self.update(job_id, progress={"done": i, "total": len(files)}, message=f"检查 {i+1}/{len(files)}：{entry['original_name']}")
            entry["report"] = analyze_audio(entry["path"], self.root, self._set_process, self.stop_event.is_set)
            self.update(job_id, files=files, progress={"done": i+1, "total": len(files)})
        self._set_process(None)
        valid = all(f["report"]["ok"] for f in files)
        self.update(job_id, status="ready" if valid else "draft", completed_stages=["check"] if valid else [],
                    message="素材体检完成，可查看报告并选择方案。" if valid else "体检发现无效音频，请移除或替换后重新检查。")

    def preflight(self, job_id):
        job = self.snapshot(job_id)
        sr = job["settings"]["sr"]
        required = ["ffmpeg.exe", "ffprobe.exe", "assets/hubert_base/config.json",
                    "assets/hubert_base/preprocessor_config.json", "assets/hubert_base/pytorch_model.bin",
                    "assets/rmvpe/rmvpe.pt", f"assets/pretrained_v2/f0G{sr}.pth", f"assets/pretrained_v2/f0D{sr}.pth",
                    f"logs/mute/0_gt_wavs/mute{sr}.wav", "logs/mute/3_feature768/mute.npy",
                    "logs/mute/2a_f0/mute.wav.npy", "logs/mute/2b-f0nsf/mute.wav.npy"]
        missing = [p for p in required if not (self.root / p).is_file()]
        if missing:
            raise ValueError("缺少训练所需文件：" + "、".join(missing) + "。补齐后可重试。")
        import torch
        from configs.config import get_device_dtype_sm
        if not torch.cuda.is_available() or get_device_dtype_sm(0)[0].type != "cuda":
            raise ValueError("没有可用于训练的 NVIDIA 显卡。请检查内置环境与驱动。")
        for file in job["files"]:
            if not Path(file["path"]).is_file() or digest(file["path"]) != file["sha256"]:
                raise ValueError("训练素材副本丢失或发生变化，请新建项目重新导入。")
        seconds = sum(f["report"]["duration"] for f in job["files"])
        estimated = int(4 * 1024 ** 3 + seconds * (int(sr[:2]) * 1000 * 4 + 16000 * 4 + 50 * 768 * 4) * 1.5)
        if shutil.disk_usage(self.root).free < estimated:
            raise ValueError(f"磁盘空间不足。这个项目建议至少留出 {estimated / 1024**3:.1f} GB 可用空间。")

    def _run(self, job_id, script, args, extra_env=None):
        environment = os.environ.copy()
        environment.update(PATH=str(self.root) + os.pathsep + str(self.root / "runtime") + os.pathsep + environment.get("PATH", ""),
                           RVC_CUDA_GRAPH="0", RVC_OFFLINE_CUDA_GRAPH="0", OPENBLAS_NUM_THREADS="1",
                           OMP_NUM_THREADS="4", weight_root=str(self.root / "assets" / "weights"),
                           rmvpe_root=str(self.root / "assets" / "rmvpe"),
                           HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        environment.pop("RVC_WIZARD_JOB", None)
        if extra_env:
            environment.update(extra_env)
        command = [sys.executable, "-I", "-u", "-X", "utf8", str(self.root / script), *map(str, args)]
        log_path = self.directory(job_id) / "wizard-console.log"
        tail = []
        process = hidden_process(command, cwd=self.root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1)
        guard = ProcessGuard(process)
        self._set_process(process)
        try:
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n[{now()}] {script}\n")
                stream.flush()
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    tail.append(line)
                    tail = tail[-100:]
                    if line.startswith("WIZARD_EVENT "):
                        self._event(job_id, json.loads(line[len("WIZARD_EVENT "):]))
            code = process.wait()
            if self.stop_event.is_set():
                raise Cancelled()
            if code:
                raise CommandFailed(code, "".join(tail))
        finally:
            if process.poll() is None:
                kill_tree(process)
            process.stdout.close()
            guard.close()
            self._set_process(None)

    def _event(self, job_id, event):
        job = self.snapshot(job_id)
        events = (job["events"] + [{**event, "time": now()}])[-80:]
        changes = {"events": events}
        if event["event"] == "checkpoint":
            changes["saved_epoch"] = event["epoch"]
        elif event["event"] == "voice":
            path = str(inside(event["path"], self.root / "assets" / "weights"))
            models = [m for m in job["models"] if m["path"] != path]
            models.append({"path": path, "epoch": event["epoch"], "final": event["final"]})
            changes["models"] = models
        elif event["event"] == "epoch":
            # The first hook is imported at epoch end, so its duration is not an epoch.
            timings = [e["seconds"] for e in events if e["event"] == "epoch"][1:]
            eta = (event["total"] - event["epoch"]) * (sum(timings[-5:]) / len(timings[-5:])) if len(timings) >= 2 else None
            changes.update(progress={"epoch": event["epoch"], "total": event["total"], "eta": eta},
                           message=f"训练到第 {event['epoch']} / {event['total']} 轮。")
        self.update(job_id, **changes)

    def _complete_stage(self, job_id, stage):
        completed = self.snapshot(job_id)["completed_stages"]
        if stage not in completed:
            self.update(job_id, completed_stages=completed + [stage])

    def _prepared_names(self, job_id):
        import soundfile as sf
        directory = self.directory(job_id)
        files = sorted((directory / "0_gt_wavs").glob("*.wav"))
        valid = set()
        for file in files:
            other = directory / "1_16k_wavs" / file.name
            try:
                a, b = sf.info(str(file)), sf.info(str(other))
                if a.frames / a.samplerate >= 1.05 and b.samplerate == 16000 and b.frames > 16000:
                    valid.add(file.stem)
            except Exception:
                pass
        if not valid:
            raise ValueError("没有足够长度的有效训练片段。请提供清晰、连续的干声，避免只有极短声音。")
        return valid

    def _features(self, job_id, kind, names, repair=False):
        directory = self.directory(job_id)
        folder = {"pitch": "2a_f0", "pitchf": "2b-f0nsf", "features": "3_feature768"}[kind]
        good = set()
        for name in names:
            file = directory / folder / (name + (".wav.npy" if kind != "features" else ".npy"))
            try:
                array = np.load(file, allow_pickle=False)
                if array.size and np.isfinite(array).all() and (kind != "features" or array.ndim == 2 and array.shape[1] == 768):
                    good.add(name)
                elif repair:
                    inside(file, directory).unlink(missing_ok=True)
            except Exception:
                if repair:
                    inside(file, directory).unlink(missing_ok=True)
        return good

    def _restore_pair(self, job_id):
        import torch
        directory = self.directory(job_id)
        manifest = read_json(directory / "wizard-checkpoints.json", {"pairs": []})
        valid = []
        for pair in sorted(manifest["pairs"], key=lambda p: p["epoch"], reverse=True):
            try:
                for key in ("g", "d"):
                    path = inside(directory / pair[key], directory)
                    value = torch.load(path, map_location="cpu", weights_only=True)
                    if value.get("iteration") != pair["epoch"] or not value.get("model") or not value.get("optimizer"):
                        raise ValueError("检查点不完整")
                    if any(not torch.isfinite(tensor).all().item() for tensor in value["model"].values()):
                        raise ValueError("检查点模型包含无效数值")
                    del value
                valid.append(pair)
            except Exception:
                continue
        keep = {pair[key] for pair in valid for key in ("g", "d")}
        for pattern in ("G_*.pth", "D_*.pth"):
            for path in directory.glob(pattern):
                if path.name not in keep:
                    path.replace(path.with_suffix(".pth.invalid"))
        atomic_json(directory / "wizard-checkpoints.json", {"pairs": sorted(valid, key=lambda p: p["epoch"])[-2:]})
        saved = valid[0]["epoch"] if valid else 0
        old = self.snapshot(job_id)["saved_epoch"]
        if old and saved == 0:
            raise ValueError("已保存的续训检查点全部损坏。请保留现有音色导出，并新建项目训练。")
        self.update(job_id, saved_epoch=saved)
        if saved < old:
            self.update(job_id, message=f"最近检查点不完整，已回退到第 {saved} 轮。")
        return saved

    def _make_config(self, job_id, names):
        job, directory = self.snapshot(job_id), self.directory(job_id)
        sr = job["settings"]["sr"]
        template = self.root / "configs" / ("v1" if sr == "40k" else "v2") / (sr + ".json")
        atomic_json(directory / "config.json", read_json(template))
        lines = []
        for name in sorted(names):
            paths = [directory / "0_gt_wavs" / f"{name}.wav", directory / "3_feature768" / f"{name}.npy",
                     directory / "2a_f0" / f"{name}.wav.npy", directory / "2b-f0nsf" / f"{name}.wav.npy"]
            lines.append("|".join(str(p).replace("\\", "/") for p in paths) + "|0")
        mute = self.logs / "mute"
        silence = "|".join(str(p).replace("\\", "/") for p in [mute / "0_gt_wavs" / f"mute{sr}.wav",
                           mute / "3_feature768" / "mute.npy", mute / "2a_f0" / "mute.wav.npy", mute / "2b-f0nsf" / "mute.wav.npy"]) + "|0"
        lines.extend([silence, silence])
        (directory / "filelist.txt").write_text("\n".join(lines), encoding="utf-8")

    def _pipeline(self, job_id):
        self.preflight(job_id)
        job, directory = self.snapshot(job_id), self.directory(job_id)
        settings = job["settings"]
        (directory / "wizard-stop.request").unlink(missing_ok=True)
        for stage, label in STAGES:
            if self.stop_event.is_set():
                raise Cancelled()
            self.update(job_id, stage=stage, progress={}, message=f"正在{label}…")
            job = self.snapshot(job_id)
            if stage == "prepare":
                try:
                    names = self._prepared_names(job_id) if stage in job["completed_stages"] else set()
                except ValueError:
                    names = set()
                if not names:
                    self._run(job_id, "train/preprocess.py", [directory / "source", int(settings["sr"][:2]) * 1000,
                                settings["workers"], directory, "False", "3.7"])
                    names = self._prepared_names(job_id)
            elif stage == "pitch":
                names = self._prepared_names(job_id)
                good = self._features(job_id, "pitch", names, True) & self._features(job_id, "pitchf", names, True)
                if good != names:
                    # Extraction skips files only when both pitch arrays exist.
                    for name in names - good:
                        for folder in ("2a_f0", "2b-f0nsf"):
                            (directory / folder / f"{name}.wav.npy").unlink(missing_ok=True)
                    self._run(job_id, "train/dataset/extract_f0.py", ["cuda", 1, 0, 0, directory, "True"])
                if self._features(job_id, "pitch", names) & self._features(job_id, "pitchf", names) != names:
                    raise ValueError("部分片段的音高提取失败，请查看日志后重试。")
            elif stage == "features":
                names = self._prepared_names(job_id)
                if self._features(job_id, "features", names, True) != names:
                    self._run(job_id, "train/dataset/extract_hubert_feature.py", ["cuda:0", 1, 0, 0, directory, "v2", "True"])
                if self._features(job_id, "features", names) != names:
                    raise ValueError("部分片段的声音特征提取失败，请查看日志后重试。")
            elif stage == "train":
                names = self._prepared_names(job_id)
                self._make_config(job_id, names)
                final_path = self.root / "assets" / "weights" / (job_id + ".pth")
                final_epoch = 0
                if final_path.exists():
                    try:
                        final_epoch = validate_voice(final_path, settings["sr"])["epoch"]
                    except Exception:
                        final_path.replace(final_path.with_suffix(".pth.invalid"))
                if final_epoch < settings["epochs"]:
                    saved = self._restore_pair(job_id)
                    if saved >= settings["epochs"]:
                        # Recover a missing final voice directly from the committed generator.
                        import torch
                        from train.utils import HParams
                        from types import SimpleNamespace
                        from .training_hooks import save_voice
                        hps = HParams(**read_json(directory / "config.json"))
                        hps.name, hps.sample_rate, hps.if_f0, hps.version = job_id, settings["sr"], 1, "v2"
                        pair = read_json(directory / "wizard-checkpoints.json")["pairs"][-1]
                        state = torch.load(directory / pair["g"], map_location="cpu", weights_only=True)["model"]
                        save_voice(hps, SimpleNamespace(state_dict=lambda: state), saved, final=True, root=self.root)
                        del state
                    batch = settings["batch_size"]
                    while saved < settings["epochs"]:
                        self.update(job_id, settings={**settings, "batch_size": batch})
                        args = ["-e", job_id, "-sr", settings["sr"], "-f0", 1, "-bs", batch, "-g", 0,
                                "-te", settings["epochs"], "-se", settings["save_every"],
                                "-pg", self.root / "assets" / "pretrained_v2" / f"f0G{settings['sr']}.pth",
                                "-pd", self.root / "assets" / "pretrained_v2" / f"f0D{settings['sr']}.pth",
                                "-l", 0, "-c", 0, "-sw", 0, "-v", "v2"]
                        try:
                            self._run(job_id, "train/train.py", args, {"RVC_WIZARD_JOB": str(directory)})
                            break
                        except CommandFailed as error:
                            if not ("out of memory" in error.tail.lower() or "alloc_failed" in error.tail.lower()) or batch == 1:
                                raise
                            batch = max(1, batch // 2)
                            self.update(job_id, message=f"显存不足，已降低每批数量到 {batch}，正在恢复进度。")
                            self._restore_pair(job_id)
                result = validate_voice(final_path, settings["sr"])
                if result["epoch"] < settings["epochs"]:
                    raise ValueError("模型保存轮次未达到训练目标，请继续 / 重试。")
                self._register_models(job_id)
            elif stage == "index":
                candidates = sorted(directory.glob("added_*v2.index"), key=lambda p: p.stat().st_mtime, reverse=True)
                index = None
                for candidate in candidates:
                    try:
                        validate_index(candidate)
                        index = candidate
                        break
                    except Exception:
                        candidate.replace(candidate.with_suffix(".index.invalid"))
                        alias = self.root / "assets" / "indices" / f"{job_id}_{candidate.name}"
                        alias.unlink(missing_ok=True)
                if not index:
                    # Validate trained-only files too: the old script reuses them.
                    from tools.faiss_io import read_index
                    for candidate in directory.glob("trained_*v2.index"):
                        try:
                            value = read_index(candidate)
                            if value.d != 768 or not value.is_trained:
                                raise ValueError()
                        except Exception:
                            candidate.replace(candidate.with_suffix(".index.invalid"))
                    self._run(job_id, "train/train_index.py", [job_id, "v2", self.root / "assets" / "indices", settings["workers"]])
                    candidates = sorted(directory.glob("added_*v2.index"))
                    if not candidates:
                        raise ValueError("没有生成可用索引，模型已保留，可单独重试这一阶段。")
                    index = candidates[-1]
                    validate_index(index)
                self.update(job_id, index=str(index))
            self._complete_stage(job_id, stage)
        self.update(job_id, status="completed", stage="done", progress={}, message="模型和索引均已核验。现在可以使用独立干声试听并导出。", error=None)

    def _register_models(self, job_id):
        weights = self.root / "assets" / "weights"
        found = []
        for path in [weights / (job_id + ".pth"), *weights.glob(job_id + "_e*.pth")]:
            if path.exists():
                try:
                    meta = validate_voice(path, self.snapshot(job_id)["settings"]["sr"])
                    found.append({"path": str(path), "epoch": meta["epoch"], "final": path.stem == job_id})
                except Exception:
                    continue
        self.update(job_id, models=sorted(found, key=lambda m: (m["epoch"], m["final"]), reverse=True))

    def _preview(self, job_id, model, source, semitones, index_rate, protect, previous_status):
        job = self.snapshot(job_id)
        validate_voice(model, job["settings"]["sr"])
        validate_index(job["index"])
        self.update(job_id, stage="preview", message="正在转换测试干声，请稍候…", preview=None)
        output = self.directory(job_id) / ("preview-" + uuid.uuid4().hex[:8] + ".wav")
        self._run(job_id, "rvc_wizard/preview_worker.py", [model, job["index"], source, output, semitones, index_rate, protect])
        import soundfile as sf
        info = sf.info(str(output))
        if info.frames == 0:
            raise ValueError("试听结果为空，请查看转换日志。")
        restored = "completed" if all(stage in job["completed_stages"] for stage, _ in STAGES) else previous_status
        self.update(job_id, preview=str(output), status=restored, error=None, message="试听已完成，可以比较原声和转换音频。")

    def export(self, job_id, model):
        job = self.snapshot(job_id)
        if not job or model not in [m["path"] for m in job["models"]] or not job["index"]:
            raise ValueError("先完成模型与索引，再选择要导出的音色。")
        meta = validate_voice(model, job["settings"]["sr"])
        validate_index(job["index"])
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", job["name"]).strip(" .")[:60] or "我的音色"
        directory = self.directory(job_id) / "exports"
        directory.mkdir(exist_ok=True)
        output = directory / f"{name}_{meta['epoch']}轮.zip"
        temporary = output.with_suffix(".zip.writing")
        instructions = f"{job['name']} · 第 {meta['epoch']} 轮\n\n把 .pth 放入 RVC 的 assets/weights，把 .index 放入 assets/indices。\n刷新原 WebUI 的音色列表，选择该模型并指定对应索引。\n试听起点：RMVPE，原调，索引比例 0.75，辅音保护 0.33。\n\n训练参数：\n" + json.dumps(job["settings"], ensure_ascii=False, indent=2) + "\n\n本包不含源录音与完整续训检查点。继续训练需保留 logs 下的原项目目录。\n"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.write(model, f"{name}.pth")
            archive.write(job["index"], f"{name}.index")
            archive.writestr("使用说明.txt", instructions)
        os.replace(temporary, output)
        self.update(job_id, export_path=str(output))
        return str(output)

    def log_tail(self, job_id, count=50):
        path = self.directory(job_id) / "wizard-console.log"
        if not path.exists():
            return "这里会保留各阶段的详细日志。"
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 24000))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-count:])
