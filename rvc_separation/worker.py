"""Dedicated worker process; only its parent task may stop it."""
import json
import sys
import traceback
from pathlib import Path
from .models import read_json, atomic_json
from .engine import run_file
from tools.gpu_task_lock import GPUTaskLock


def main(request_path):
    request = read_json(request_path)
    stop = Path(request["stop_path"])
    def emit(event):
        print("SEPARATION_EVENT " + json.dumps(event, ensure_ascii=False), flush=True)
    try:
        with GPUTaskLock("一键分离 · " + request["job_id"], cancelled=stop.exists,
                         on_wait=lambda owner: emit(dict(event="waiting", message="等待其他训练 / 分离任务释放显卡…"))):
            results = []
            for index, entry in enumerate(request["files"]):
                if stop.exists():
                    raise InterruptedError("任务已停止。")
                emit(dict(event="file", file_id=entry["id"], file_index=index, file_count=len(request["files"]), message=entry["name"]))
                result = run_file(entry, request["settings"], request["mode"], request["start"], request["duration"],
                                  request["cache"], emit, stop.exists)
                results.append(result)
                atomic_json(request["result_path"], dict(results=results, complete=False))
                emit(dict(event="file_done", file_index=index, file_count=len(request["files"]), message=entry["name"]))
            atomic_json(request["result_path"], dict(results=results, complete=True))
            emit(dict(event="complete", message="处理完成，可以试听。"))
        return 0
    except Exception as error:
        emit(dict(event="error", message=str(error)))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
