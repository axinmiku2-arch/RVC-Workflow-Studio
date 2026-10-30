"""Four independently cached stages; the caller owns the GPU lock exactly once."""
import gc
import os
import sys
import time
from pathlib import Path
import numpy as np
import soundfile as sf
from rvc_separation.models import atomic_json, read_json, sha256, ROOT
from rvc_separation.engine import run_file, signature
from .settings import separation
from . import audio


def cached(metadata):
    result = read_json(metadata, {}) or {}
    return result if result.get("outputs") and all(Path(path).is_file() for path in result["outputs"].values()) else None


def gpu_stages(request, emit, cancelled):
    entry, settings, params = request["entry"], request["settings"], request["conversion"]
    if sha256(params["model"]) != params["model_sha256"]:
        raise ValueError("音色模型文件已变化，请重新提交转换以使用新版本。")
    if params.get("index_sha256") and sha256(params["index"]) != params["index_sha256"]:
        raise ValueError("索引文件已变化，请重新提交转换。")
    separated = run_file(entry, separation(settings), request["mode"], request["start"], request["duration"],
                         Path(request["cache"]) / "separation", emit, cancelled)
    key = signature(dict(source=sha256(separated["outputs"]["final"]), conversion=params, engine=1))
    directory = Path(request["cache"]) / "conversion" / key
    directory.mkdir(parents=True, exist_ok=True)
    metadata = directory / "stage.json"
    outputs = dict(separated["outputs"])
    prior = cached(metadata)
    emit(dict(event="stage", stage="conversion", message="转换音色"))
    if prior:
        outputs.update(prior["outputs"])
        emit(dict(event="status", message="转换音色 · 使用已完成阶段"))
        return dict(outputs=outputs, conversion_key=key, metrics=separated["metrics"] + [dict(prior["metrics"], reused=True)])
    if cancelled():
        raise InterruptedError("任务已停止。")
    sys.argv = [sys.argv[0], "--noautoopen"]
    model = Path(params["model"])
    os.environ["weight_root"] = str(model.parent)
    os.environ.setdefault("index_root", str(ROOT / "logs"))
    os.environ.setdefault("outside_index_root", str(ROOT / "assets" / "indices"))
    os.environ.setdefault("rmvpe_root", str(ROOT / "assets" / "rmvpe"))
    os.environ.setdefault("RVC_CUDA_GRAPH", "0")
    from configs.config import Config
    from infer.vc.modules import VC
    import torch
    started = time.perf_counter()
    vc = VC(Config())
    try:
        vc.get_vc(model.name)
        status, converted = vc.vc_single(params["speaker"], separated["outputs"]["final"], params["transpose"], params["f0"],
            params["index"], params["index_rate"], params["resample_sr"], params["rms_mix"], params["protect"])
        if not converted or converted[0] is None or converted[1] is None:
            raise RuntimeError(status)
        rate, wave = converted
        value = audio.stereo(wave)
        source = sf.info(separated["outputs"]["final"])
        frames = round(source.frames * rate / source.samplerate)
        difference = len(value) - frames
        if abs(difference) > round(.1 * rate):
            raise ValueError(f"转换时长偏差 {difference / rate:.3f} 秒，未合成以免人声与伴奏错位。")
        value = audio.length(value, frames)
        output = audio.write(directory / "converted.wav", value, rate)
        measurement = dict(stage="conversion", seconds=time.perf_counter() - started, sample_rate=int(rate), frames=frames,
                           end_adjustment_frames=difference, status=status, model=model.name)
        atomic_json(metadata, dict(outputs={"converted": output}, metrics=measurement))
        outputs["converted"] = output
        return dict(outputs=outputs, conversion_key=key, metrics=separated["metrics"] + [measurement])
    finally:
        del vc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def post_stages(core, settings, cache, emit=lambda e: None, cancelled=lambda: False):
    outputs = {key: path for key, path in core["outputs"].items() if key not in {"effect", "song"}}
    value, rate = sf.read(outputs["converted"], dtype="float32", always_2d=True)
    key = core["conversion_key"]
    metrics = list(core["metrics"])
    if settings["effects"]:
        effect_key = signature(dict(parent=key, preset=settings["preset"], strength=settings["strength"], engine=1))
        directory = Path(cache) / "effects" / effect_key
        metadata = directory / "stage.json"
        emit(dict(event="stage", stage="effects", message="添加人声效果"))
        prior = cached(metadata)
        if prior:
            output = prior["outputs"]["effect"]
            metrics.append(dict(prior["metrics"], reused=True))
        else:
            started = time.perf_counter()
            output = audio.write(directory / "effect.wav", audio.effects(value, rate, settings["preset"], settings["strength"], emit, cancelled), rate)
            measurement = dict(stage="effects", seconds=time.perf_counter() - started, preset=settings["preset"], strength=settings["strength"])
            atomic_json(metadata, dict(outputs={"effect": output}, metrics=measurement))
            metrics.append(measurement)
        outputs["effect"] = output
        key = effect_key
    if settings["song"]:
        if "instrumental" not in outputs:
            raise ValueError("当前任务没有分离伴奏，无法合成歌曲。")
        song_key = signature(dict(parent=key, backing=sha256(outputs["instrumental"]), pitch=settings["backing_pitch"],
                                  vocal_db=settings["vocal_db"], backing_db=settings["backing_db"], engine=1))
        directory = Path(cache) / "mix" / song_key
        metadata = directory / "stage.json"
        emit(dict(event="stage", stage="mix", message="合成完整歌曲"))
        prior = cached(metadata)
        if prior:
            output = prior["outputs"]["song"]
            metrics.append(dict(prior["metrics"], reused=True))
        else:
            if cancelled():
                raise InterruptedError("任务已停止。")
            started = time.perf_counter()
            voice, _ = sf.read(outputs.get("effect", outputs["converted"]), dtype="float32", always_2d=True)
            backing, backing_rate = sf.read(outputs["instrumental"], dtype="float32", always_2d=True)
            backing = audio.resample(backing, backing_rate, rate)
            # RVC rounding is compensated only at the end; no time stretching of the vocal.
            backing = audio.length(backing, len(value))
            wave, gain = audio.mix(voice, backing, rate, settings["backing_pitch"], settings["vocal_db"], settings["backing_db"])
            output = audio.write(directory / "song.wav", wave, rate)
            measurement = dict(stage="mix", seconds=time.perf_counter() - started, gain=gain, pitch=settings["backing_pitch"])
            atomic_json(metadata, dict(outputs={"song": output}, metrics=measurement))
            metrics.append(measurement)
        outputs["song"] = output
    for name in ("converted", "effect", "song"):
        if name in outputs:
            audio.validate(outputs[name])
    return dict(outputs=outputs, metrics=metrics, conversion_key=core["conversion_key"])
