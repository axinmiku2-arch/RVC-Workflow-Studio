"""Keep the Audio upload surface; intercept encoded music before Audio decoding."""
from pathlib import Path
import gradio as gr
from gradio.context import Context
from .backend import retain, status_html, approved_imports
from rvc_separation.models import sha256


def preserve_imported_audio(component, approved):
    """Gradio 3 otherwise writes PCM16 WAV over its input's MP3/FLAC copy.

    Full imported files stay encoded and lossless. Explicit crops use a separate
    copy so neither cropping nor conversion can change the download artifact.
    Other callers retain the original Audio preprocessing behavior.
    """
    original = component.preprocess

    def preprocess(value):
        if value and value.get("is_file") and Path(value.get("name", "")).is_file():
            path = Path(value["name"])
            digest = sha256(path)
            if digest in approved:
                if value.get("crop_min", 0) == 0 and value.get("crop_max", 100) == 100:
                    return approved[digest] if isinstance(approved, dict) else str(path)
                import shutil
                import tempfile
                with tempfile.NamedTemporaryFile(prefix="rvc-crop-", suffix=path.suffix, delete=False) as file:
                    shutil.copyfile(path, file.name)
                    cropped = dict(value, name=file.name)
                try:
                    return original(cropped)
                finally:
                    Path(file.name).unlink(missing_ok=True)
            # A stale tab or API caller must not pass encrypted bytes to ffmpeg.
            with path.open("rb") as file:
                header = file.read(8)
            if header == b"CTENFDAM" or path.suffix.lower() in {
                ".ncm", ".qmc", ".qmc0", ".qmc2", ".qmc3", ".qmc6",
                ".qmcflac", ".qmcogg", ".tkm", ".bkcmp3", ".bkcflac",
                ".mflac", ".mflac0", ".mgg", ".mgg0", ".mgg1", ".mggl",
                ".tm0", ".tm2", ".tm3", ".tm6", ".kgm", ".kgma", ".vpr",
                ".kwm", ".xm", ".ofl_en",
            }:
                raise gr.Error("文件还未解密。请刷新新版页面后重新拖入，等待“解密完成”再点击转换。")
        return original(value)

    component.preprocess = preprocess


def bind_import(source):
    root = Context.root_block
    approved = approved_imports()
    preserve_imported_audio(source, approved)
    status = gr.HTML(status_html("可直接拖入普通音频或 NCM／QMC 音乐；支持的加密文件会自动解密。"), elem_id="music-import-info")
    download = gr.File(label="下载解密音乐", interactive=False, visible=False, elem_id="music-import-download")
    # These are transport components only. Their File inputs accept binary music
    # without the Audio component trying to decode encrypted data first.
    token = gr.Textbox(value="", elem_id="music-import-token")
    normal = gr.File(type="file", file_count="single", elem_id="music-import-normal")
    decoded = gr.File(type="file", file_count="single", elem_id="music-import-decoded")
    root.css = (root.css or "") + """
    #music-import-token,#music-import-normal,#music-import-decoded {display:none!important}
    #music-import-info {font-size:13px;color:#64748b;min-height:0}
    #music-import-status[data-state=error] {color:#b42318}
    #music-import-status[data-state=ready] {color:#15803d}
    #music-import-download {min-height:0}
    #rvc-source-audio[data-import-busy=true] {opacity:.65}
    """

    def receive(file, ticket, decrypted):
        if file is None:
            return gr.update(), gr.update(), gr.update()
        try:
            result = retain(file.name, getattr(file, "orig_name", Path(file.name).name), decrypted)
            approved[result["sha256"]] = result["path"]
            track = result["tracks"][0]
            message = ("解密完成" if decrypted else "音频已导入") + f"：{result['name']} · {result['duration']:.1f}秒 · {track['sample_rate']}Hz"
            return result["path"], status_html(message, "ready", ticket), gr.update(value=result["path"] if decrypted else None, visible=decrypted)
        except Exception as error:
            return None, status_html("导入失败：" + str(error), "error", ticket), gr.update(value=None, visible=False)

    def transport(file, ticket, decrypted):
        return [*receive(file, ticket, decrypted), None if file is not None else gr.update()]

    normal.change(lambda file, ticket: transport(file, ticket, False), [normal, token], [source, status, download, normal], queue=False, api_name="music_import_audio")
    decoded.change(lambda file, ticket: transport(file, ticket, True), [decoded, token], [source, status, download, decoded], queue=False, api_name="music_import_decoded")
    # Clearing the player also removes its independent decrypted download.
    source.clear(lambda: gr.update(value=None, visible=False), [], download, queue=False)
    root.load(None, [], [], _js=(Path(__file__).parent / "import.js").read_text(encoding="utf-8"))
