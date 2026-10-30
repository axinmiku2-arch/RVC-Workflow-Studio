"""Reuse the current WebUI instead of launching an obsolete duplicate."""
import argparse
import json
import urllib.request
import webbrowser


def is_current_webui(config):
    if not isinstance(config, dict) or config.get("title") != "RVC WebUI":
        return False
    apis = {item.get("api_name") for item in config.get("dependencies", [])}
    return {"infer_convert", "music_import_audio", "music_import_decoded"} <= apis


def reuse(port=7897, open_browser=True):
    url = f"http://127.0.0.1:{port}/"
    try:
        # Never send local requests through a system proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "config", timeout=2) as response:
            config = json.load(response)
        if not is_current_webui(config):
            return False
    except (OSError, ValueError):
        return False
    if open_browser:
        webbrowser.open(url + "?__theme=light")
    print(f"WebUI is already running. Reusing {url}", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7897)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    raise SystemExit(0 if reuse(args.port, not args.no_browser) else 1)


if __name__ == "__main__":
    main()
