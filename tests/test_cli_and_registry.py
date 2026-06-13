import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_tool.config import load_domain_config
from wiki_tool.mcp_registry import MCP_TOOL_NAMES, create_tool_registry


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


AGENT_MODEL_ENV_NAMES = [
    "LLM_WIKI_AGENT_MODEL",
    "LLM_WIKI_ANSWER_MODEL",
    "LLM_WIKI_INGEST_MODEL",
    "LLM_WIKI_CONCEPT_MODEL",
    "LLM_WIKI_REVIEW_MODEL",
]


def _cli_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LLM_WIKI_AGENT_PROVIDER"] = "rule_based"
    for name in AGENT_MODEL_ENV_NAMES:
        env[name] = ""
    env["LLM_WIKI_CODEX_COMMAND"] = ""
    return env


class CliAndRegistryTests(unittest.TestCase):
    def test_cli_subprocess_env_forces_rule_based_provider(self):
        with patch.dict(
            os.environ,
            {
                "LLM_WIKI_AGENT_PROVIDER": "codex",
                "LLM_WIKI_AGENT_MODEL": "gpt-5.5",
                "LLM_WIKI_ANSWER_MODEL": "gpt-5.5",
                "LLM_WIKI_INGEST_MODEL": "gpt-5.5",
                "LLM_WIKI_CONCEPT_MODEL": "gpt-5.5",
                "LLM_WIKI_REVIEW_MODEL": "gpt-5.5",
                "LLM_WIKI_CODEX_COMMAND": "codex.cmd",
            },
            clear=True,
        ):
            env = _cli_subprocess_env()

        self.assertEqual(env["LLM_WIKI_AGENT_PROVIDER"], "rule_based")
        for name in AGENT_MODEL_ENV_NAMES:
            self.assertEqual(env[name], "")
        self.assertEqual(env["LLM_WIKI_CODEX_COMMAND"], "")

    def test_tool_registry_exposes_required_mcp_tool_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_domain_config(write_domain(root), root=root)
            registry = create_tool_registry(config)

            self.assertEqual(set(registry), set(MCP_TOOL_NAMES))
            self.assertIn("scan_raw_sources", registry)
            self.assertIn("summarize_new_sources", registry)
            self.assertIn("organize_pending_sources", registry)
            self.assertIn("analyze_answer_candidates", registry)
            self.assertIn("draft_source_summary_with_agent", registry)
            self.assertIn("draft_concept_update_with_agent", registry)
            self.assertIn("review_wiki_changes_with_agent", registry)
            self.assertIn("run_wiki_lint", registry)

    def test_cli_runs_raw_to_concept_pipeline_from_domain_file(self):
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
                    "scripts/wiki_tool.py",
                    "--domain",
                    str(domain_file),
                    "pipeline",
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
                env=_cli_subprocess_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("raw source scan 완료", result.stdout)
            self.assertIn("source summary 생성 완료", result.stdout)
            self.assertIn("concept organization 완료", result.stdout)
            self.assertTrue((root / "wiki" / "concepts" / "capm.md").exists())


if __name__ == "__main__":
    unittest.main()
