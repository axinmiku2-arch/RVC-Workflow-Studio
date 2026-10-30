"""Standalone separation entry point, without importing the legacy WebUI."""
import argparse
import os
import socket
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class InstanceLock:
    def __init__(self):
        self.path = ROOT / "logs" / ".separation-instance.lock"
        self.path.parent.mkdir(exist_ok=True)
        self.stream = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), "r+b", buffering=0)
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

    def close(self):
        self.stream.close()


def install_routes(app):
    from fastapi.responses import HTMLResponse, RedirectResponse
    from tools.wizard_links import install_routes as links, open_wizard
    links(app)
    app.server_app.add_api_route("/separation/open-training", lambda: RedirectResponse(open_wizard("training")), methods=["GET"])
    app.server_app.add_api_route("/separation/help", lambda: HTMLResponse(HELP), methods=["GET"])


HELP = """<!doctype html><meta charset="utf-8"><title>一键分离使用说明</title><style>body{font-family:'Microsoft YaHei',sans-serif;max-width:860px;margin:50px auto;padding:0 24px;color:#243840;line-height:1.9;background:#f5f7f8}h1,h2,a{color:#0f766e}section{background:white;padding:24px;border-radius:16px;margin:20px 0}</style>
<h1>RVC 一键分离向导</h1><section><h2>从歌曲到干声</h2><ol><li>拖入音频或视频，点击导入素材。多音轨视频可逐个选择音轨。</li><li>默认开启 Leap Xe 分离与温和去混响，保留人声。伴奏可以同时保留。</li><li>选择副歌等典型片段，先试处理 30 秒。试听原声、分离人声与最终干声。</li><li>满意后处理全部整首。关闭网页不会停止后台任务；刷新可找回任务。</li><li>试听完整结果，勾选文件及结果，浏览或填写导出文件夹，点击导出。</li></ol></section>
<section><h2>如何勾选功能</h2><p>伴奏密集时可以对比 Leap Xe 与 Deux；想快速试效果可用现有 ViperX。去和声适合提取主唱，但会移除部分重叠演唱。温和去混响优先保留音色和尾音；加强档处理延迟回声，也可能减少和声与叠唱。降噪只在噪声明显时开启，过度清理可能损伤气声。已经提取的人声可以关闭分离，直接清理。</p><p>不同歌曲的效果不同，请以试听为准。没有自动切除间奏、气声或静音。</p></section>
<section><h2>继续、模型与导出</h2><p>停止只结束本任务的子进程，完整阶段保留。继续 / 重试会复用未改变的步骤。更换功能后需重新处理；试段与整首分别保存。显存不足时会缩短同一模型的片段长度，并显示实际参数。训练、原 WebUI 与分离的 GPU 执行入口共享任务锁，排队运行。</p><p>模型管理支持续传和重试，只有下载校验与真实推理验证通过后才可用。默认导出 44.1kHz、双声道、24 位 WAV，也可选 FLAC 或单声道。重名自动编号，必要时仅降低音量以防削波。试听缓存不能作为整首导出。导出的干声可拖入训练向导，不会自动开始训练。</p><p>Deux：CC BY-NC 4.0；Sucial Fused：CC BY-NC-SA 4.0。其他模型许可请查看作者发布页面。</p></section>"""


def main():
    parser = argparse.ArgumentParser(description="RVC 一键分离向导")
    parser.add_argument("--port", type=int, default=7899)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare-models", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.update(GRADIO_ANALYTICS_ENABLED="False", NO_PROXY="localhost,127.0.0.1,::1", no_proxy="localhost,127.0.0.1,::1",
                      PATH=str(ROOT) + os.pathsep + str(ROOT / "runtime") + os.pathsep + os.environ.get("PATH", ""))
    cache = ROOT / "logs" / "separation" / ".upload-cache"
    cache.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(cache)
    os.environ.update(TEMP=str(cache), TMP=str(cache), GRADIO_TEMP_DIR=str(cache))
    try:
        instance = InstanceLock()
    except OSError:
        with (ROOT / "logs" / ".separation-instance.lock").open("rb", buffering=0) as stream:
            url = stream.read(1024).decode("ascii").strip()
        if url.startswith("http://127.0.0.1:"):
            print("分离向导已经运行：" + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise RuntimeError("分离向导正在启动，请稍候再试。")
    from rvc_separation.backend import JobManager
    from rvc_separation.ui import build_ui
    manager = JobManager(ROOT)
    app = build_ui(manager)
    try:
        for port in range(max(1024, args.port), min(args.port + 100, 65536)):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    continue
            try:
                app.queue(concurrency_count=4, max_size=32).launch(server_name="127.0.0.1", server_port=port,
                    inbrowser=False, share=False, quiet=True, prevent_thread_lock=True)
                break
            except OSError:
                continue
        else:
            raise RuntimeError("没有可用端口。")
        install_routes(app)
        url = f"http://127.0.0.1:{port}/?__theme=light"
        instance.record(url)
        print("RVC 一键分离向导已启动：" + url, flush=True)
        print("关闭网页后后台继续处理；双击启动文件可重新打开。", flush=True)
        if args.prepare_models:
            manager.download()
        if not args.no_browser:
            webbrowser.open(url)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("正在停止本向导并保存任务。", flush=True)
    finally:
        manager.shutdown()
        if manager.thread:
            manager.thread.join(timeout=8)
        app.close()
        instance.close()


if __name__ == "__main__":
    main()
