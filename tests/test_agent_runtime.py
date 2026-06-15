import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_tool.agent_hooks import AgentHookResult
from wiki_tool.agent_runtime import run_maintenance_once
from wiki_tool.config import load_domain_config
from wiki_tool.mcp_tools import WikiToolAdapter


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


def _runtime_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LLM_WIKI_AGENT_PROVIDER"] = "rule_based"
    for name in AGENT_MODEL_ENV_NAMES:
        env[name] = ""
    env["LLM_WIKI_CODEX_COMMAND"] = ""
    return env


class AgentRuntimeTests(unittest.TestCase):
    def test_runtime_subprocess_env_forces_rule_based_provider(self):
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
            env = _runtime_subprocess_env()

        self.assertEqual(env["LLM_WIKI_AGENT_PROVIDER"], "rule_based")
        for name in AGENT_MODEL_ENV_NAMES:
            self.assertEqual(env[name], "")
        self.assertEqual(env["LLM_WIKI_CODEX_COMMAND"], "")

    def test_run_maintenance_once_processes_raw_change_to_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")

            with patch.dict(os.environ, _runtime_subprocess_env()):
                result = run_maintenance_once(domain)

            self.assertTrue(result["lint"]["ok"])
            self.assertEqual(result["scan"]["new_count"], 1)
            self.assertEqual(result["summarize"]["summarized_count"], 1)
            self.assertEqual(result["organize"]["promoted_count"], 1)
            self.assertEqual(result["answers"]["candidate_count"], 0)
            self.assertEqual(result["answers"]["skipped_count"], 0)
            self.assertEqual(result["answer_concept_drafts"]["draft_count"], 0)
            self.assertEqual(result["answer_concept_drafts"]["skipped_count"], 0)
            self.assertEqual(result["answer_concept_updates"]["applied_count"], 0)
            self.assertEqual(result["answer_concept_updates"]["skipped_count"], 0)
            self.assertEqual(result["review"]["status"], "skipped")
            self.assertTrue((root / "wiki" / "concepts" / "capm.md").exists())

    def test_run_maintenance_once_reviews_with_gemini_when_review_provider_is_gemini(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")

            env = _runtime_subprocess_env()
            env["LLM_WIKI_REVIEW_PROVIDER"] = "gemini"
            with patch.dict(os.environ, env), patch("wiki_tool.agent_runtime.review_wiki_changes_with_agent") as review_hook:
                review_hook.return_value = AgentHookResult(
                    role="review",
                    provider="gemini",
                    fallback=False,
                    status="ok",
                    draft="- Gemini review ok",
                    error="",
                )

                result = run_maintenance_once(domain)

        review_hook.assert_called_once()
        changes_summary = review_hook.call_args.args[0]
        self.assertIn("source summarized", changes_summary)
        self.assertEqual(result["review"]["provider"], "gemini")
        self.assertEqual(result["review"]["status"], "ok")

    def test_run_maintenance_once_applies_answer_concept_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            concept = root / "wiki" / "concepts" / "jwt.md"
            source = root / "wiki" / "sources" / "jwt.md"
            concept.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            concept.write_text("# JWT\n\n## Definition\n\nHuman-authored definition.\n", encoding="utf-8")
            source.write_text("# JWT Source\n", encoding="utf-8")
            adapter = WikiToolAdapter(domain)
            adapter.apply_wiki_update(
                question="What is JWT?",
                answer="JWT is a compact token format.",
                used_pages=[{"path": "wiki/concepts/jwt.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/sources/jwt.md", "text": "JWT source evidence"}],
                status="ok",
                suggested_title="JWT",
            )

            with patch.dict(os.environ, _runtime_subprocess_env()):
                result = run_maintenance_once(domain)

            self.assertEqual(result["answer_concept_updates"]["applied_count"], 1)
            self.assertIn("## Answer-Derived Notes", concept.read_text(encoding="utf-8"))

    def test_run_maintenance_once_reuses_answer_concept_draft_result(self):
        class FakeRuntimeAdapter:
            instances = []

            def __init__(self, _config):
                self.calls = []
                self.draft_result = {"draft_count": 1, "skipped_count": 0, "drafts": [], "skipped": []}
                self.applied_draft_result = None
                FakeRuntimeAdapter.instances.append(self)

            def scan_raw_sources(self):
                self.calls.append("scan")
                return {"new_count": 0}

            def summarize_new_sources(self):
                self.calls.append("summarize")
                return {"codex_used_count": 0, "fallback_count": 0}

            def organize_pending_sources(self):
                self.calls.append("organize")
                return {"codex_used_count": 0, "fallback_count": 0}

            def analyze_answer_candidates(self):
                self.calls.append("answers")
                return {"candidate_count": 1, "skipped_count": 0}

            def draft_answer_concept_updates(self):
                self.calls.append("answer_drafts")
                return self.draft_result

            def apply_answer_concept_updates(self, draft_result=None):
                self.calls.append("answer_updates")
                self.applied_draft_result = draft_result
                return {"applied_count": 0, "skipped_count": 0}

            def run_wiki_lint(self):
                self.calls.append("lint")
                return {"ok": True, "issues": []}

        with tempfile.TemporaryDirectory() as tmp, patch(
            "wiki_tool.agent_runtime.WikiToolAdapter",
            FakeRuntimeAdapter,
        ):
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)

            result = run_maintenance_once(domain)

        adapter = FakeRuntimeAdapter.instances[0]
        self.assertEqual(adapter.calls, ["scan", "summarize", "organize", "answers", "answer_drafts", "answer_updates", "lint"])
        self.assertIs(adapter.applied_draft_result, adapter.draft_result)
        self.assertIs(result["answer_concept_drafts"], adapter.draft_result)

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
                env=_runtime_subprocess_env(),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("agent maintenance 완료", result.stdout)


if __name__ == "__main__":
    unittest.main()
