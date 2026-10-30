"""Local, explicit navigation between the two standalone wizards."""
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def open_wizard(kind):
    if kind not in {"training", "separation"}:
        raise ValueError("未知向导。")
    lock_path = ROOT / "logs" / (".wizard-instance.lock" if kind == "training" else ".separation-instance.lock")
    def existing():
        try:
            with lock_path.open("rb", buffering=0) as stream:
                url = stream.read(1024).decode("ascii").strip()
            if not url.startswith("http://127.0.0.1:"):
                return None
            with urlopen(url.split("?")[0].rstrip("/") + "/config", timeout=1) as response:
                return url if response.status == 200 else None
        except Exception:
            return None
    url = existing()
    if url:
        return url
    (ROOT / "logs").mkdir(exist_ok=True)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with (ROOT / "logs" / (kind + "-wizard-launch.log")).open("ab") as log:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", str(ROOT / (kind + "_wizard.py")), "--no-browser"],
                         cwd=ROOT, stdout=log, stderr=log, **options)
    for _ in range(90):
        url = existing()
        if url:
            return url
        time.sleep(.5)
    raise RuntimeError("向导启动失败，请查看 logs 中的启动记录，或双击对应启动文件。")


def install_routes(app):
    from fastapi.responses import HTMLResponse, RedirectResponse
    def launch(kind):
        try:
            return RedirectResponse(open_wizard(kind))
        except Exception as error:
            import html
            return HTMLResponse("<meta charset='utf-8'><p>" + html.escape(str(error)) + "</p>", status_code=503)
    for kind in ("training", "separation"):
        def route(kind=kind):
            return launch(kind)
        app.server_app.add_api_route("/wizard/open-" + kind, route, methods=["GET"])

