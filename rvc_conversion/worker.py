"""One task-owned process, one GPU lock, then CPU-only effect rendering."""
import json
import sys
import traceback
from pathlib import Path
from tools.gpu_task_lock import GPUTaskLock
from rvc_separation.models import read_json, atomic_json
from .engine import gpu_stages, post_stages


def main(path):
    request = read_json(path)
    stop = Path(request["stop_path"])
    def emit(event):
        print("CONVERSION_EVENT " + json.dumps(event, ensure_ascii=False), flush=True)
    try:
        if request.get("post_only"):
            core = request["core"]
        else:
            with GPUTaskLock("分离与转换 · " + request["id"], cancelled=stop.exists,
                             on_wait=lambda owner: emit(dict(event="waiting", message="等待其他训练／分离任务释放显卡…"))):
                core = gpu_stages(request, emit, stop.exists)
                atomic_json(request["core_path"], core)
        if stop.exists():
            raise InterruptedError("任务已停止。")
        result = post_stages(core, request["settings"], request["cache"], emit, stop.exists)
        atomic_json(request["result_path"], result)
        emit(dict(event="complete", message="处理完成，可以切换试听并导出。"))
        return 0
    except Exception as error:
        emit(dict(event="error", message=str(error)))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
