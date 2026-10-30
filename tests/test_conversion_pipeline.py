import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
from rvc_conversion import audio
from rvc_conversion.settings import normalize, separation
from rvc_conversion.engine import post_stages, gpu_stages
from rvc_conversion.backend import Manager
from rvc_separation.models import atomic_json, sha256


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wave = np.zeros((44100, 2), np.float32)
        self.wave[-3000:-1000] = .15
        self.voice = audio.write(self.root / 'voice.wav', self.wave, 44100)
        self.backing = audio.write(self.root / 'backing.wav', self.wave * 2, 44100)

    def tearDown(self):
        self.temp.cleanup()

    def test_integer_conversion_and_mono(self):
        result = audio.stereo(np.array([-32768, 0, 32767], np.int16))
        self.assertEqual(result.shape, (3, 2))
        self.assertEqual(result[0, 0], -1)
        self.assertLess(result[2, 0], 1)

    def test_invalid_values_rejected(self):
        with self.assertRaises(ValueError):
            audio.stereo(np.array([np.nan]))
        with self.assertRaises(ValueError):
            normalize({'strength': float('inf')})

    def test_settings_dependencies(self):
        with self.assertRaises(ValueError):
            normalize({'song': True})
        result = separation(normalize({}))
        self.assertFalse(result['separate'])
        self.assertEqual(result['dereverb'], 'off')

    def test_follow_pitch(self):
        for src, target in [(-14, -2), (-12, 0), (12, 0), (14, 2), (-6, -6), (6, 6), (-26, -2)]:
            self.assertEqual(audio.follow_pitch(src), target)

    def test_zero_strength_exact_bypass(self):
        for preset in audio.PRESETS.values():
            self.assertTrue(np.array_equal(self.wave, audio.effects(self.wave, 44100, preset, 0)))

    def test_effect_tail_and_file_state(self):
        result = audio.effects(self.wave, 44100, 'ethereal', 35)
        self.assertGreater(len(result), len(self.wave))
        self.assertTrue(np.isfinite(result).all())
        second = audio.effects(self.wave, 44100, 'ethereal', 35)
        np.testing.assert_array_equal(second, result)

    def test_continuous_effect_block_boundaries(self):
        value = np.tile(self.wave, (5, 1))
        result = audio.effects(value, 44100, 'natural', 35)
        self.assertGreaterEqual(len(result), len(value))
        self.assertTrue(np.isfinite(result).all())

    def test_pitch_timing_and_rate(self):
        for rate in (32000, 40000, 48000):
            wave = audio.resample(self.wave, 44100, rate)
            for semitone in (-2, 2, 12):
                result = audio.pitch(wave, rate, semitone)
                self.assertEqual(result.shape, wave.shape)
                self.assertTrue(np.isfinite(result).all())

    def test_mix_peak_and_stereo(self):
        voice = np.ones((100, 2), np.float32)
        backing = np.zeros((80, 2), np.float32)
        backing[:, 0] = 1
        result, gain = audio.mix(voice, backing, 44100)
        self.assertEqual(result.shape, (100, 2))
        self.assertLessEqual(float(np.abs(result).max()), .999001)
        self.assertLess(gain, 1)
        self.assertNotEqual(result[0, 0], result[0, 1])

    def test_native_rate_export_no_overwrite(self):
        source = audio.write(self.root / '原声.wav', audio.resample(self.wave, 44100, 40000), 40000)
        for fmt in ('WAV', 'FLAC'):
            first = audio.export(source, self.root / '中文目录', '歌曲', '干声', fmt)
            second = audio.export(source, self.root / '中文目录', '歌曲', '干声', fmt)
            self.assertNotEqual(first['path'], second['path'])
            info = sf.info(first['path'])
            self.assertEqual(info.samplerate, 40000)
            self.assertEqual(info.subtype, 'PCM_24')

    def test_post_only_reuses_dry_and_effect(self):
        core = dict(outputs={'converted': self.voice, 'instrumental': self.backing}, conversion_key='test', metrics=[])
        settings = normalize({'separate': True, 'effects': True, 'song': True})
        original = Path(self.voice).read_bytes()
        one = post_stages(core, settings, self.root / 'cache')
        with patch('rvc_conversion.audio.effects', side_effect=AssertionError('effect should be cached')):
            two = post_stages(core, dict(settings, vocal_db=-3), self.root / 'cache')
        self.assertEqual(one['outputs']['effect'], two['outputs']['effect'])
        self.assertNotEqual(one['outputs']['song'], two['outputs']['song'])
        self.assertEqual(Path(self.voice).read_bytes(), original)

    def test_missing_backing_never_silently_mixes(self):
        core = dict(outputs={'converted': self.voice}, conversion_key='test', metrics=[])
        with self.assertRaises(ValueError):
            post_stages(core, normalize({'separate': True, 'song': True}), self.root / 'cache')

    def test_preview_export_blocked(self):
        manager = Manager(self.root / 'manager')
        manager.jobs['sample'] = dict(id='sample', status='completed', mode='preview', result={'outputs': {'converted': self.voice}}, name='试听', updated=1)
        with self.assertRaisesRegex(ValueError, '试听'):
            manager.export('sample', ['converted'], self.root / 'out', 'WAV')

    def test_restore_does_not_touch_separation_jobs(self):
        independent = self.root / 'separation' / 'job_1' / 'job.json'
        atomic_json(independent, {'status': 'running'})
        directory = self.root / 'conversion'
        atomic_json(directory / 'task_1' / 'job.json', {'id': 'task_1', 'status': 'running', 'updated': 1})
        manager = Manager(directory)
        self.assertEqual(manager.snapshot()['status'], 'interrupted')
        self.assertIn('running', independent.read_text(encoding='utf8'))

    def test_model_change_rejected_before_cache(self):
        model = self.root / 'model.pth'
        model.write_bytes(b'first')
        request = dict(entry={}, settings={}, conversion={'model': str(model), 'model_sha256': sha256(model)})
        model.write_bytes(b'second')
        with self.assertRaisesRegex(ValueError, '已变化'):
            gpu_stages(request, lambda e: None, lambda: False)

    def test_post_cancel_and_no_cache_registration(self):
        core = dict(outputs={'converted': self.voice}, conversion_key='test', metrics=[])
        with self.assertRaises(InterruptedError):
            post_stages(core, normalize({'effects': True}), self.root / 'cache', cancelled=lambda: True)
        self.assertEqual(list((self.root / 'cache').rglob('stage.json')), [])

    def test_restore_preserves_intentionally_empty_index(self):
        from rvc_conversion.ui import restored_voice_result
        result = [{'visible': True, 'maximum': 1}, {'visible': True, 'value': .33}, {'visible': True, 'value': .33},
                  {'value': 'automatic.index'}, {'value': 'automatic.index'}]
        job = {'conversion': {'model': str(self.root / 'voice.pth'), 'speaker': 0, 'protect': .2, 'index': ''}}
        restored = restored_voice_result(result, job, 'voice.pth')
        self.assertEqual(restored[3]['value'], '')
        self.assertEqual(restored[4]['value'], 'automatic.index')
        self.assertEqual(restored[1]['value'], .2)
        self.assertIsNone(restored[-1])

    def test_pitch_transients_keep_timeline(self):
        wave = np.zeros((44100 * 3, 2), np.float32)
        wave[44100:44110] = .5
        for shift in (-6, -2, 2, 6):
            shifted = audio.pitch(wave, 44100, shift)
            location = int(np.argmax(np.abs(shifted[:, 0])))
            self.assertLess(abs(location - 44100), 44100 * .04)


if __name__ == '__main__':
    unittest.main()
