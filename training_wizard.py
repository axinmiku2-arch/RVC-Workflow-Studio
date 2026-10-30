"""Standalone entry point. No import of webui.py and no legacy TEMP cleanup."""
import argparse
import os
import socket
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def install_help_route(blocks):
    """Gradio 3.14 serves a new App at launch, separate from blocks.app."""
    from fastapi.responses import HTMLResponse
    from rvc_wizard.guide import guide_html

    blocks.server_app.add_api_route(
        "/wizard/help", lambda: HTMLResponse(guide_html()), methods=["GET"]
    )


class InstanceLock:
    def __init__(self):
        self.path = ROOT / "logs" / ".wizard-instance.lock"
        self.path.parent.mkdir(exist_ok=True)
        self.stream = open(self.path, "r+b" if self.path.exists() else "w+b", buffering=0)
        if self.path.stat().st_size < 4097:
            self.stream.seek(4096)
            self.stream.write(b"0")
        self.stream.seek(4096)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def record(self, url):
        self.stream.seek(0)
        self.stream.write(url.encode("ascii").ljust(1024, b" "))

    @staticmethod
    def previous_url():
        path = ROOT / "logs" / ".wizard-instance.lock"
        with open(path, "rb", buffering=0) as stream:
            return stream.read(1024).decode("ascii").strip()

    def close(self):
        self.stream.close()


def main():
    parser = argparse.ArgumentParser(description="RVC 中文音色训练向导")
    parser.add_argument("--port", type=int, default=7898)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.update(GRADIO_ANALYTICS_ENABLED="False", RVC_CUDA_GRAPH="0", RVC_OFFLINE_CUDA_GRAPH="0",
                      NO_PROXY="localhost,127.0.0.1,::1", no_proxy="localhost,127.0.0.1,::1",
                      PATH=str(ROOT) + os.pathsep + str(ROOT / "runtime") + os.pathsep + os.environ.get("PATH", ""))
    cache = ROOT / "logs" / ".wizard-cache"
    cache.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(cache)
    os.environ.update(TEMP=str(cache), TMP=str(cache), GRADIO_TEMP_DIR=str(cache))
    try:
        instance = InstanceLock()
    except OSError:
        url = InstanceLock.previous_url()
        if url.startswith("http://127.0.0.1:"):
            print("训练向导已经在运行：" + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise RuntimeError("已有向导正在启动，请稍候再试。")
    from rvc_wizard.backend import JobManager
    from rvc_wizard.guide import write_guide
    from rvc_wizard.ui import build_ui
    manager = JobManager(ROOT)
    write_guide(ROOT)
    app = build_ui(manager)
    port = max(1024, min(args.port, 65535))
    try:
        for candidate in range(port, min(port + 100, 65536)):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
            try:
                app.queue(concurrency_count=4, max_size=32).launch(server_name="127.0.0.1", server_port=candidate,
                         inbrowser=False, share=False, quiet=True, prevent_thread_lock=True)
                port = candidate
                break
            except OSError:
                continue
        else:
            raise RuntimeError("没有找到可用端口，请关闭不需要的向导实例后重试。")
        install_help_route(app)
        from tools.wizard_links import install_routes
        install_routes(app)
        url = f"http://127.0.0.1:{port}/?__theme=light"
        instance.record(url)
        print("\nRVC 中文音色训练向导已启动：" + url, flush=True)
        print("保持这个窗口运行。关闭网页不会停止训练。\n", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("正在停止后台任务并保留完整进度…", flush=True)
    finally:
        manager.shutdown()
        if manager.thread:
            manager.thread.join(timeout=8)
        app.close()
        instance.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        print("\n启动失败：" + str(error), flush=True)
