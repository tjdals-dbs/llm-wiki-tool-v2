from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class SetupWrapperTests(unittest.TestCase):
    def test_windows_run_wrapper_requires_venv_python(self):
        content = _read("run_app.bat")

        self.assertIn(".venv\\Scripts\\python.exe", content)
        self.assertIn("Run setup.bat first", content)
        self.assertIn('".venv\\Scripts\\python.exe" scripts\\run_app.py %*', content)

    def test_unix_run_wrapper_requires_venv_python(self):
        content = _read("run_app.sh")

        self.assertIn(".venv/bin/python", content)
        self.assertIn("Run ./setup.sh first", content)
        self.assertIn('".venv/bin/python" scripts/run_app.py "$@"', content)

    def test_windows_setup_creates_venv_and_installs_requirements(self):
        content = _read("setup.bat")

        self.assertIn("python -m venv .venv", content)
        self.assertIn('".venv\\Scripts\\python.exe" -m pip install --upgrade pip', content)
        self.assertIn('".venv\\Scripts\\python.exe" -m pip install -r requirements.txt', content)
        self.assertIn("where python", content)

    def test_unix_setup_creates_venv_and_installs_requirements(self):
        content = _read("setup.sh")

        self.assertIn("python3 -m venv .venv", content)
        self.assertIn('".venv/bin/python" -m pip install --upgrade pip', content)
        self.assertIn('".venv/bin/python" -m pip install -r requirements.txt', content)
        self.assertIn("command -v python3", content)


if __name__ == "__main__":
    unittest.main()
