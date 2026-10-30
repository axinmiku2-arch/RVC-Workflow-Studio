"""Stage-addressed processing: changing an option only invalidates downstream stages."""
import gc
import hashlib
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from .models import MODELS, ROOT, WEIGHTS, available, atomic_json, read_json, sha256
from .audio import RATE, decode, validate, write_float


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def model_fingerprint(key):
    """Make stage reuse depend on actual model and configuration contents."""
    spec = MODELS[key]
    try:
        return {name: sha256(WEIGHTS / spec[name]) for name in ("weight", "config")}
    except OSError as error:
        raise ValueError(f"{spec['label']} 的模型或配置不可读取，请检查模型管理。") from error


def stages(settings):
    result = []
    if settings["separate"]:
        result.append(("separate", settings["separator"], "分离人声与伴奏"))
    if "vocals" in settings["keep"]:
        if settings["harmony"]:
            result.append(("harmony", settings["karaoke"], "提取主唱 / 去和声"))
        if settings["dereverb"] != "off":
            result.append(("dereverb", "gentle" if settings["dereverb"] == "gentle" else "fused", "去混响 / 回声"))
        if settings["denoise"]:
            result.append(("denoise", "denoise", "降噪"))
    return result


def infer(key, input_path, emit=lambda event: None, allow_unvalidated=False):
    import torch
    tools_path = str(ROOT / "tools")
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)
    from pymss import MSSeparator
    spec = MODELS[key]
    if not allow_unvalidated and not available(key):
        raise ValueError(f"{spec['label']} 尚未完成下载与兼容验证，请先打开模型管理。")
    audio, rate = sf.read(input_path, dtype="float32", always_2d=True)
    if rate != RATE or audio.shape[1] != 2:
        raise ValueError("模型输入须为 44.1kHz 双声道。")
    mix = audio.T.copy()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    original_chunk = spec["chunk"]
    chunks = [original_chunk]
    for ratio in (.75, .5, .25, .125):
        value = max(88200, int(original_chunk * ratio) // 512 * 512)
        if value not in chunks:
            chunks.append(value)
    logger = logging.getLogger("rvc.separation.model")
    logger.setLevel(logging.WARNING)
    logger.addHandler(logging.StreamHandler()) if not logger.handlers else None
    last_progress = [0.]
    def progress(done, total, message):
        if time.monotonic() - last_progress[0] >= .25 or done >= total:
            emit(dict(event="progress", done=float(done), total=float(total), message=str(message)))
            last_progress[0] = time.monotonic()
    started = time.perf_counter()
    for chunk in chunks:
        separator = None
        try:
            if device == "cuda":
                torch.cuda.reset_peak_memory_stats()
            emit(dict(event="settings", model=key, chunk=chunk, seconds=round(chunk / RATE, 2), batch=1,
                      message=f"{spec['label']} · 片段 {chunk / RATE:.2f} 秒 · 批量 1"))
            separator = MSSeparator(spec["family"], str(WEIGHTS / spec["weight"]), str(WEIGHTS / spec["config"]),
                device=device, logger=logger, use_tta=False, progress_callback=progress,
                inference_params={"chunk_size": chunk, "batch_size": 1, "overlap_size": int(chunk * (1 - 1 / spec["overlap"])),
                                  "normalize": False, "standardize": False, "use_amp": device == "cuda"})
            separator.config.training.use_amp = device == "cuda"
            output = separator.separate(mix, pbar=False)
            arrays = []
            for stem in spec["stems"]:
                if stem not in output:
                    raise ValueError(f"{key} 输出名不符：期望 {spec['stems']}，实际 {list(output)}")
                # pymss returns frames x channels; the internal chain uses channels x frames.
                data = np.asarray(output[stem], dtype=np.float32).T.copy()
                if data.shape != mix.shape or not np.isfinite(data).all():
                    raise ValueError(f"{key} 输出校验失败：{data.shape} / {mix.shape}，有限数值={np.isfinite(data).all()}")
                arrays.append(data)
            metrics = dict(model=key, chunk=chunk, overlap=spec["overlap"], batch=1, amp=device == "cuda", device=device,
                           seconds=time.perf_counter() - started, peak_vram_mb=torch.cuda.max_memory_allocated() / 1024**2 if device == "cuda" else 0,
                           stems=spec["stems"], frames=mix.shape[1], sample_rate=RATE, channels=2)
            return arrays, metrics
        except (torch.cuda.OutOfMemoryError, RuntimeError) as error:
            if "out of memory" not in str(error).lower() or chunk == chunks[-1]:
                raise
            emit(dict(event="status", message=f"显存不足，缩短 {spec['label']} 的片段后重试；保持同一模型。"))
        finally:
            if separator is not None:
                separator.close()
                del separator
            gc.collect()
            if device == "cuda":
                torch.cuda.empty_cache()
    raise RuntimeError("显存不足，请关闭其他占用显存的任务后重试。")


RESULT_LABELS = {"original": "原声", "vocals": "分离人声", "instrumental": "伴奏", "lead": "主唱", "harmony": "和声及移除部分",
                 "dereverb": "去混响人声", "reverb": "移除的混响 / 回声", "denoise": "降噪人声", "noise": "移除的噪声", "final": "最终干声"}


def run_file(entry, settings, mode, start, duration, cache, emit=lambda e: None, cancelled=lambda: False):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    chain = signature(dict(source=entry["sha256"], track=entry["track"], mode=mode, start=start if mode == "preview" else 0,
                           duration=duration if mode == "preview" else None, engine=1))
    decoded = cache / chain
    decoded.mkdir(exist_ok=True)
    input_path = decoded / "original.wav"
    if not input_path.exists():
        emit(dict(event="status", message="解码所选音轨…"))
        if shutil.disk_usage(cache).free < max(0, (duration if mode == "preview" else entry["duration"]) * RATE * 8) + 256 * 1024**2:
            raise OSError("任务目录磁盘空间不足。")
        decode(entry["path"], input_path, entry["track"], start if mode == "preview" else 0, duration if mode == "preview" else None)
    info = validate(input_path)
    outputs = {"original": str(input_path)}
    current = str(input_path)
    metrics = []
    plan = stages(settings)
    for index, (stage, model, label) in enumerate(plan):
        if cancelled():
            raise InterruptedError("已停止，可以继续。")
        chain = signature(dict(parent=chain, stage=stage, model=model, files=model_fingerprint(model), engine=2))
        directory = cache / chain
        directory.mkdir(exist_ok=True)
        metadata = directory / "stage.json"
        cached = read_json(metadata, {}) or {}
        emit(dict(event="stage", stage=stage, stage_index=index, stage_count=len(plan), message=label))
        if cached and all(Path(p).exists() for p in cached.get("outputs", {}).values()) and cached.get("outputs"):
            emit(dict(event="status", message=label + " · 使用已完成阶段"))
            outputs.update(cached["outputs"])
            current = cached["primary"]
            metrics.append(dict(cached["metrics"], reused=True))
            continue
        def stage_event(event):
            if cancelled():
                raise InterruptedError("已停止，可以继续。")
            emit(dict(event, stage=stage, stage_index=index, stage_count=len(plan)))
        arrays, measurement = infer(model, current, stage_event)
        primary_name, residual_name = {"separate": ("vocals", "instrumental"), "harmony": ("lead", "harmony"),
                                      "dereverb": ("dereverb", "reverb"), "denoise": ("denoise", "noise")}[stage]
        produced = {primary_name: write_float(directory / (primary_name + ".wav"), arrays[0]),
                    residual_name: write_float(directory / (residual_name + ".wav"), arrays[1])}
        current = produced[primary_name]
        atomic_json(metadata, dict(outputs=produced, primary=current, metrics=measurement))
        outputs.update(produced)
        metrics.append(measurement)
    if "vocals" in settings["keep"]:
        outputs["final"] = current
    return dict(file_id=entry["id"], original_name=entry["name"], outputs=outputs, metrics=metrics, audio=info, track=entry["track"])
