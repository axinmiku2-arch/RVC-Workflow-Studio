"""Validate and retain imported audio without changing its encoded contents."""
import html
import math
import os
import re
import shutil
import uuid
from pathlib import Path

from rvc_separation.models import ROOT, sha256, atomic_json, read_json
from rvc_separation.audio import probe

MAX_BYTES = 512 * 1024**2
DIRECTORY = Path(os.environ.get("RVC_MUSIC_IMPORT_DIR", str(ROOT / "logs" / "music_import")))


def approved_imports(directory=None):
    """Recognize retained audio after a restart without rewriting restored input."""
    result = {}
    for manifest in (Path(directory or DIRECTORY) / "cache").glob("*/*.json"):
        data = read_json(manifest) or {}
        name = data.get("name", "")
        if not name or safe_name(name) != name:
            continue
        path = manifest.parent / name
        digest = data.get("sha256")
        if path.is_file() and digest == manifest.parent.name and sha256(path) == digest:
            result[digest] = str(path)
    return result


def status_html(message, state="idle", ticket=""):
    return (f'<div id="music-import-status" role="status" aria-live="polite" '
            f'data-state="{html.escape(state, quote=True)}" data-ticket="{html.escape(ticket, quote=True)}">'
            f'{html.escape(message)}</div>')


def safe_name(name):
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    path = Path(name or "audio.wav")
    stem = path.stem[:140]
    if stem.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        stem = "audio_" + stem
    return stem + path.suffix.lower()


def retain(source, original_name, decrypted=False, directory=None):
    source = Path(source)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES:
        raise ValueError("文件为空或超过512MB，请换一个音频文件。")
    name = safe_name(original_name)
    if decrypted and Path(name).suffix.lower() not in {".mp3", ".flac", ".m4a", ".ogg"}:
        raise ValueError("解密结果不是支持的普通音频格式。")
    # Probe the actual contents, not just the suffix. Failed imports never set
    # the player's value or expose a download of an undecodable result.
    report = probe(source)
    if not math.isfinite(report["duration"]) or report["duration"] <= 0:
        raise ValueError("音频时长无效，请重新选择文件。")
    directory = Path(directory or DIRECTORY)
    digest = sha256(source)
    cache = directory / "cache" / digest
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if not target.exists() or sha256(target) != digest:
        if shutil.disk_usage(cache).free < source.stat().st_size + 32 * 1024**2:
            raise OSError("导入目录磁盘空间不足。")
        partial = cache / (uuid.uuid4().hex + ".partial")
        try:
            shutil.copyfile(source, partial)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    result = dict(path=str(target), name=name, sha256=digest, decrypted=bool(decrypted), **report)
    atomic_json(cache / (name + ".json"), result)
    return result
