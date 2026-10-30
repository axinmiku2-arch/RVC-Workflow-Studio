"""Small shared helpers; importing this module never starts the original WebUI."""
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = [("prepare", "整理与切片"), ("pitch", "提取音高"),
          ("features", "提取声音特征"), ("train", "训练音色"), ("index", "生成索引")]
DEFAULTS = {"preset": "正式训练（推荐）", "sr": "40k", "epochs": 200,
            "batch_size": 6, "workers": 4, "save_every": 5}
PRESETS = ["正式训练（推荐）", "快速试跑（20 轮）", "自定义"]
PARAMETERS = [
    ("模型版本", "v2", "使用本项目已有的 v2 底模，无需下载或填写路径。"),
    ("采样率", "40k", "常规唱歌的起点。48k 可用于优质、高采样率素材，但不能修复低音质。"),
    ("音高指导", "开启", "保留唱歌的音高信息；这个向导固定开启。"),
    ("音高提取", "RMVPE / 显卡", "自动提取每个片段的音高，无需手工标注。"),
    ("训练轮数", "正式 200 / 试跑 20", "20 轮检查流程；200 轮是优质素材的起点。更多轮数不保证更好。"),
    ("每批训练数量", "6", "适合这台约 12GB 显存的起始值；不足时有限降为 3、1。"),
    ("预处理并行数", "4", "兼顾处理速度、内存占用和电脑响应。"),
    ("显存缓存", "关闭", "不把全部素材放进显存，降低显存不足的概率。"),
    ("保存进度", "每 5 轮", "保留最近两组完整检查点；正常停止还会保存当前完成的轮次。"),
]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def inside(path, parent):
    """Resolve and reject any operation that escapes its managed directory."""
    resolved, root = Path(path).resolve(), Path(parent).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("文件路径超出了这个训练项目的范围。")
    return resolved


def duration_text(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds >= 3600:
        return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分钟"
    return f"{seconds // 60} 分 {seconds % 60} 秒"
