"""Regression coverage for boundaries that can lose work or export stale audio."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import soundfile as sf

from rvc_separation.models import download_file, ROOT, read_json
from rvc_separation.audio import decode, probe, write_float, validate, export_audio, process_options
from rvc_separation.backend import JobManager, DEFAULTS, fingerprint, normalize
from rvc_separation.engine import run_file, model_fingerprint
from tools.gpu_task_lock import GPUTaskLock, GPUWaitCancelled


class DownloadTests(unittest.TestCase):
    def test_model_fingerprint_tracks_weight_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "weight").write_bytes(b"first")
            (root / "config").write_bytes(b"settings")
            spec = {"test": {"weight": "weight", "config": "config", "label": "test"}}
            with patch("rvc_separation.engine.WEIGHTS", root), patch("rvc_separation.engine.MODELS", spec):
                before = model_fingerprint("test")
                (root / "weight").write_bytes(b"other")
                after_weight = model_fingerprint("test")
                (root / "config").write_bytes(b"changed")
                after_config = model_fingerprint("test")
                self.assertNotEqual(before["weight"], after_weight["weight"])
                self.assertNotEqual(after_weight["config"], after_config["config"])

    def test_range_resume_and_server_ignoring_range(self):
        data = b"model-test-" * 10240
        ranges = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                value = self.headers.get("Range")
                ranges.append(value)
                offset = int(value.split("=")[1].split("-")[0]) if value and self.path.startswith("/range") else 0
                self.send_response(206 if offset else 200)
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{len(data)-1}/{len(data)}")
                self.send_header("Content-Length", str(len(data) - offset))
                self.end_headers()
                self.wfile.write(data[offset:])
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                for name in ("range", "ignore"):
                    target = Path(folder) / (name + ".ckpt")
                    target.with_name(target.name + ".part").write_bytes(data[:5000])
                    download_file(f"http://127.0.0.1:{server.server_port}/{name}", target, len(data), hashlib.sha256(data).hexdigest())
                    self.assertEqual(target.read_bytes(), data)
                self.assertEqual(ranges, ["bytes=5000-", "bytes=5000-"])
                with self.assertRaises(InterruptedError):
                    download_file("http://invalid", Path(folder) / "cancel.ckpt", cancelled=lambda: True)
                with patch("rvc_separation.models.shutil.disk_usage") as disk:
                    disk.return_value.free = 0
                    with self.assertRaisesRegex(OSError, "磁盘空间不足"):
                        download_file("http://invalid", Path(folder) / "space.ckpt", 100)
        finally:
            server.shutdown()
            server.server_close()


class AudioJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder / "中文 歌曲.wav"
        wave = np.sin(np.arange(44100 * 2) * .04).astype("float32") * .2
        write_float(self.source, np.stack([wave, wave]))
        self.manager = JobManager(self.folder)
        self.job_id = self.manager.create([str(self.source)])

    def tearDown(self):
        self.manager.shutdown()
        self.temp.cleanup()

    def test_integer_export_clipping_names_and_formats(self):
        high = self.folder / "loud.wav"
        write_float(high, np.full((2, 44100), 1.2, dtype="float32"))
        a = export_audio(high, self.folder / "输出", "同名.wav", "干声")
        b = export_audio(high, self.folder / "输出", "同名.wav", "干声")
        c = export_audio(high, self.folder / "输出", "同名.wav", "干声", "FLAC", True)
        self.assertNotEqual(a["path"], b["path"])
        for item in (a, b, c):
            info = sf.info(item["path"])
            self.assertEqual(info.subtype, "PCM_24")
            self.assertEqual(info.samplerate, 44100)
            data, _ = sf.read(item["path"])
            self.assertLessEqual(np.abs(data).max(), .999001)
        self.assertEqual(sf.info(c["path"]).channels, 1)
        with patch("rvc_separation.audio.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            with self.assertRaises(OSError):
                export_audio(high, self.folder / "输出", "x.wav", "干声")
        with self.assertRaises(ValueError):
            write_float(self.folder / "nan.wav", np.full((2, 5), np.nan))

    def test_preview_cannot_export_and_settings_invalidate_full(self):
        job = self.manager.jobs[self.job_id]
        result = dict(file_id=job["files"][0]["id"], original_name="歌曲.wav", outputs={"final": str(self.source)})
        version = dict(id="test", mode="preview", status="completed", fingerprint=fingerprint(job), results=[result])
        job["versions"].append(version)
        job["current_preview"] = "test"
        with self.assertRaisesRegex(ValueError, "整首"):
            self.manager.export(self.job_id, ["final"], self.folder / "导出", "WAV", False)
        version["mode"] = "full"
        job["current_full"] = "test"
        self.assertEqual(len(self.manager.export(self.job_id, ["final"], self.folder / "导出", "WAV", False)), 1)
        self.manager.configure(self.job_id, dict(DEFAULTS, denoise=True))
        self.assertFalse(self.manager.results(self.job_id, "full"))
        with self.assertRaises(ValueError):
            self.manager.export(self.job_id, ["final"], self.folder / "导出", "WAV", False)
        self.assertEqual(normalize(dict(DEFAULTS, keep=["instrumental"], harmony=True, denoise=True))["dereverb"], "off")

    def test_cache_reuses_upstream_and_invalidates_downstream(self):
        entry = self.manager.snapshot(self.job_id)["files"][0]
        calls = []
        def fake(model, path, *args):
            calls.append(model)
            data, _ = sf.read(path, dtype="float32", always_2d=True)
            return [data.T * .8, data.T * .2], {"model": model}
        cache = self.folder / "stages"
        fingerprints = {key: {"weight": key, "config": "v1"} for key in ("leap", "gentle", "denoise", "karaoke")}
        with patch("rvc_separation.engine.infer", fake), patch("rvc_separation.engine.model_fingerprint", side_effect=lambda key: fingerprints[key]):
            run_file(entry, DEFAULTS, "full", 0, 30, cache)
            self.assertEqual(calls, ["leap", "gentle"])
            result = run_file(entry, dict(DEFAULTS, denoise=True), "full", 0, 30, cache)
            self.assertEqual(calls, ["leap", "gentle", "denoise"])
            self.assertTrue(result["metrics"][0]["reused"])
            run_file(entry, dict(DEFAULTS, harmony=True), "full", 0, 30, cache)
            self.assertEqual(calls, ["leap", "gentle", "denoise", "karaoke", "gentle"])
            fingerprints["leap"] = {"weight": "replacement", "config": "v1"}
            run_file(entry, DEFAULTS, "full", 0, 30, cache)
            self.assertEqual(calls[-2:], ["leap", "gentle"])

    def test_video_multiple_tracks_and_exact_alignment(self):
        other = self.folder / "另一音轨.wav"
        write_float(other, np.zeros((2, 44100 * 2), dtype="float32"))
        video = self.folder / "中文 双音轨.mkv"
        command = [str(ROOT / "ffmpeg.exe"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=64x64:r=1:d=2",
                   "-i", str(self.source), "-i", str(other), "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(video)]
        subprocess.run(command, check=True, **process_options())
        self.assertEqual(len(probe(video)["tracks"]), 2)
        decoded = decode(video, self.folder / "track.wav", track=1, start=.25, duration=1)
        data, _ = sf.read(decoded)
        self.assertEqual(data.shape, (44100, 2))
        self.assertEqual(np.abs(data).max(), 0)
        damaged = self.folder / "坏文件.mp3"
        damaged.write_bytes(b"not audio")
        with self.assertRaises(ValueError):
            probe(damaged)

    def test_restart_retains_completed_stage_and_marks_interruption(self):
        self.manager.update(self.job_id, status="running", latest="pending")
        restored = JobManager(self.folder)
        self.assertEqual(restored.snapshot(self.job_id)["status"], "interrupted")
        self.assertTrue(Path(restored.snapshot(self.job_id)["files"][0]["path"]).exists())

    def test_busy_page_restore_is_idempotent_but_changed_settings_are_rejected(self):
        self.manager.update(self.job_id, status="running")
        self.manager.configure(self.job_id, DEFAULTS)
        entry = self.manager.snapshot(self.job_id)["files"][0]
        self.manager.track(self.job_id, entry["id"], 0)
        with self.assertRaisesRegex(ValueError, "等待"):
            self.manager.configure(self.job_id, dict(DEFAULTS, denoise=True))
        self.assertEqual(self.manager.snapshot(self.job_id)["status"], "running")


class LockTests(unittest.TestCase):
    def test_training_wizard_waits_and_cancel_does_not_enter_pipeline(self):
        from rvc_wizard.backend import JobManager as TrainingManager
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_float(root / "train.wav", np.ones((2, 44100), dtype="float32") * .1)
            manager = TrainingManager(root)
            job_id = manager.create("mutex-test", [source])
            entered = threading.Event()
            manager._pipeline = lambda job: entered.set()
            with GPUTaskLock("separation-owner", root=root):
                manager._start(job_id, "train")
                deadline = time.monotonic() + 3
                while "等待" not in manager.snapshot(job_id)["message"] and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertIn("等待", manager.snapshot(job_id)["message"])
                self.assertFalse(entered.is_set())
                manager.stop(immediate=True)
                manager.thread.join(timeout=5)
                self.assertFalse(entered.is_set())
                self.assertEqual(manager.snapshot(job_id)["status"], "stopped")
            manager._start(job_id, "train")
            manager.thread.join(timeout=5)
            self.assertTrue(entered.is_set())

    def test_cross_process_serial_and_wait_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            owner = GPUTaskLock("test-owner", root=folder).acquire()
            signal = Path(folder) / "acquired.json"
            code = "from tools.gpu_task_lock import GPUTaskLock; import sys,pathlib; guard=GPUTaskLock('child',root=sys.argv[1]); guard.acquire(); pathlib.Path(sys.argv[2]).write_text('acquired'); guard.release()"
            process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code, folder, str(signal)], cwd=ROOT, **process_options())
            try:
                time.sleep(.5)
                self.assertFalse(signal.exists())
                self.assertIsNone(process.poll())
                with self.assertRaises(GPUWaitCancelled):
                    GPUTaskLock("cancelled", cancelled=lambda: True, root=folder).acquire()
                owner.release()
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertTrue(signal.exists())
            finally:
                owner.release()
                if process.poll() is None:
                    process.kill()
                    process.wait()


class MemoryFallbackTests(unittest.TestCase):
    def test_oom_reduces_chunk_keeps_model_and_reports_actual_setting(self):
        from rvc_separation.engine import infer
        from rvc_separation.models import MODELS
        chunks, events, closed = [], [], []
        spec = MODELS["leap"]
        class FakeSeparator:
            def __init__(self, family, weight, config, **kwargs):
                self.config = SimpleNamespace(training=SimpleNamespace(use_amp=False))
                self.chunk = kwargs["inference_params"]["chunk_size"]
                chunks.append(self.chunk)
                self.weight = weight
            def separate(self, mix, **kwargs):
                if self.chunk == spec["chunk"]:
                    raise RuntimeError("CUDA out of memory")
                return {"vocals": mix.T * .8, "other": mix.T * .2}
            def close(self):
                closed.append(self.weight)
        with tempfile.TemporaryDirectory() as folder:
            source = write_float(Path(folder) / "source.wav", np.ones((2, 44100), dtype="float32") * .1)
            import sys
            from rvc_separation.models import ROOT
            sys.path.insert(0, str(ROOT / "tools")) if str(ROOT / "tools") not in sys.path else None
            with patch("pymss.MSSeparator", FakeSeparator), patch("torch.cuda.is_available", return_value=False):
                arrays, metrics = infer("leap", source, events.append, allow_unvalidated=True)
            self.assertEqual(len(chunks), 2)
            self.assertLess(metrics["chunk"], spec["chunk"])
            self.assertEqual(metrics["model"], "leap")
            self.assertEqual(len(set(closed)), 1)
            self.assertTrue(any("显存不足" in item.get("message", "") for item in events))
            self.assertEqual(arrays[0].shape, (2, 44100))


if __name__ == "__main__":
    unittest.main()
