"""Float audio, effect presets, aligned accompaniment and collision-safe export."""
import os
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd
from rvc_separation.models import ROOT

PRESETS = {"清晰贴近": "clear", "自然空间": "natural", "空灵氛围": "ethereal"}


def plugins():
    folder = str(ROOT / "tools" / "audio_fx")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import pedalboard
    return pedalboard


def stereo(data):
    value = np.asarray(data)
    if np.issubdtype(value.dtype, np.integer):
        value = value.astype(np.float32) / float(max(abs(np.iinfo(value.dtype).min), np.iinfo(value.dtype).max))
    else:
        value = value.astype(np.float32)
    if value.ndim == 1:
        value = np.stack([value, value], axis=1)
    if value.ndim != 2 or value.shape[1] != 2 or not len(value) or not np.isfinite(value).all():
        raise ValueError("音频须为有效的单声道或双声道，不能包含 NaN / Inf。")
    return value


def write(path, data, rate):
    value = stereo(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".partial.wav")
    sf.write(temporary, value, int(rate), subtype="FLOAT")
    validate(temporary)
    os.replace(temporary, path)
    return str(path)


def validate(path):
    info = sf.info(path)
    if info.frames <= 0 or info.channels != 2 or info.samplerate < 16000:
        raise ValueError("处理结果的采样率、声道或时长无效。")
    with sf.SoundFile(path) as stream:
        for block in stream.blocks(blocksize=262144, dtype="float32", always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError("处理结果包含 NaN / Inf。")
    return dict(sample_rate=info.samplerate, frames=info.frames, channels=info.channels, duration=info.duration)


def resample(data, source_rate, target_rate):
    value = stereo(data)
    if source_rate == target_rate:
        return value
    divisor = gcd(int(source_rate), int(target_rate))
    return resample_poly(value, target_rate // divisor, source_rate // divisor, axis=0).astype(np.float32)


def length(data, frames):
    value = stereo(data)
    return np.pad(value, ((0, max(0, frames - len(value))), (0, 0)))[:frames]


def follow_pitch(value):
    value = int(value)
    remainder = value % 12
    return remainder - 12 if remainder > 6 or (remainder == 6 and value < 0) else remainder


def effects(data, rate, preset, strength, emit=lambda e: None, cancelled=lambda: False):
    value = stereo(data)
    amount = float(strength) / 100
    if not 0 <= amount <= 1 or preset not in PRESETS.values():
        raise ValueError("效果预设或强度无效。")
    if amount == 0:
        return value.copy()
    p = plugins()
    board = [p.HighpassFilter(cutoff_frequency_hz=70), p.Compressor(threshold_db=-20, ratio=1.8, attack_ms=15, release_ms=120)]
    if preset == "clear":
        board += [p.PeakFilter(cutoff_frequency_hz=250, gain_db=-1.5, q=.8), p.HighShelfFilter(cutoff_frequency_hz=4500, gain_db=1.5, q=.7)]
    elif preset == "natural":
        board += [p.Reverb(room_size=.35, damping=.65, wet_level=.14, dry_level=1, width=.85)]
    else:
        board += [p.Chorus(rate_hz=.25, depth=.15, centre_delay_ms=7, feedback=0, mix=.08),
                  p.Delay(delay_seconds=.22, feedback=.15, mix=.08),
                  p.Reverb(room_size=.72, damping=.6, wet_level=.32, dry_level=1, width=1)]
    board = p.Pedalboard(board)
    # Continuous plugin state across blocks; append silence so the final word's tail survives.
    tail = 0 if preset == "clear" else int(rate * (3 if preset == "natural" else 8))
    total = len(value) + tail
    output = np.zeros((total, 2), np.float32)
    for start in range(0, total, 65536):
        if cancelled():
            raise InterruptedError("效果处理已停止。")
        count = min(65536, total - start)
        dry = np.zeros((count, 2), np.float32)
        available = max(0, min(count, len(value) - start))
        dry[:available] = value[start:start + available]
        processed = np.asarray(board(dry.T, rate, reset=start == 0), dtype=np.float32).T
        if len(processed) != count:
            raise ValueError("效果器返回了未补偿的缓冲延迟。")
        output[start:start + count] = dry * (1 - amount) + processed * amount
        emit(dict(event="progress", done=start + count, total=total, message="添加人声效果"))
    if tail:
        audible = np.flatnonzero(np.max(np.abs(output[len(value):]), axis=1) > 1e-4)
        end = len(value) + (int(audible[-1]) + 1 + int(.1 * rate) if len(audible) else 0)
        output = output[:min(total, end)]
        if len(output) > len(value):
            fade = min(int(.03 * rate), len(output) - len(value))
            output[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return stereo(output)


def pitch(data, rate, semitones):
    value = stereo(data)
    if not semitones:
        return value.copy()
    if not -24 <= float(semitones) <= 24:
        raise ValueError("伴奏变调须在 -24 至 24 半音之间。")
    p = plugins()
    shifted = np.asarray(p.PitchShift(semitones=float(semitones))(value.T, rate), dtype=np.float32).T
    if shifted.shape != value.shape:
        raise ValueError("伴奏变调的时长或缓冲延迟校验失败。")
    return stereo(shifted)


def mix(voice, backing, rate, shift=0, vocal_db=0, backing_db=0):
    vocal, instrumental = stereo(voice), pitch(backing, rate, shift)
    frames = max(len(vocal), len(instrumental))
    result = length(vocal, frames) * 10 ** (float(vocal_db) / 20) + length(instrumental, frames) * 10 ** (float(backing_db) / 20)
    peak = float(np.max(np.abs(result)))
    gain = min(1., .999 / max(.999, peak))
    return stereo(result * gain), gain


def export(source, folder, name, kind, fmt="WAV"):
    # Existing exporter already handles exclusive names, PCM24 and peak checks.
    from rvc_separation.audio import export_audio
    return export_audio(source, folder, name, kind, fmt=fmt, sample_rate=sf.info(source).samplerate)
