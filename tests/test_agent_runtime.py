import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_tool.agent_hooks import AgentHookResult
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
            self.assertEqual(result["review"]["status"], "skipped")
            self.assertTrue((root / "wiki" / "concepts" / "capm.md").exists())

    def test_run_maintenance_once_reviews_codex_pipeline_without_failing_on_review_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            source_draft = "\n".join(
                [
                    "# CAPM Source",
                    "",
                    "## Summary",
                    "",
                    "Codex source summary입니다.",
                    "",
                    "## Key Points",
                    "",
                    "- CAPM은 위험과 수익을 연결한다.",
                    "",
                    "## Evidence",
                    "",
                    "- CAPM은 기대수익률과 위험을 연결한다.",
                    "",
                    "## Candidate Concepts",
                    "",
                    "- CAPM",
                    "",
                    "## Quality Review",
                    "",
                    "- quality: usable",
                ]
            )
            concept_draft = "\n".join(
                [
                    "# CAPM",
                    "",
                    "## Definition",
                    "",
                    "Codex concept draft입니다.",
                    "",
                    "## Source Evidence",
                    "",
                    "- [capm](../sources/capm.md)",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as ingest_hook, patch("wiki_tool.organizer.draft_concept_update_with_agent") as concept_hook, patch(
                "wiki_tool.agent_runtime.review_wiki_changes_with_agent"
            ) as review_hook:
                ingest_hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=source_draft,
                )
                concept_hook.return_value = AgentHookResult(
                    role="concept",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=concept_draft,
                )
                review_hook.return_value = AgentHookResult(
                    role="review",
                    provider="rule_based",
                    fallback=True,
                    status="codex_error",
                    draft="",
                    error="review failed",
                )
                result = run_maintenance_once(domain)

            log = (root / "wiki" / "log.md").read_text(encoding="utf-8")
            self.assertTrue(result["lint"]["ok"])
            self.assertEqual(result["summarize"]["codex_used_count"], 1)
            self.assertEqual(result["organize"]["codex_used_count"], 1)
            self.assertEqual(result["review"]["status"], "codex_error")
            self.assertIn("agent review: provider=rule_based, status=codex_error", log)
            self.assertIn("warning=review failed", log)

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
