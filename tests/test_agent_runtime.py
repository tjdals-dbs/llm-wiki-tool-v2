import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wiki_tool.agent_runtime import run_maintenance_once
from wiki_tool.config import load_domain_config


def write_domain(root: Path) -> Path:
    domain_file = root / "domain.yml"
    domain_file.write_text(
        "\n".join(
            [
                "name: Test Domain",
                "slug: test",
                "description: Test wiki.",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                "language: ko",
            ]
        ),
        encoding="utf-8",
    )
    return domain_file


class AgentRuntimeTests(unittest.TestCase):
    def test_run_maintenance_once_processes_raw_change_to_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")

            result = run_maintenance_once(domain)

            self.assertTrue(result["lint"]["ok"])
            self.assertEqual(result["scan"]["new_count"], 1)
            self.assertEqual(result["summarize"]["summarized_count"], 1)
            self.assertEqual(result["organize"]["promoted_count"], 1)
            self.assertTrue((root / "wiki" / "concepts" / "capm.md").exists())

    def test_runtime_script_once_mode_runs_without_browser_gui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain_file = write_domain(root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            repo_root = Path(__file__).resolve().parents[1]

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_agent_runtime.py",
                    "--domain",
                    str(domain_file),
                    "--once",
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("agent maintenance 완료", result.stdout)


if __name__ == "__main__":
    unittest.main()
