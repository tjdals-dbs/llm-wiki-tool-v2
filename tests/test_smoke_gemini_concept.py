import importlib.util
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from wiki_tool.agent_hooks import AgentHookResult


def load_smoke_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_gemini_concept.py"
    spec = importlib.util.spec_from_file_location("smoke_gemini_concept", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCliRunner:
    def __init__(self, usable_commands=()):
        self.usable_commands = set(usable_commands)
        self.calls = []

    def __call__(self, command):
        self.calls.append(tuple(command))
        ok = command[0] in self.usable_commands
        return subprocess.CompletedProcess(command, 0 if ok else 1, stdout="ok\n" if ok else "", stderr="" if ok else "missing")


class SmokeGeminiConceptTests(unittest.TestCase):
    def test_cli_diagnostic_reports_gemini_success_and_failure(self):
        smoke = load_smoke_module()

        ok = smoke.collect_gemini_cli_diagnostic({}, runner=FakeCliRunner({"gemini"}))
        missing = smoke.collect_gemini_cli_diagnostic({}, runner=FakeCliRunner())

        self.assertTrue(ok.usable)
        self.assertEqual(ok.command, "gemini")
        self.assertFalse(missing.usable)
        self.assertIn("version command failed", missing.status_message)

    def test_gemini_concept_success_creates_concept_and_preserves_raw(self):
        smoke = load_smoke_module()
        draft = "\n".join(
            [
                "# Requirements Analysis",
                "",
                "## Definition",
                "",
                "Requirements analysis organizes goals and constraints before implementation.",
                "",
                "## Explanation",
                "",
                "The draft is grounded in the generated source page.",
                "",
                "## Source Evidence",
                "",
                "- [gemini concept smoke](../sources/gemini-concept-smoke.md)",
                "- The source describes goals, constraints, and implementation scope.",
            ]
        )

        with patch.dict(os.environ, {"LLM_WIKI_CONCEPT_PROVIDER": "gemini"}, clear=True):
            with patch(
                "wiki_tool.organizer.draft_concept_update_with_agent",
                return_value=AgentHookResult("concept", "gemini", False, "ok", draft),
            ):
                result = smoke.run_concept_smoke()

        self.assertEqual(result["resolved_concept_provider"], "gemini")
        self.assertEqual(result["concept_summary_status"], "ok")
        self.assertFalse(result["fallback"])
        self.assertTrue(result["raw_unchanged"])
        self.assertTrue(result["concept_schema_ok"])
        self.assertTrue(result["concept_evidence_ok"])
        self.assertTrue(result["provider_metadata_ok"])
        self.assertTrue(result["lint_ok"])
        self.assertGreaterEqual(result["generated_concept_pages_count"], 1)
        self.assertIn("wiki/concepts/", result["generated_concept_page_path"])

    def test_forced_gemini_fallback_is_fail_exit_code(self):
        smoke = load_smoke_module()
        diagnostic = smoke.CliDiagnostic("gemini", "gemini", True, True, "usable")
        result = {
            "resolved_concept_provider": "gemini",
            "fallback": True,
            "concept_summary_status": "fallback",
            "raw_unchanged": True,
            "concept_schema_ok": True,
            "concept_evidence_ok": True,
            "provider_metadata_ok": False,
            "lint_ok": True,
            "fallback_reason": "missing_source_evidence",
        }

        classification = smoke.classify_smoke_result(result, diagnostic, forced_provider="gemini")

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)
        self.assertIn("forced gemini concept provider fell back", classification.reason)

    def test_default_main_forces_gemini_over_codex_env_and_restores_provider(self):
        smoke = load_smoke_module()
        captured = []

        smoke.load_environment_for_smoke = lambda ignore_dotenv=False: {"exists": True, "loaded": True, "loaded_keys": ["LLM_WIKI_AGENT_PROVIDER"], "ignored": ignore_dotenv}
        smoke.collect_gemini_cli_diagnostic = lambda env: smoke.CliDiagnostic("gemini", "gemini", True, True, "usable")

        def fake_run_concept_smoke():
            captured.append(
                (
                    os.environ.get("LLM_WIKI_CONCEPT_PROVIDER"),
                    os.environ.get("LLM_WIKI_INGEST_PROVIDER"),
                )
            )
            return {
                "resolved_concept_provider": os.environ.get("LLM_WIKI_CONCEPT_PROVIDER"),
                "resolved_concept_model": os.environ.get("LLM_WIKI_CONCEPT_MODEL", ""),
                "concept_summary_status": "ok",
                "fallback": False,
                "generated_concept_page_path": "wiki/concepts/requirements-analysis.md",
                "raw_unchanged": True,
                "concept_schema_ok": True,
                "concept_evidence_ok": True,
                "provider_metadata_ok": True,
                "lint_ok": True,
                "lint_issues_count": 0,
            }

        smoke.run_concept_smoke = fake_run_concept_smoke

        with patch.dict(
            os.environ,
            {
                "LLM_WIKI_AGENT_PROVIDER": "codex",
                "LLM_WIKI_CONCEPT_PROVIDER": "codex",
                "LLM_WIKI_INGEST_PROVIDER": "codex",
                "LLM_WIKI_CONCEPT_MODEL": "gemini-test",
            },
            clear=True,
        ):
            output = StringIO()
            with redirect_stdout(output):
                exit_code = smoke.main([])
            restored_concept_provider = os.environ.get("LLM_WIKI_CONCEPT_PROVIDER")
            restored_ingest_provider = os.environ.get("LLM_WIKI_INGEST_PROVIDER")

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured, [("gemini", "rule_based")])
        self.assertEqual(restored_concept_provider, "codex")
        self.assertEqual(restored_ingest_provider, "codex")
        self.assertIn("resolved concept provider: gemini", output.getvalue())

    def test_ignore_dotenv_skips_repo_env_and_reports_default_model(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LLM_WIKI_CONCEPT_PROVIDER": "gemini"}, clear=True):
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "LLM_WIKI_AGENT_PROVIDER=codex",
                        "LLM_WIKI_CONCEPT_MODEL=gpt-5.5",
                    ]
                ),
                encoding="utf-8",
            )

            env_load = smoke.load_environment_for_smoke(root, ignore_dotenv=True)
            summary = smoke.summarize_environment(os.environ, env_load)

        rendered = "\n".join(smoke.format_environment_summary(summary))

        self.assertTrue(env_load["exists"])
        self.assertFalse(env_load["loaded"])
        self.assertTrue(env_load["ignored"])
        self.assertEqual(summary["resolved_concept_provider"], "gemini")
        self.assertEqual(summary["resolved_concept_model"], "gemini-2.5-flash")
        self.assertIn(".env loaded: no (--ignore-dotenv)", rendered)

    def test_gemini_cli_missing_fails_with_clear_message(self):
        smoke = load_smoke_module()
        diagnostic = smoke.CliDiagnostic("gemini", "gemini", False, False, "version command failed: missing")
        result = {
            "resolved_concept_provider": "gemini",
            "fallback": True,
            "concept_summary_status": "fallback",
            "raw_unchanged": True,
            "concept_schema_ok": True,
            "concept_evidence_ok": True,
            "provider_metadata_ok": False,
            "lint_ok": True,
            "fallback_reason": "Gemini CLI command not found",
        }

        classification = smoke.classify_smoke_result(result, diagnostic, forced_provider="gemini")

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)
        self.assertIn("not usable", classification.reason)

    def test_format_output_contains_provider_model_fallback_and_status(self):
        smoke = load_smoke_module()
        result = {
            "resolved_concept_provider": "gemini",
            "resolved_concept_model": "gemini-test",
            "concept_summary_status": "ok",
            "fallback": False,
            "generated_concept_page_path": "wiki/concepts/requirements-analysis.md",
            "raw_unchanged": True,
            "concept_schema_ok": True,
            "concept_evidence_ok": True,
            "provider_metadata_ok": True,
            "lint_ok": True,
            "promoted_count": 1,
            "gemini_used_count": 1,
            "fallback_count": 0,
        }

        rendered = "\n".join(smoke.format_concept_smoke(result))

        self.assertIn("resolved concept provider: gemini", rendered)
        self.assertIn("resolved concept model: gemini-test", rendered)
        self.assertIn("concept summary status: ok", rendered)
        self.assertIn("fallback: false", rendered)
        self.assertIn("lint ok: true", rendered)

    def test_environment_summary_uses_gemini_default_model_without_model_env(self):
        smoke = load_smoke_module()

        summary = smoke.summarize_environment({"LLM_WIKI_CONCEPT_PROVIDER": "gemini"})

        self.assertEqual(summary["resolved_concept_provider"], "gemini")
        self.assertEqual(summary["resolved_concept_model"], "gemini-2.5-flash")

    def test_invalid_gemini_concept_draft_fails_smoke(self):
        smoke = load_smoke_module()
        diagnostic = smoke.CliDiagnostic("gemini", "gemini", True, True, "usable")
        result = {
            "resolved_concept_provider": "gemini",
            "fallback": False,
            "concept_summary_status": "failed",
            "raw_unchanged": True,
            "concept_schema_ok": False,
            "concept_evidence_ok": False,
            "provider_metadata_ok": False,
            "lint_ok": True,
            "fallback_reason": "missing_source_evidence",
        }

        classification = smoke.classify_smoke_result(result, diagnostic, forced_provider="gemini")

        self.assertEqual(classification.label, "FAIL")
        self.assertNotEqual(classification.exit_code, 0)

    def test_main_reports_forced_gemini_failure_without_traceback(self):
        smoke = load_smoke_module()

        smoke.load_environment_for_smoke = lambda ignore_dotenv=False: {"exists": False, "loaded": False, "loaded_keys": [], "ignored": ignore_dotenv}
        smoke.collect_gemini_cli_diagnostic = lambda env: smoke.CliDiagnostic(
            "gemini",
            "gemini",
            False,
            False,
            "version command failed: missing",
        )
        smoke.run_concept_smoke = lambda: {
            "resolved_concept_provider": "rule_based",
            "resolved_concept_model": "",
            "concept_summary_status": "fallback",
            "fallback": True,
            "fallback_reason": "Gemini CLI command not found",
            "generated_concept_page_path": "",
            "raw_unchanged": True,
            "concept_schema_ok": False,
            "concept_evidence_ok": False,
            "provider_metadata_ok": False,
            "lint_ok": False,
            "lint_issues_count": 0,
        }

        with patch.dict(os.environ, {}, clear=True):
            output = StringIO()
            with redirect_stdout(output):
                exit_code = smoke.main([])

        self.assertEqual(exit_code, 1)
        text = output.getvalue()
        self.assertIn("SMOKE RESULT: FAIL", text)
        self.assertIn("Gemini CLI command not found", text)
        self.assertNotIn("Traceback", text)


if __name__ == "__main__":
    unittest.main()
