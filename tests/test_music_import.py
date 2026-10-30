import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
from rvc_music.backend import retain, safe_name, status_html, approved_imports
from rvc_music.ui import preserve_imported_audio
from rvc_separation.models import sha256


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.flac"
        sf.write(self.source, .1 * np.sin(np.arange(44100) * .05), 44100, subtype="PCM_24")

    def tearDown(self):
        self.temporary.cleanup()

    def test_retained_bytes_and_native_format(self):
        result = retain(self.source, "中文素材_已解密.flac", True, self.root / "store")
        self.assertEqual(Path(result["path"]).read_bytes(), self.source.read_bytes())
        self.assertEqual(sf.info(result["path"]).subtype, "PCM_24")
        self.assertTrue(result["decrypted"])

    def test_repeat_and_name_collision(self):
        first = retain(self.source, "素材.flac", True, self.root / "store")
        again = retain(self.source, "素材.flac", True, self.root / "store")
        sf.write(self.source, np.zeros(44100), 44100)
        second = retain(self.source, "素材.flac", True, self.root / "store")
        self.assertEqual(first["path"], again["path"])
        self.assertNotEqual(first["path"], second["path"])
        self.assertNotEqual(Path(first["path"]).read_bytes(), Path(second["path"]).read_bytes())

    def test_restart_recognizes_only_intact_imports(self):
        store = self.root / "store"
        result = retain(self.source, "素材.flac", True, store)
        self.assertEqual(approved_imports(store), {result["sha256"]:result["path"]})
        Path(result["path"]).write_bytes(b"damaged")
        self.assertEqual(approved_imports(store), {})
        retain(self.source, "素材.flac", True, store)
        self.assertEqual(approved_imports(store), {result["sha256"]:result["path"]})

    def test_invalid_contents_and_format_fail_closed(self):
        broken = self.root / "bad.mp3"
        broken.write_bytes(b"not a music file")
        with self.assertRaises(ValueError):
            retain(broken, "bad.mp3", True, self.root / "store")
        with self.assertRaises(ValueError):
            retain(self.source, "still.ncm", True, self.root / "store")
        self.assertFalse((self.root / "store").exists())

    def test_invalid_duration(self):
        with patch('rvc_music.backend.probe', return_value={"duration":float('nan')}):
            with self.assertRaises(ValueError):
                retain(self.source, "source.flac", True, self.root / "store")

    def test_names_and_html_are_safe(self):
        self.assertEqual(safe_name("../../CON.flac"), "audio_CON.flac")
        self.assertEqual(safe_name('C:\\folder\\中文.flac'), '中文.flac')
        self.assertNotIn('<script>', status_html('<script>', 'error', '"><script>'))

    def test_conversion_does_not_reencode_download(self):
        import gradio as gr
        player = gr.Audio(type="filepath")
        preserve_imported_audio(player, {sha256(self.source)})
        original = self.source.read_bytes()
        result = player.preprocess({"name":str(self.source), "data":None, "is_file":True})
        self.assertEqual(Path(result).read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(sf.info(result).subtype, "PCM_24")

    def test_conversion_uses_retained_name_after_browser_copy(self):
        import gradio as gr
        import shutil
        result = retain(self.source, "歌曲_已解密.flac", True, self.root / "store")
        browser_copy = self.root / "歌曲_已解密_browserhash.flac"
        shutil.copyfile(self.source, browser_copy)
        player = gr.Audio(type="filepath")
        preserve_imported_audio(player, {result["sha256"]:result["path"]})
        self.assertEqual(player.preprocess({"name":str(browser_copy), "data":None, "is_file":True}), result["path"])

    def test_crop_uses_separate_copy(self):
        import gradio as gr
        player = gr.Audio(type="filepath")
        preserve_imported_audio(player, {sha256(self.source)})
        original = self.source.read_bytes()
        result = player.preprocess({"name":str(self.source), "data":None, "is_file":True,"crop_min":0,"crop_max":50})
        self.assertLess(sf.info(result).frames, sf.info(self.source).frames)
        self.assertEqual(self.source.read_bytes(), original)

    def test_encrypted_input_never_reaches_audio_decoder(self):
        import gradio as gr
        for name, contents in (("歌曲.ncm", b"CTENFDAM" + b"encrypted"),
                               ("伪装.mp3", b"CTENFDAM" + b"encrypted"),
                               ("歌曲.qmcflac", b"encrypted")):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(contents)
                player = gr.Audio(type="filepath")
                with patch.object(player, "preprocess") as decoder:
                    preserve_imported_audio(player, {})
                    with self.assertRaises(gr.Error) as caught:
                        player.preprocess({"name":str(path), "is_file":True})
                    self.assertIn("刷新新版页面", str(caught.exception))
                    decoder.assert_not_called()

    def test_launcher_only_reuses_webui_with_import_api(self):
        from rvc_music.launcher import is_current_webui
        current = {"title":"RVC WebUI", "dependencies":[{"api_name":name} for name in
                   ("infer_convert", "music_import_audio", "music_import_decoded")]}
        self.assertTrue(is_current_webui(current))
        self.assertFalse(is_current_webui(dict(current, title="Another app")))
        self.assertFalse(is_current_webui({"title":"RVC WebUI", "dependencies":[{"api_name":"infer_convert"}]}))
        self.assertFalse(is_current_webui(None))


if __name__ == "__main__":
    unittest.main()
