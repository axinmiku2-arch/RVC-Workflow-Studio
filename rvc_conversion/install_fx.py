"""Install only the pinned audio effect wheel into a private dependency folder."""
import hashlib
import json
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.9.25"
HASH = "51c9c87905cd221f334cf1d9e359a583f8cf40bb913c5c1fc494c44830898fa4"


def main():
    destination = ROOT / "tools" / "audio_fx"
    with urllib.request.urlopen(f"https://pypi.org/pypi/pedalboard/{VERSION}/json", timeout=30) as response:
        metadata = json.load(response)
    wheel = next(item for item in metadata["urls"] if item["filename"] == f"pedalboard-{VERSION}-cp312-cp312-win_amd64.whl")
    if wheel["digests"]["sha256"] != HASH:
        raise ValueError("效果器安装包的公开校验值不符。")
    with urllib.request.urlopen(wheel["url"], timeout=60) as response:
        data = response.read()
    if len(data) != wheel["size"] or hashlib.sha256(data).hexdigest() != HASH:
        raise ValueError("效果器下载校验失败。")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for name in archive.namelist():
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("安装包含有越界路径。")
        archive.extractall(destination)
    (destination / "installation.json").write_text(json.dumps(dict(version=VERSION, sha256=HASH, source=wheel["url"]), indent=2), encoding="utf-8")
    print(f"已独立安装 Pedalboard {VERSION}，{len(data)} 字节；现有依赖未变更。")


if __name__ == "__main__":
    main()
