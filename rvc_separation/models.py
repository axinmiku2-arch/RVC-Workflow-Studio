"""Pinned model sources, resumable downloads and verified local inventory."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "assets" / "pymss_weights"
STATE = ROOT / "logs" / "separation" / "models.json"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hf(repo, revision, name):
    return f"https://huggingface.co/{repo}/resolve/{revision}/{name}"


MODELS = {
    "leap": dict(label="Leap Xe · 推荐", family="bs_roformer", weight="bs_leap_xe_voc.ckpt", config="leap_xe_config_voc.yaml", size=267796851,
        sha="b739c1d2d87a81cd3dd3844ed9ad0bd678708c7a0a761a03a1aaff9af79a096d", chunk=881559, overlap=2, stems=["vocals", "other"],
        repo="pcunwa/BS-Roformer-Leap", revision="4e47d6662ae82eaa8b4ac4329fe66099a843b48e", prefix="Xe/", license="见作者模型说明"),
    "deux": dict(label="Deux · 对比方案", family="mel_band_roformer", weight="becruily_deux.ckpt", config="config_deux_becruily.yaml", size=435006815,
        sha="10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa", chunk=573300, overlap=2, stems=["Vocals", "Instrumental"],
        repo="becruily/mel-band-roformer-deux", revision="2da74427d682a3df47a774378fc24d7a1a0cdaad", license="CC BY-NC 4.0"),
    "karaoke": dict(label="BS Karaoke · 推荐主唱提取", family="bs_roformer", weight="bs_roformer_karaoke_frazer_becruily.ckpt", config="config_karaoke_frazer_becruily.yaml", size=204436907,
        sha="eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9", chunk=882000, overlap=4, stems=["Vocals", "Instrumental"],
        repo="becruily/bs-roformer-karaoke", revision="f7849ae934209184dc288d1018cd8a76a7fc8b3c", license="见作者模型说明"),
    "fused": dict(label="Sucial Fused · 加强去混响／回声", family="mel_band_roformer", weight="dereverb_echo_mbr_fused_0.5_v2_0.25_big_0.25_super.ckpt", config="config_dereverb_echo_mbr_v2.yaml", size=455776577,
        sha="1596b1063238f487d54a0510a8c92cb28c000c803a271dd618ac49efc99ef3f7", chunk=352800, overlap=4, stems=["dry", "other"],
        repo="Sucial/Dereverb-Echo_Mel_Band_Roformer", revision="9c83bf27196213e6107cf0de5ff2d06d56a46876", license="CC BY-NC-SA 4.0"),
    "denoise": dict(label="aufr33 Denoise · 普通版", family="mel_band_roformer", weight="denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt", config="model_mel_band_roformer_denoise.yaml", size=913097300,
        sha=None, chunk=352800, overlap=4, stems=["dry", "other"], release="https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v.1.0.7/", license="见作者模型说明"),
    "gentle": dict(label="anvuew · 温和去混响", family="mel_band_roformer", weight="dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt", config="dereverb_mel_band_roformer_anvuew.yaml", chunk=352800, overlap=2, stems=["noreverb", "reverb"], existing=True),
    "viper": dict(label="ViperX 368 · 快速", family="bs_roformer", weight="model_bs_roformer_ep_368_sdr_12.9628.ckpt", config="model_bs_roformer_ep_368_sdr_12.9628.yaml", chunk=352800, overlap=4, stems=["vocals", "instrumental"], existing=True),
    "old_karaoke": dict(label="旧 Karaoke · 对比", family="mel_band_roformer", weight="model_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt", config="config_mel_band_roformer_karaoke.yaml", chunk=352800, overlap=4, stems=["karaoke", "other"], existing=True),
}


def source(spec, filename):
    if "repo" in spec:
        return hf(spec["repo"], spec["revision"], spec.get("prefix", "") + filename)
    return spec["release"] + filename


def available(key):
    spec = MODELS[key]
    files = all((WEIGHTS / spec[k]).is_file() for k in ("weight", "config"))
    if spec.get("existing"):
        return files
    item = (read_json(STATE, {}) or {}).get(key, {})
    return files and item.get("validated", False) and (WEIGHTS / spec["weight"]).stat().st_size == spec["size"]


def download_file(url, target, expected_size=None, expected_hash=None, progress=lambda *a: None, cancelled=lambda: False):
    """Range continuation, retry, hash verification, then atomic rename."""
    import requests
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (expected_size is None or target.stat().st_size == expected_size):
        digest = sha256(target)
        if expected_hash is None or digest == expected_hash:
            return digest
    partial = target.with_name(target.name + ".part")
    for attempt in range(5):
        if cancelled():
            raise InterruptedError("下载已停止，重新开始会续传。")
        offset = partial.stat().st_size if partial.exists() else 0
        if expected_size and offset == expected_size:
            break
        if expected_size and offset > expected_size:
            partial.unlink()
            offset = 0
        if expected_size and shutil.disk_usage(target.parent).free < expected_size - offset + 128 * 1024**2:
            raise OSError("模型目录磁盘空间不足，请释放空间后重试。")
        try:
            # Fresh signed redirects are needed when resuming a large HF object.
            with requests.get(url + ("&" if "?" in url else "?") + f"download=true&request={int(time.time())}",
                              headers={"Range": f"bytes={offset}-"} if offset else {}, stream=True, timeout=(30, 90)) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    offset = 0  # server ignored Range; restart without duplicating bytes
                if response.status_code == 206 and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("服务器返回的续传位置不正确。")
                total = expected_size or offset + int(response.headers.get("Content-Length", 0))
                last = 0
                with partial.open("ab" if offset else "wb") as stream:
                    for block in response.iter_content(1024 * 1024):
                        if cancelled():
                            raise InterruptedError("下载已停止，重新开始会续传。")
                        if not block:
                            continue
                        stream.write(block)
                        offset += len(block)
                        if time.monotonic() - last > 1:
                            progress(offset, total, target.name)
                            last = time.monotonic()
                    stream.flush()
                    os.fsync(stream.fileno())
            if expected_size and offset != expected_size:
                raise IOError(f"下载未完整：{offset} / {expected_size}")
            break
        except (requests.RequestException, IOError, ValueError):
            if attempt == 4:
                raise
            for _ in range((attempt + 1) * 10):
                if cancelled():
                    raise InterruptedError("下载已停止。")
                time.sleep(.2)
    digest = sha256(partial)
    if expected_hash and digest != expected_hash:
        partial.rename(partial.with_name(partial.name + f".invalid-{int(time.time())}"))
        raise ValueError("模型哈希不匹配；已隔离不完整文件，请重试下载。")
    os.replace(partial, target)
    progress(target.stat().st_size, target.stat().st_size, target.name)
    return digest


def download_models(progress=lambda *a: None, cancelled=lambda: False):
    from tools.gpu_task_lock import GPUTaskLock
    with GPUTaskLock("分离模型下载", cancelled=cancelled, root=ROOT, filename=".separation-download.lock",
                     on_wait=lambda owner: progress(0, 0, "等待已有模型下载完成…")):
        return _download_models(progress, cancelled)


def _download_models(progress, cancelled):
    state = read_json(STATE, {}) or {}
    for key, spec in MODELS.items():
        if spec.get("existing"):
            continue
        hashes = {}
        for kind in ("config", "weight"):
            hashes[kind] = download_file(source(spec, spec[kind]), WEIGHTS / spec[kind],
                spec["size"] if kind == "weight" else None, spec["sha"] if kind == "weight" else None, progress, cancelled)
        previous = state.get(key, {})
        state[key] = dict(downloaded=True, hashes=hashes, source=spec.get("repo", spec.get("release")),
                          revision=spec.get("revision", "v.1.0.7"), validated=previous.get("validated", False) and previous.get("hashes") == hashes)
        atomic_json(STATE, state)
    return state


def register_validation(key, details):
    state = read_json(STATE, {}) or {}
    state.setdefault(key, {}).update(validated=True, validation=details)
    atomic_json(STATE, state)
