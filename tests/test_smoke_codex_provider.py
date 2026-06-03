import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO


def load_smoke_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_codex_provider.py"
    spec = importlib.util.spec_from_file_location("smoke_codex_provider", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeCodexProviderTests(unittest.TestCase):
    def test_environment_summary_does_not_expose_full_sensitive_values(self):
        smoke = load_smoke_module()
        env = {
            "LLM_WIKI_AGENT_PROVIDER": "codex",
            "LLM_WIKI_AGENT_MODEL": "gpt-5.5",
            "LLM_WIKI_ANSWER_MODEL": "secret-answer-model-with-long-private-suffix",
            "LLM_WIKI_CODEX_COMMAND": r"C:\Tools\codex.cmd --profile private-user",
        }

        summary = smoke.summarize_environment(env)
        rendered = "\n".join(smoke.format_environment_summary(summary))

        self.assertIn("LLM_WIKI_AGENT_PROVIDER: set", rendered)
        self.assertIn("resolved answer model: secret-answer-model-with-long-private-suffix", rendered)
        self.assertIn("LLM_WIKI_CODEX_COMMAND: set", rendered)
        self.assertNotIn(r"C:\Tools\codex.cmd --profile private-user", rendered)

    def test_smoke_runner_loads_dotenv_before_environment_summary(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "LLM_WIKI_AGENT_PROVIDER=codex",
                        "LLM_WIKI_ANSWER_MODEL=gpt-5.5",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = smoke.load_environment_for_smoke(root)
            summary = smoke.summarize_environment(os.environ)

        self.assertEqual(loaded["LLM_WIKI_AGENT_PROVIDER"], "codex")
        self.assertEqual(summary["provider"], "codex")
        self.assertEqual(summary["resolved_models"]["answer"], "gpt-5.5")

    def test_codex_cli_version_check_success_and_failure_are_structured(self):
        smoke = load_smoke_module()

        def ok_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="codex-cli 0.131.0\n", stderr="")

        ok = smoke.check_codex_cli("codex.cmd", runner=ok_runner)

        self.assertTrue(ok.ok)
        self.assertEqual(ok.status, "ok")
        self.assertEqual(ok.version, "codex-cli 0.131.0")

        def missing_runner(command, **kwargs):
            raise FileNotFoundError("missing")

        missing = smoke.check_codex_cli("missing-codex", runner=missing_runner)

        self.assertFalse(missing.ok)
        self.assertEqual(missing.status, "missing")
        self.assertIn("not found", missing.reason)

    def test_answer_smoke_result_contains_provider_fallback_status_and_counts(self):
        smoke = load_smoke_module()

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def answer_question(self, question):
                return {
                    "provider": "codex",
                    "fallback": False,
                    "status": "ok",
                    "answer": "CAPM answer",
                    "used_pages": [{"path": "wiki/concepts/capm.md"}],
                    "evidence": [{"text": "evidence 1"}, {"text": "evidence 2"}],
                }

        with tempfile.TemporaryDirectory() as tmp:
            domain_path = self._write_domain(Path(tmp))

            result = smoke.run_answer_smoke(domain_path, "CAPM은 무엇인가?", adapter_cls=FakeAdapter)

        self.assertEqual(result["provider"], "codex")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["used_pages_count"], 1)
        self.assertEqual(result["evidence_count"], 2)

    def test_answer_smoke_does_not_modify_source_domain_wiki_files(self):
        smoke = load_smoke_module()

        class WritingAdapter:
            def __init__(self, config):
                self.config = config

            def answer_question(self, question):
                graph_file = self.config.wiki_dir / "graph" / "graph.json"
                graph_file.parent.mkdir(parents=True, exist_ok=True)
                graph_file.write_text('{"changed": true}', encoding="utf-8")
                return {
                    "provider": "codex",
                    "fallback": False,
                    "status": "ok",
                    "answer": "CAPM answer",
                    "used_pages": [{"path": "wiki/concepts/capm.md"}],
                    "evidence": [{"text": "evidence"}],
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain_path = self._write_domain(root)
            wiki_file = root / "wiki" / "graph" / "graph.json"
            wiki_file.parent.mkdir(parents=True)
            wiki_file.write_text('{"original": true}', encoding="utf-8")

            smoke.run_answer_smoke(domain_path, "CAPM은 무엇인가?", adapter_cls=WritingAdapter)

            self.assertEqual(wiki_file.read_text(encoding="utf-8"), '{"original": true}')

    def test_main_runs_pipeline_only_when_include_pipeline_is_set(self):
        smoke = load_smoke_module()
        calls = []

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            domain_path = self._write_domain(Path(tmp))
            smoke.load_environment_for_smoke = lambda: {}
            smoke.summarize_environment = lambda env: {
                "variables": {},
                "provider": "codex",
                "resolved_models": {"answer": "gpt-5.5", "ingest": "gpt-5.5", "concept": "gpt-5.5", "review": "gpt-5.5"},
                "codex_command": "codex.cmd",
                "codex_command_display": "codex.cmd",
            }
            smoke.check_codex_cli = lambda command: smoke.CodexCliCheck(True, "ok", "codex-cli", "")
            smoke.run_answer_smoke = lambda domain, question: {
                "provider": "codex",
                "fallback": False,
                "status": "ok",
                "answer_preview": "answer",
                "used_pages_count": 1,
                "evidence_count": 2,
            }
            smoke.run_pipeline_smoke = lambda: calls.append("pipeline") or {
                "source_provider": "codex",
                "source_codex_used_count": 1,
                "source_fallback_count": 0,
                "concept_provider": "codex",
                "concept_codex_used_count": 1,
                "concept_fallback_count": 0,
                "lint_ok": True,
                "raw_unchanged": True,
            }

            with redirect_stdout(StringIO()):
                no_pipeline_code = smoke.main(["--domain", str(domain_path), "--question", "CAPM"])
            with redirect_stdout(StringIO()):
                include_pipeline_code = smoke.main(["--domain", str(domain_path), "--question", "CAPM", "--include-pipeline"])

        self.assertEqual(no_pipeline_code, 0)
        self.assertEqual(include_pipeline_code, 0)
        self.assertEqual(calls, ["pipeline"])

    def test_pipeline_temp_domain_contains_public_safe_raw_text(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            domain_path, raw_path = smoke.create_pipeline_smoke_domain(Path(tmp))

            raw_text = raw_path.read_text(encoding="utf-8")

        self.assertTrue(domain_path.name == "domain.yml")
        self.assertEqual(raw_path.relative_to(domain_path.parent).as_posix(), "raw/capm-note.md")
        self.assertIn("CAPM은 자산의 기대수익률", raw_text)
        self.assertNotIn("private", raw_text.casefold())

    def test_pipeline_smoke_result_contains_provider_counts_and_raw_hash(self):
        smoke = load_smoke_module()

        class FakePipelineAdapter:
            def __init__(self, config):
                self.config = config

            def scan_raw_sources(self):
                return {"new_count": 1}

            def summarize_new_sources(self):
                path = self.config.wiki_dir / "sources" / "capm-note.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# CAPM Note\n", encoding="utf-8")
                return {
                    "provider": "codex",
                    "codex_used_count": 1,
                    "fallback_count": 0,
                    "summarized_count": 1,
                    "needs_review_count": 0,
                }

            def organize_pending_sources(self):
                path = self.config.wiki_dir / "concepts" / "capm.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# CAPM\n", encoding="utf-8")
                return {
                    "provider": "codex",
                    "codex_used_count": 1,
                    "fallback_count": 0,
                    "promoted_count": 1,
                    "merged_count": 0,
                }

            def run_wiki_lint(self):
                return {
                    "ok": True,
                    "issues": [
                        {
                            "path": "wiki/concepts/capm.md",
                            "message": "ignored because lint is ok in this fixture",
                        }
                    ],
                }

        result = smoke.run_pipeline_smoke(adapter_cls=FakePipelineAdapter)

        self.assertEqual(result["scan_new_count"], 1)
        self.assertEqual(result["source_provider"], "codex")
        self.assertEqual(result["source_codex_used_count"], 1)
        self.assertEqual(result["concept_provider"], "codex")
        self.assertEqual(result["concept_codex_used_count"], 1)
        self.assertEqual(result["generated_source_pages_count"], 1)
        self.assertEqual(result["generated_concept_pages_count"], 1)
        self.assertEqual(result["lint_issues_count"], 1)
        self.assertEqual(
            result["lint_issues"],
            ["wiki/concepts/capm.md: ignored because lint is ok in this fixture"],
        )
        self.assertTrue(result["raw_unchanged"])

    def test_pipeline_fallback_with_lint_ok_uses_zero_exit_code(self):
        smoke = load_smoke_module()
        cli = smoke.CodexCliCheck(ok=True, status="ok", version="codex-cli", reason="")
        answer = {"provider": "codex", "fallback": False, "status": "ok", "evidence_count": 1}
        pipeline = {
            "source_provider": "codex",
            "source_codex_used_count": 0,
            "source_fallback_count": 1,
            "concept_provider": "codex",
            "concept_codex_used_count": 0,
            "concept_fallback_count": 1,
            "lint_ok": True,
            "raw_unchanged": True,
        }

        classification = smoke.classify_result(cli, answer, pipeline)

        self.assertEqual(classification.label, "FALLBACK")
        self.assertEqual(classification.exit_code, 0)

    def test_pipeline_lint_failure_uses_fail_exit_code(self):
        smoke = load_smoke_module()
        cli = smoke.CodexCliCheck(ok=True, status="ok", version="codex-cli", reason="")
        answer = {"provider": "codex", "fallback": False, "status": "ok", "evidence_count": 1}
        pipeline = {"lint_ok": False, "raw_unchanged": True}

        classification = smoke.classify_result(cli, answer, pipeline)

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)

    def test_fallback_result_uses_zero_exit_code(self):
        smoke = load_smoke_module()
        cli = smoke.CodexCliCheck(ok=True, status="ok", version="codex-cli", reason="")
        answer = {
            "provider": "rule_based",
            "fallback": True,
            "status": "ok",
            "codex_status": "codex_invalid_answer",
            "fallback_reason": "missing_evidence",
            "evidence_count": 1,
        }

        classification = smoke.classify_result(cli, answer)

        self.assertEqual(classification.label, "FALLBACK")
        self.assertEqual(classification.exit_code, 0)

    def test_missing_codex_cli_uses_fail_exit_code(self):
        smoke = load_smoke_module()
        cli = smoke.CodexCliCheck(ok=False, status="missing", version="", reason="Codex CLI command not found")
        answer = {}

        classification = smoke.classify_result(cli, answer)

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)

    def _write_domain(self, root: Path) -> Path:
        domain = root / "domain.yml"
        domain.write_text(
            "\n".join(
                [
                    "name: Smoke Test",
                    "slug: smoke-test",
                    "description: Smoke test wiki.",
                    "raw_dir: raw",
                    "wiki_dir: wiki",
                    "manifest: manifests/raw_sources.csv",
                    "language: ko",
                ]
            ),
            encoding="utf-8",
        )
        return domain


if __name__ == "__main__":
    unittest.main()
