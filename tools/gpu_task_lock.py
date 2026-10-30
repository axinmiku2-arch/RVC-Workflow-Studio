"""Cross-process GPU execution guard. It never terminates another owner."""
import functools
import inspect
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GPUWaitCancelled(RuntimeError):
    pass


class GPUTaskLock:
    def __init__(self, label, cancelled=lambda: False, on_wait=lambda owner: None, root=ROOT, filename=".rvc-gpu.lock"):
        self.label, self.cancelled, self.on_wait = label, cancelled, on_wait
        self.path = Path(root) / "logs" / filename
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), "r+b", buffering=0)
        if self.path.stat().st_size < 4097:
            self.stream.seek(4096)
            self.stream.write(b"0")
        last = 0
        try:
            while True:
                if self.cancelled():
                    raise GPUWaitCancelled("已取消显卡排队。")
                try:
                    self.stream.seek(4096)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() - last > 2:
                        self.stream.seek(0)
                        owner = self.stream.read(2048).decode("utf-8", errors="replace").strip()
                        self.on_wait(owner)
                        last = time.monotonic()
                    time.sleep(.2)
            data = json.dumps({"task": self.label, "pid": os.getpid(), "started": time.time()}, ensure_ascii=False).encode("utf-8")
            self.stream.seek(0)
            self.stream.write(data.ljust(2048, b" "))
            return self
        except BaseException:
            self.stream.close()
            self.stream = None
            raise

    def release(self):
        if self.stream:
            self.stream.seek(0)
            self.stream.write(b" " * 2048)
            self.stream.seek(4096)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()


def gpu_serialized(label):
    def decorator(fn):
        if inspect.isgeneratorfunction(fn):
            @functools.wraps(fn)
            def generated(*args, **kwargs):
                with GPUTaskLock(label):
                    yield from fn(*args, **kwargs)
            return generated
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with GPUTaskLock(label):
                return fn(*args, **kwargs)
        return wrapped
    return decorator
