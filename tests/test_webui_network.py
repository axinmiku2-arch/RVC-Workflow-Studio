"""Exercise the real WebUI launch function without starting a server."""
import ast
import logging
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def launch_function():
    path = Path(__file__).resolve().parents[1] / "webui.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                and item.name == "launch_webui_with_port_fallback")
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    scope = {"os": os, "logger": logging.getLogger(__name__)}
    exec(compile(module, str(path), "exec"), scope)
    return scope


class WebUINetworkTests(unittest.TestCase):
    def test_loopback_default_and_explicit_lan_opt_in(self):
        for configured, expected in ((None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")):
            with self.subTest(configured=configured), patch.dict(os.environ, {}, clear=True):
                if configured:
                    os.environ["RVC_WEBUI_HOST"] = configured
                scope = launch_function()
                observed = {}
                def choose(port, host):
                    observed["probe_host"] = host
                    return port
                scope["find_available_port"] = choose
                class App:
                    def queue(self, **kwargs):
                        return self
                    def launch(self, **kwargs):
                        observed["launch_host"] = kwargs["server_name"]
                config = SimpleNamespace(listen_port=7897, noautoopen=True)
                self.assertEqual(scope["launch_webui_with_port_fallback"](App(), config), 7897)
                self.assertEqual(observed, {"probe_host": expected, "launch_host": expected})


if __name__ == "__main__":
    unittest.main()
