"""Verify isolated subprocess imports from an installed source checkout."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReleaseEnvironmentTests(unittest.TestCase):
    def test_isolated_python_imports_checkout_with_unicode_path(self):
        source = Path(__file__).resolve().parents[1] / "tools" / "configure_venv.py"
        with tempfile.TemporaryDirectory(prefix="rvc_environment_") as temp:
            root = Path(temp) / "项目 folder"
            (root / "tools").mkdir(parents=True)
            shutil.copyfile(source, root / "tools" / "configure_venv.py")
            (root / "probe_package").mkdir()
            (root / "probe_package" / "__init__.py").write_text("value = 7\n", encoding="ascii")
            venv = root / ".venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([str(python), "-I", str(root / "tools" / "configure_venv.py")],
                           cwd=temp, check=True, capture_output=True)
            result = subprocess.run([str(python), "-I", "-c", "import probe_package; print(probe_package.value)"],
                                    cwd=temp, check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), "7")

    @unittest.skipUnless(os.name == "nt", "Windows setup script")
    def test_windows_setup_offline_and_launcher_selects_venv(self):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rvc_setup_") as temp:
            root = Path(temp) / "项目 folder"
            (root / "tools").mkdir(parents=True)
            for relative in ("tools/configure_venv.py", "tools/select-python.bat", "setup-windows.ps1"):
                shutil.copyfile(checkout / relative, root / relative)
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(root / "setup-windows.ps1"), "-Python", sys.executable, "-SkipDependencies"],
                           cwd=temp, check=True, capture_output=True)
            env = dict(os.environ, SCRIPT_DIR=str(root))
            check = root / "check-launcher.bat"
            check.write_text('@echo off\ncall "%SCRIPT_DIR%\\tools\\select-python.bat"\n'
                             'if errorlevel 1 exit /b 1\n'
                             'if /I not "%RVC_PYTHON%"=="%SCRIPT_DIR%\\.venv\\Scripts\\python.exe" exit /b 2\n'
                             '"%RVC_PYTHON%" -I -c "print(12345)"\n', encoding="ascii")
            result = subprocess.run(["cmd.exe", "/d", "/c", str(check)], env=env,
                                    cwd=temp, check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), "12345")


if __name__ == "__main__":
    unittest.main()
