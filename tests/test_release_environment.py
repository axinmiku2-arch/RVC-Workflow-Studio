"""Verify isolated subprocess imports from an installed source checkout."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReleaseEnvironmentTests(unittest.TestCase):
    def run_checked(self, args, **kwargs):
        result = subprocess.run(args, capture_output=True, **kwargs)
        if result.returncode:
            stdout = result.stdout.decode("utf-8", errors="backslashreplace")
            stderr = result.stderr.decode("utf-8", errors="backslashreplace")
            self.fail(f"{result.args!r} exited with status {result.returncode}\n"
                      f"stdout:\n{stdout}\nstderr:\n{stderr}")
        return result

    def test_isolated_python_imports_checkout_with_unicode_path(self):
        source = Path(__file__).resolve().parents[1] / "tools" / "configure_venv.py"
        with tempfile.TemporaryDirectory(prefix="rvc_environment_") as temp:
            root = Path(temp) / "项目 folder"
            (root / "tools").mkdir(parents=True)
            shutil.copyfile(source, root / "tools" / "configure_venv.py")
            (root / "probe_package").mkdir()
            (root / "probe_package" / "__init__.py").write_text("value = 7\n", encoding="ascii")
            venv = root / ".venv"
            self.run_checked([sys.executable, "-m", "venv", str(venv)])
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            script = str(root / "tools" / "configure_venv.py")
            self.run_checked([str(python), "-I", script], cwd=temp)
            # Simulate a redirected Windows stream even if CI normally uses UTF-8.
            # -I ignores PYTHONIOENCODING, so set the stream encoding in the child.
            restricted_output = (
                "import runpy, sys; "
                "sys.stdout.reconfigure(encoding='cp1252', errors='strict'); "
                "runpy.run_path(sys.argv[1], run_name='__main__')"
            )
            self.run_checked([str(python), "-I", "-c", restricted_output, script], cwd=temp)
            result = self.run_checked([str(python), "-I", "-c", "import probe_package; print(probe_package.value)"],
                                      cwd=temp)
            self.assertEqual(result.stdout.strip(), b"7")

    @unittest.skipUnless(os.name == "nt", "Windows setup script")
    def test_windows_setup_offline_and_launcher_selects_venv(self):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rvc_setup_") as temp:
            root = Path(temp) / "项目 folder"
            (root / "tools").mkdir(parents=True)
            for relative in ("tools/configure_venv.py", "tools/select-python.bat", "setup-windows.ps1"):
                shutil.copyfile(checkout / relative, root / relative)
            self.run_checked(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              str(root / "setup-windows.ps1"), "-Python", sys.executable, "-SkipDependencies"], cwd=temp)
            env = dict(os.environ, SCRIPT_DIR=str(root))
            check = root / "check-launcher.bat"
            check.write_text('@echo off\ncall "%SCRIPT_DIR%\\tools\\select-python.bat"\n'
                             'if errorlevel 1 exit /b 1\n'
                             'if /I not "%RVC_PYTHON%"=="%SCRIPT_DIR%\\.venv\\Scripts\\python.exe" exit /b 2\n'
                             '"%RVC_PYTHON%" -I -c "print(12345)"\n', encoding="ascii")
            result = self.run_checked(["cmd.exe", "/d", "/c", str(check)], env=env, cwd=temp)
            self.assertEqual(result.stdout.strip(), b"12345")


if __name__ == "__main__":
    unittest.main()
