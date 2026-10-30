"""Register this checkout with its virtual environment for isolated workers."""
import sys
import sysconfig
from pathlib import Path


def main():
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Run this script using the project's virtual environment.")
    root = Path(__file__).resolve().parents[1]
    packages = Path(sysconfig.get_path("purelib")).resolve()
    if not packages.is_dir() or not packages.is_relative_to(Path(sys.prefix).resolve()):
        raise SystemExit("Cannot identify the virtual environment site-packages directory.")
    target = packages / "rvc_workflow_studio.pth"
    # Python 3.12 may decode .pth files using the Windows locale. An ASCII
    # representation keeps project paths containing other languages intact.
    target.write_text("import sys; sys.path.insert(0, " + ascii(str(root)) + ")\n", encoding="ascii")
    print(f"Registered project directory in {target}")


if __name__ == "__main__":
    main()
