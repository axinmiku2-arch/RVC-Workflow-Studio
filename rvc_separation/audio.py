"""Explicit audio-track decoding and lossless, clipping-safe export."""
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
from .models import ROOT

RATE = 44100


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def probe(path):
    result = subprocess.run([str(ROOT / "ffprobe.exe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, timeout=60, **process_options())
    if result.returncode:
        raise ValueError("无法读取这个文件，请确认它含有可解码的音轨。")
    data = json.loads(result.stdout)
    tracks = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            tags = stream.get("tags", {})
            tracks.append(dict(index=stream["index"], codec=stream.get("codec_name", ""), channels=stream.get("channels", 0),
                               sample_rate=int(stream.get("sample_rate", 0)), language=tags.get("language", ""), title=tags.get("title", ""),
                               duration=float(stream.get("duration") or data.get("format", {}).get("duration") or 0)))
    if not tracks:
        raise ValueError("文件中没有音轨。")
    return dict(tracks=tracks, duration=float(data.get("format", {}).get("duration") or tracks[0]["duration"] or 0))


def decode(source, target, track=0, start=0, duration=None, on_process=lambda p: None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".partial.wav")
    command = [str(ROOT / "ffmpeg.exe"), "-v", "error", "-nostdin", "-y", "-i", str(source)]
    if start:
        command += ["-ss", str(start)]
    if duration is not None:
        command += ["-t", str(duration)]
    command += ["-map", f"0:a:{int(track)}", "-vn", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_f32le", str(tmp)]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **process_options())
    on_process(proc)
    try:
        _, error = proc.communicate()
        if proc.returncode:
            raise ValueError("音轨解码失败：" + error.decode("utf-8", errors="replace")[-1500:])
    finally:
        on_process(None)
    validate(tmp)
    os.replace(tmp, target)
    return str(target)


def validate(path, frames=None):
    info = sf.info(path)
    if info.samplerate != RATE or info.channels != 2 or info.frames <= 0 or (frames is not None and info.frames != frames):
        raise ValueError("音频时长、采样率或声道校验失败。")
    with sf.SoundFile(path) as stream:
        for block in stream.blocks(blocksize=262144, dtype="float32", always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError("音频包含无效数值。")
    return dict(sample_rate=info.samplerate, channels=info.channels, frames=info.frames, duration=info.duration)


def write_float(path, waveform):
    data = np.asarray(waveform, dtype=np.float32)
    if data.ndim != 2 or data.shape[0] != 2 or data.shape[1] <= 0 or not np.isfinite(data).all():
        raise ValueError("模型输出不完整或包含 NaN / Inf。")
    path = Path(path)
    tmp = path.with_name(path.stem + ".partial.wav")
    sf.write(tmp, data.T, RATE, subtype="FLOAT")
    validate(tmp, data.shape[1])
    os.replace(tmp, path)
    return str(path)


def export_audio(source, folder, original_name, kind, fmt="WAV", mono=False, sample_rate=RATE):
    """Reserve a collision-free destination; attenuate only when necessary."""
    folder = Path(str(folder).strip().strip('"')).expanduser()
    if not folder.is_absolute():
        folder = ROOT / folder
    folder.mkdir(parents=True, exist_ok=True)
    info = sf.info(source)
    if shutil.disk_usage(folder).free < info.frames * (1 if mono else 2) * 3 + 32 * 1024**2:
        raise OSError("导出目录磁盘空间不足。")
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(original_name).stem).strip(" .") or "audio"
    if stem.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        stem = "audio_" + stem
    stem = stem[:140]
    fmt = fmt.upper()
    if fmt not in {"WAV", "FLAC"}:
        raise ValueError("请选择 WAV 或 FLAC。")
    suffix = ".wav" if fmt == "WAV" else ".flac"
    destination = None
    for index in range(100000):
        candidate = folder / f"{stem}_{kind}{'_' + str(index + 1) if index else ''}{suffix}"
        try:
            with candidate.open("xb"):
                pass
            destination = candidate
            break
        except FileExistsError:
            continue
    if destination is None:
        raise OSError("无法分配导出文件名。")
    temporary = folder / (".separation-export-" + uuid.uuid4().hex + suffix)
    try:
        peak = 0.0
        with sf.SoundFile(source) as stream:
            for block in stream.blocks(blocksize=262144, dtype="float32", always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError("导出源包含无效数值。")
                if mono:
                    block = block.mean(axis=1, keepdims=True)
                peak = max(peak, float(np.abs(block).max()))
        gain = min(1.0, .999 / max(peak, .999))
        if int(sample_rate) != info.samplerate:
            raise ValueError("导出采样率须与处理结果一致。")
        with sf.SoundFile(source) as stream, sf.SoundFile(temporary, mode="w", samplerate=int(sample_rate),
                channels=1 if mono else 2, format=fmt, subtype="PCM_24") as output:
            for block in stream.blocks(blocksize=262144, dtype="float32", always_2d=True):
                if mono:
                    block = block.mean(axis=1, keepdims=True)
                output.write(block * gain)
        os.replace(temporary, destination)
        return dict(path=str(destination), gain=gain, format=fmt, channels=1 if mono else 2)
    except BaseException:
        destination.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise
