import subprocess
import sys
import unittest
from pathlib import Path


class LintCliTests(unittest.TestCase):
    def test_lint_script_runs_from_repository_root(self):
        root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [
                sys.executable,
                "scripts/lint_wiki.py",
                "--domain",
                "examples/finance/domain.yml",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("위키 lint 통과", result.stdout)


if __name__ == "__main__":
    unittest.main()
