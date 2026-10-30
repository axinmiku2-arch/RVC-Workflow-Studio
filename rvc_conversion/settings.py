"""Immutable request settings shared by the UI and isolated worker."""
import math
from pathlib import Path
from rvc_separation.models import ROOT, MODELS, available
from rvc_separation.engine import stages

DEFAULTS = dict(separate=False, separator="leap", harmony=False, karaoke="karaoke", dereverb="gentle", denoise=False,
                effects=False, preset="ethereal", strength=35, song=False, backing_pitch=0, vocal_db=0, backing_db=0)


def normalize(value):
    result = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    for key in ("separate", "harmony", "denoise", "effects", "song"):
        result[key] = bool(result[key])
    if result["separator"] not in {"leap", "deux", "viper"} or result["karaoke"] not in {"karaoke", "old_karaoke"}:
        raise ValueError("分离模型选择无效。")
    if result["dereverb"] not in {"off", "gentle", "fused"} or result["preset"] not in {"clear", "natural", "ethereal"}:
        raise ValueError("去混响或效果预设无效。")
    for key, low, high in (("strength", 0, 100), ("backing_pitch", -24, 24), ("vocal_db", -24, 12), ("backing_db", -24, 12)):
        result[key] = float(result[key])
        if not math.isfinite(result[key]) or not low <= result[key] <= high:
            raise ValueError(f"{key} 超出允许范围。")
    if result["song"] and not result["separate"]:
        raise ValueError("合成完整歌曲需要先启用分离音频。")
    return result


def separation(value):
    return dict(separate=value["separate"], separator=value["separator"], keep=["vocals", "instrumental"],
                harmony=value["harmony"] if value["separate"] else False, karaoke=value["karaoke"],
                dereverb=value["dereverb"] if value["separate"] else "off", denoise=value["denoise"] if value["separate"] else False)


def check_models(settings, model):
    if not model or not Path(model).is_file():
        raise ValueError("请先选择可用的音色模型。")
    for _, key, _ in stages(separation(settings)):
        if not available(key):
            raise ValueError(f"{MODELS[key]['label']} 尚未就绪，请在一键分离向导的模型管理中检查。")


LABELS = {"converted": "转换干声", "effect": "效果人声", "song": "合成歌曲", "final": "转换前干声",
          "vocals": "初次分离人声", "instrumental": "原伴奏", "lead": "主唱", "harmony": "移除的和声",
          "dereverb": "去混响人声", "reverb": "移除的混响", "denoise": "降噪人声", "noise": "移除的噪声", "original": "原声"}
