"""HTTP regression for the portable Gradio server used by the wizard."""
import os
import socket
import unittest
import urllib.request

import gradio as gr
from training_wizard import install_help_route


class HelpRouteTests(unittest.TestCase):
    def test_help_is_on_the_launched_server(self):
        os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with gr.Blocks(analytics_enabled=False) as app:
            gr.Markdown("测试中文说明入口")
        try:
            app.launch(server_name="127.0.0.1", server_port=port,
                       share=False, quiet=True, prevent_thread_lock=True)
            install_help_route(app)
            request = urllib.request.Request(f"http://127.0.0.1:{port}/wizard/help")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
                text = response.read().decode("utf-8")
            self.assertIn("200", text)
            self.assertIn("RMVPE", text)
            self.assertIn("使用说明", text)
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
