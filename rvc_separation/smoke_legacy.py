"""Build the real legacy UI with an isolated TEMP and validate event signatures."""
import ast
import os
import sys
from .models import ROOT


def main():
    os.chdir(ROOT)
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    sys.argv = [str(ROOT / "webui.py"), "--noautoopen", "--port", "7910"]
    tree = ast.parse((ROOT / "webui.py").read_text(encoding="utf-8"))
    # The legacy startup normally clears project TEMP. Smoke testing redirects
    # that cleanup into this test's directory; user processes and files stay intact.
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "tmp" for target in node.targets):
            node.value = ast.Constant(str(ROOT / "logs" / "separation" / "legacy-smoke-TEMP"))
    # Build the complete UI but skip its blocking launcher at the end of Blocks.
    block = next(n for n in tree.body if isinstance(n, ast.With) and isinstance(n.items[0].context_expr, ast.Call)
                 and isinstance(n.items[0].context_expr.func, ast.Attribute) and n.items[0].context_expr.func.attr == "Blocks")
    block.body = [n for n in block.body if not (isinstance(n, ast.If) and isinstance(n.test, ast.Attribute) and n.test.attr == "iscolab")]
    namespace = {"__name__": "__main__", "__file__": str(ROOT / "webui.py")}
    exec(compile(ast.fix_missing_locations(tree), str(ROOT / "webui.py"), "exec"), namespace)
    app = namespace["app"]
    config = app.get_config_file()
    labels = [c.get("props", {}).get("value", "") for c in config["components"]]
    assert "打开一键分离向导" in labels and "打开一键训练向导" in labels
    app.queue(concurrency_count=4).launch(server_name="127.0.0.1", server_port=7910, inbrowser=False,
                                       share=False, prevent_thread_lock=True, quiet=True)
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:7910/config", timeout=10) as response:
            assert response.status == 200
        print("原 WebUI 初始化、分离入口、GPU 包装后的事件签名与 HTTP 启动检查通过。", flush=True)
    finally:
        app.close()


if __name__ == "__main__":
    main()
