r"""Run with runtime\python.exe -I -X utf8 -m unittest discover -s tests -v."""
import copy
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf
import torch
from rvc_wizard.backend import JobManager, CommandFailed, analyze_audio, validate_voice
from rvc_wizard.common import ROOT, DEFAULTS, atomic_json, inside, read_json
from rvc_wizard.training_hooks import save_pair


def wait(manager, timeout=20):
    deadline = time.monotonic() + timeout
    while manager.active_id and time.monotonic() < deadline:
        time.sleep(.02)
    if manager.active_id:
        manager.stop(immediate=True)
        raise AssertionError("后台任务没有在限定时间内结束")


class FakeManager(JobManager):
    """Exercises orchestration and recovery, not the RVC network itself."""
    def preflight(self, job_id):
        pass

    def _run(self, job_id, script, args, extra_env=None):
        directory = self.directory(job_id)
        if script.endswith("preprocess.py"):
            for folder, sr in [("0_gt_wavs", 40000), ("1_16k_wavs", 16000)]:
                (directory / folder).mkdir(exist_ok=True)
                sf.write(directory / folder / "0_0.wav", np.sin(np.arange(sr*2)*.04)*.2, sr)
        elif script.endswith("extract_f0.py"):
            for folder in ("2a_f0", "2b-f0nsf"):
                (directory / folder).mkdir(exist_ok=True)
                np.save(directory / folder / "0_0.wav.npy", np.ones(200))
        elif script.endswith("extract_hubert_feature.py"):
            (directory / "3_feature768").mkdir(exist_ok=True)
            np.save(directory / "3_feature768" / "0_0.npy", np.ones((100, 768), dtype=np.float32))
        elif script.endswith("train.py"):
            batch = int(args[args.index("-bs")+1])
            self.attempts = getattr(self, "attempts", []) + [batch]
            if getattr(self, "oom", False) and batch > 1:
                raise CommandFailed(1, "CUDA out of memory")
            sr = self.snapshot(job_id)["settings"]["sr"]
            epochs = self.snapshot(job_id)["settings"]["epochs"]
            weights = self.root / "assets" / "weights"
            weights.mkdir(parents=True, exist_ok=True)
            torch.save({"weight": {"test": torch.ones(2)}, "config": [0]*18, "sr": sr,
                        "f0": 1, "version": "v2", "info": f"{epochs}epoch"}, weights / (job_id + ".pth"))
        elif script.endswith("train_index.py"):
            if getattr(self, "fail_index", False):
                raise CommandFailed(1, "test index error")
            import faiss
            index = faiss.IndexFlatL2(768)
            index.add(np.ones((100, 768), dtype=np.float32))
            from tools.faiss_io import write_index
            write_index(index, directory / "added_test_v2.index")


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs" / "v1").mkdir(parents=True)
        shutil_config = read_json(ROOT / "configs" / "v1" / "40k.json")
        atomic_json(self.root / "configs" / "v1" / "40k.json", shutil_config)
        self.source = self.root / "中文 素材 (1).wav"
        sf.write(self.source, .2*np.sin(np.arange(32000*3)*2*np.pi*220/32000), 32000)
        self.manager = FakeManager(self.root)

    def tearDown(self):
        self.manager.shutdown()
        if self.manager.thread:
            self.manager.thread.join(timeout=10)
        self.temp.cleanup()

    def ready(self, manager=None):
        manager = manager or self.manager
        job_id = manager.create("自检音色", [str(self.source)])
        original = analyze_audio
        with patch("rvc_wizard.backend.analyze_audio", side_effect=lambda path, root, proc, cancel: original(path, ROOT, proc, cancel)):
            manager.check(job_id)
            wait(manager)
        self.assertEqual(manager.snapshot(job_id)["status"], "ready")
        return job_id

    def test_import_duplicate_names_and_hashes(self):
        other = self.root / "sub" / self.source.name
        other.parent.mkdir()
        sf.write(other, .1*np.sin(np.arange(32000*2)*.07), 32000)
        job = self.manager.create("同名素材", [str(self.source), str(other), str(self.source)])
        files = self.manager.snapshot(job)["files"]
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["original_name"], files[1]["original_name"])
        self.assertNotEqual(files[0]["path"], files[1]["path"])
        self.manager.remove_file(job, files[0]["id"])
        self.assertTrue(self.source.exists())
        self.assertEqual(len(self.manager.snapshot(job)["files"]), 1)

    def test_silent_empty_broken_and_long_audio(self):
        for name, data in [("silent.wav", np.zeros(32000)), ("long.wav", np.tile(.2*np.sin(np.arange(32000)*.04), 90))]:
            path = self.root / name
            sf.write(path, data, 32000)
            report = analyze_audio(path, ROOT)
            self.assertEqual(report["ok"], name == "long.wav")
            if name == "long.wav":
                self.assertAlmostEqual(report["duration"], 90, places=1)
        for name, content in [("empty.wav", b""), ("broken.mp3", b"not an audio file")]:
            path = self.root / name
            path.write_bytes(content)
            self.assertFalse(analyze_audio(path, ROOT)["ok"])

    def test_wav_flac_mp3_decode(self):
        from rvc_wizard.backend import hidden_process
        for extension in (".flac", ".mp3"):
            path = self.source.with_suffix(extension)
            process = hidden_process([str(ROOT / "ffmpeg.exe"), "-v", "error", "-y", "-i", str(self.source), str(path)])
            self.assertEqual(process.wait(), 0)
            self.assertTrue(analyze_audio(path, ROOT)["ok"])

    def test_full_pipeline_export_and_resume(self):
        job = self.ready()
        self.manager.configure(job, "快速试跑（20 轮）", "40k", 20, 6, 4, 5)
        self.manager.start(job)
        wait(self.manager)
        result = self.manager.snapshot(job)
        self.assertEqual(result["status"], "completed", result["error"])
        output = self.manager.export(job, result["models"][0]["path"])
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(len(archive.namelist()), 3)
            self.assertFalse(any("source" in name for name in archive.namelist()))
        restored = FakeManager(self.root)
        self.assertEqual(restored.snapshot(job)["status"], "completed")
        restored.configure(job, "自定义", "40k", 25, 6, 4, 5)
        restored.start(job)
        wait(restored)
        self.assertEqual(restored.snapshot(job)["status"], "completed")
        self.assertEqual(validate_voice(restored.snapshot(job)["models"][0]["path"])["epoch"], 25)

    def test_oom_fallback_is_bounded(self):
        job = self.ready()
        self.manager.oom = True
        self.manager.start(job)
        wait(self.manager)
        self.assertEqual(self.manager.attempts, [6, 3, 1])
        self.assertEqual(self.manager.snapshot(job)["settings"]["batch_size"], 1)
        self.assertEqual(self.manager.snapshot(job)["status"], "completed")

    def test_index_retry_keeps_voice_and_skips_training(self):
        job = self.ready()
        self.manager.fail_index = True
        self.manager.start(job)
        wait(self.manager)
        self.assertEqual(self.manager.snapshot(job)["status"], "failed")
        self.assertTrue(self.manager.snapshot(job)["models"])
        before = self.manager.attempts[:]
        self.manager.fail_index = False
        self.manager.start(job)
        wait(self.manager)
        self.assertEqual(self.manager.snapshot(job)["status"], "completed")
        self.assertEqual(self.manager.attempts, before)

    def test_interrupted_and_invalid_stage_outputs(self):
        job = self.ready()
        self.manager.update(job, status="running", stage="features")
        restored = FakeManager(self.root)
        self.assertEqual(restored.snapshot(job)["status"], "interrupted")
        self.manager.update(job, status="ready")
        self.manager.start(job)
        wait(self.manager)
        np.save(self.manager.directory(job) / "3_feature768" / "0_0.npy", np.full((2,768), np.nan))
        self.manager.update(job, status="failed")
        self.manager.start(job)
        wait(self.manager)
        self.assertEqual(self.manager.snapshot(job)["status"], "completed")
        self.assertTrue(np.isfinite(np.load(self.manager.directory(job) / "3_feature768" / "0_0.npy")).all())

    def test_atomic_pairs_retention_and_corruption_recovery(self):
        job = self.ready()
        directory = self.manager.directory(job)
        model = torch.nn.Linear(2, 2)
        optimizer = torch.optim.Adam(model.parameters())
        model(torch.ones(1,2)).sum().backward()
        optimizer.step()
        hps = SimpleNamespace(train=SimpleNamespace(learning_rate=1e-4))
        for epoch in (5, 10, 15):
            save_pair(directory, hps, model, model, optimizer, optimizer, epoch)
        manifest = read_json(directory / "wizard-checkpoints.json")
        self.assertEqual([p["epoch"] for p in manifest["pairs"]], [10, 15])
        self.assertFalse((directory / "G_000000005.pth").exists())
        (directory / "D_000000015.pth").write_bytes(b"broken")
        self.manager.update(job, saved_epoch=15)
        self.assertEqual(self.manager._restore_pair(job), 10)
        self.assertEqual(self.manager.snapshot(job)["saved_epoch"], 10)

    def test_settings_locked_after_processing(self):
        job = self.ready()
        self.manager.update(job, completed_stages=["check", "prepare"])
        with self.assertRaises(ValueError):
            self.manager.configure(job, "自定义", "48k", 200, 6, 4, 5)
        with self.assertRaises(ValueError):
            self.manager.add_files(job, [str(self.source)])

    def test_invalid_checkpoint_numbers_fall_back(self):
        job = self.ready()
        directory = self.manager.directory(job)
        model = torch.nn.Linear(2, 2)
        optimizer = torch.optim.Adam(model.parameters())
        hps = SimpleNamespace(train=SimpleNamespace(learning_rate=1e-4))
        save_pair(directory, hps, model, model, optimizer, optimizer, 5)
        with torch.no_grad():
            model.weight[0, 0] = float("nan")
        save_pair(directory, hps, model, model, optimizer, optimizer, 10)
        self.manager.update(job, saved_epoch=10)
        self.assertEqual(self.manager._restore_pair(job), 5)

    def test_busy_preview_preserves_current_input(self):
        job = self.ready()
        current = self.manager.directory(job) / "test-input.wav"
        current.write_bytes(b"current preview source")
        self.manager.active_id = job
        try:
            with self.assertRaisesRegex(ValueError, "已有任务"):
                self.manager.preview(job, "model.pth", str(self.source), 0, .75, .33)
            self.assertEqual(current.read_bytes(), b"current preview source")
        finally:
            self.manager.active_id = None

    def test_missing_dependencies_and_path_escape(self):
        job = self.ready()
        with self.assertRaisesRegex(ValueError, "缺少"):
            JobManager.preflight(self.manager, job)
        with self.assertRaises(ValueError):
            inside(self.root.parent / "outside", self.root)

    def test_global_task_lock_and_stop(self):
        job = self.ready()
        def slow(_):
            while not self.manager.stop_event.is_set():
                time.sleep(.01)
            from rvc_wizard.backend import Cancelled
            raise Cancelled()
        with patch.object(self.manager, "_pipeline", side_effect=slow):
            self.manager.start(job)
            with self.assertRaisesRegex(ValueError, "已有任务"):
                self.manager.start(job)
            self.manager.stop()
            wait(self.manager)
        self.assertEqual(self.manager.snapshot(job)["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
