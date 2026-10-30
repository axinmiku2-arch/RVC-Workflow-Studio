import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from infer.vc.pipeline import Pipeline
from infer.vc.utils import get_index_path_from_model


class PitchVoicingTests(unittest.TestCase):
    def pipeline(self, values):
        instance = object.__new__(Pipeline)
        instance.sr, instance.window, instance.device = 16000, 160, "cpu"
        instance.model_rmvpe = SimpleNamespace(infer_from_audio=lambda *a, **k: values)
        return instance

    def test_unvoiced_frames_survive_pitch_shift_and_detector_cache(self):
        raw = np.array([0, 200, 0, 0, 300, 0], dtype=np.float32)
        coarse, continuous = self.pipeline(raw).get_f0(np.zeros(960), 6, 12, "rmvpe")
        np.testing.assert_array_equal(continuous, [0, 400, 0, 0, 600, 0])
        np.testing.assert_array_equal(coarse[raw == 0], 1)
        np.testing.assert_array_equal(raw, [0, 200, 0, 0, 300, 0])
        self.assertTrue(((coarse >= 1) & (coarse <= 255)).all())

    def test_silent_input_keeps_all_unvoiced(self):
        coarse, continuous = self.pipeline(np.zeros(20)).get_f0(np.zeros(3200), 20, 0, "rmvpe")
        np.testing.assert_array_equal(coarse, np.ones(20))
        np.testing.assert_array_equal(continuous, np.zeros(20))

    def test_phase_models_find_the_same_index(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "added_IVF531_Flat_nprobe_1_wizard_test_v2.index"
            path.touch()
            with patch.dict(os.environ, outside_index_root=folder, index_root=""):
                for name in ("wizard_test.pth", "wizard_test_e150.pth", "wizard_test_e50_s100.pth"):
                    self.assertEqual(Path(get_index_path_from_model(name)).resolve(), path.resolve())

    def test_training_outputs_keep_unvoiced_labels_and_skip_silence(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, "argv", ["extract_f0.py", "cpu", folder, "1", "rmvpe"]):
                module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "train/dataset/extract_f0.py"))
            try:
                feature = module["FeatureInput"]()
                raw = np.array([0, 200, 0, 300, 0], dtype=np.float32)
                feature.model_rmvpe = SimpleNamespace(infer_from_audio=lambda x, **k: raw if x[0] else np.zeros(5))
                globals_ = feature.compute_f0.__globals__
                voiced_coarse = Path(folder) / "voiced-coarse"
                voiced_continuous = Path(folder) / "voiced-continuous"
                silent_coarse = Path(folder) / "silent-coarse"
                silent_continuous = Path(folder) / "silent-continuous"
                with patch.dict(globals_, load_audio=lambda path, rate: np.ones(800) if path == "voiced.wav" else np.zeros(800)):
                    feature.go([
                        ("voiced.wav", str(voiced_coarse), str(voiced_continuous)),
                        ("silent.wav", str(silent_coarse), str(silent_continuous)),
                    ], "rmvpe")
                saved = np.load(str(voiced_continuous) + ".npy", allow_pickle=False)
                np.testing.assert_array_equal(saved, raw)
                np.testing.assert_array_equal(np.load(str(voiced_coarse) + ".npy")[saved == 0], 1)
                self.assertFalse(Path(str(silent_continuous) + ".npy").exists())
                self.assertFalse(Path(str(silent_coarse) + ".npy").exists())
            finally:
                module["f"].close()


if __name__ == "__main__":
    unittest.main()
