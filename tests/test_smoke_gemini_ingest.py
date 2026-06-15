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
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_gemini_ingest.py"
    spec = importlib.util.spec_from_file_location("smoke_gemini_ingest", script_path)
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


class SmokeGeminiIngestTests(unittest.TestCase):
    def test_cli_diagnostic_reports_gemini_success_and_failure(self):
        smoke = load_smoke_module()

        ok = smoke.collect_gemini_cli_diagnostic({}, runner=FakeCliRunner({"gemini"}))
        missing = smoke.collect_gemini_cli_diagnostic({}, runner=FakeCliRunner())

        self.assertTrue(ok.usable)
        self.assertEqual(ok.command, "gemini")
        self.assertFalse(missing.usable)
        self.assertIn("version command failed", missing.status_message)

    def test_gemini_ingest_success_creates_source_and_preserves_raw(self):
        smoke = load_smoke_module()
        draft = "\n".join(
            [
                "---",
                "title: Gemini Ingest Smoke",
                "type: source",
                "status: ok",
                "---",
                "# Gemini Ingest Smoke",
                "",
                "## Summary",
                "요구사항 분석과 보안 설정을 설명하는 테스트 원문입니다.",
                "",
                "## Key Points",
                "- 요구사항 분석은 목표와 제약을 정리합니다.",
                "- JWT와 Spring Security는 인증과 접근 제어 맥락에서 쓰입니다.",
                "",
                "## Evidence",
                "- 원문은 요구사항 분석, JWT, Spring Security를 언급합니다.",
                "",
                "## Candidate Concepts",
                "- 요구사항 분석",
                "- JWT",
                "- Spring Security",
                "",
                "## Candidate Concept Evidence",
                "- 요구사항 분석: 목표와 제약을 정리합니다.",
                "- JWT: 인증 토큰 형식으로 언급됩니다.",
                "- Spring Security: 접근 제어 프레임워크로 언급됩니다.",
                "",
                "## Quality Review",
                "- quality: ok",
            ]
        )

        with patch.dict(os.environ, {"LLM_WIKI_INGEST_PROVIDER": "gemini"}, clear=True):
            with patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent",
                return_value=AgentHookResult("ingest", "gemini", False, "ok", draft),
            ):
                result = smoke.run_ingest_smoke()

        self.assertEqual(result["resolved_ingest_provider"], "gemini")
        self.assertEqual(result["source_summary_status"], "ok")
        self.assertFalse(result["fallback"])
        self.assertTrue(result["raw_unchanged"])
        self.assertTrue(result["source_schema_ok"])
        self.assertTrue(result["source_quality_ok"])
        self.assertTrue(result["lint_ok"])
        self.assertIn("wiki/sources/", result["generated_source_page_path"])

    def test_forced_gemini_fallback_is_fail_exit_code(self):
        smoke = load_smoke_module()
        diagnostic = smoke.CliDiagnostic("gemini", "gemini", True, True, "usable")
        result = {
            "resolved_ingest_provider": "gemini",
            "fallback": True,
            "source_summary_status": "fallback",
            "raw_unchanged": True,
            "source_schema_ok": True,
            "source_quality_ok": True,
            "lint_ok": True,
            "fallback_reason": "Gemini returned invalid draft",
        }

        classification = smoke.classify_smoke_result(result, diagnostic, forced_provider="gemini")

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)
        self.assertIn("forced gemini ingest provider fell back", classification.reason)

    def test_default_main_forces_gemini_over_codex_env_and_restores_provider(self):
        smoke = load_smoke_module()
        captured_provider = []

        smoke.load_environment_for_smoke = lambda ignore_dotenv=False: {"exists": True, "loaded": True, "loaded_keys": ["LLM_WIKI_AGENT_PROVIDER"], "ignored": ignore_dotenv}
        smoke.collect_gemini_cli_diagnostic = lambda env: smoke.CliDiagnostic("gemini", "gemini", True, True, "usable")

        def fake_run_ingest_smoke():
            captured_provider.append(os.environ.get("LLM_WIKI_INGEST_PROVIDER"))
            return {
                "resolved_ingest_provider": os.environ.get("LLM_WIKI_INGEST_PROVIDER"),
                "resolved_ingest_model": os.environ.get("LLM_WIKI_INGEST_MODEL", ""),
                "source_summary_status": "ok",
                "fallback": False,
                "generated_source_page_path": "wiki/sources/gemini-ingest-smoke.md",
                "raw_unchanged": True,
                "source_schema_ok": True,
                "source_quality_ok": True,
                "lint_ok": True,
                "lint_issues_count": 0,
            }

        smoke.run_ingest_smoke = fake_run_ingest_smoke

        with patch.dict(
            os.environ,
            {
                "LLM_WIKI_AGENT_PROVIDER": "codex",
                "LLM_WIKI_INGEST_PROVIDER": "codex",
                "LLM_WIKI_INGEST_MODEL": "gemini-test",
            },
            clear=True,
        ):
            output = StringIO()
            with redirect_stdout(output):
                exit_code = smoke.main([])
            restored_provider = os.environ.get("LLM_WIKI_INGEST_PROVIDER")

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured_provider, ["gemini"])
        self.assertEqual(restored_provider, "codex")
        self.assertIn("resolved ingest provider: gemini", output.getvalue())

    def test_ignore_dotenv_skips_repo_env_and_reports_default_model(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LLM_WIKI_INGEST_PROVIDER": "gemini"}, clear=True):
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "LLM_WIKI_AGENT_PROVIDER=codex",
                        "LLM_WIKI_INGEST_MODEL=gpt-5.5",
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
        self.assertEqual(summary["resolved_ingest_provider"], "gemini")
        self.assertEqual(summary["resolved_ingest_model"], "gemini-2.5-flash")
        self.assertIn(".env loaded: no (--ignore-dotenv)", rendered)

    def test_gemini_cli_missing_fails_with_clear_message(self):
        smoke = load_smoke_module()
        diagnostic = smoke.CliDiagnostic("gemini", "gemini", False, False, "version command failed: missing")
        result = {
            "resolved_ingest_provider": "gemini",
            "fallback": True,
            "source_summary_status": "fallback",
            "raw_unchanged": True,
            "source_schema_ok": True,
            "source_quality_ok": True,
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
            "resolved_ingest_provider": "gemini",
            "resolved_ingest_model": "gemini-test",
            "source_summary_status": "ok",
            "fallback": False,
            "generated_source_page_path": "wiki/sources/gemini-ingest-smoke.md",
            "raw_unchanged": True,
            "source_schema_ok": True,
            "source_quality_ok": True,
            "lint_ok": True,
            "summarized_count": 1,
            "gemini_used_count": 1,
            "fallback_count": 0,
        }

        rendered = "\n".join(smoke.format_ingest_smoke(result))

        self.assertIn("resolved ingest provider: gemini", rendered)
        self.assertIn("resolved ingest model: gemini-test", rendered)
        self.assertIn("source summary status: ok", rendered)
        self.assertIn("fallback: false", rendered)
        self.assertIn("lint ok: true", rendered)

    def test_environment_summary_uses_gemini_default_model_without_model_env(self):
        smoke = load_smoke_module()

        summary = smoke.summarize_environment({"LLM_WIKI_INGEST_PROVIDER": "gemini"})

        self.assertEqual(summary["resolved_ingest_provider"], "gemini")
        self.assertEqual(summary["resolved_ingest_model"], "gemini-2.5-flash")

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
        smoke.run_ingest_smoke = lambda: {
            "resolved_ingest_provider": "rule_based",
            "resolved_ingest_model": "",
            "source_summary_status": "fallback",
            "fallback": True,
            "fallback_reason": "Gemini CLI command not found",
            "generated_source_page_path": "",
            "raw_unchanged": True,
            "source_schema_ok": False,
            "source_quality_ok": False,
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

    def test_provider_auto_option_is_no_longer_accepted(self):
        smoke = load_smoke_module()

        stderr = StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stdout(StringIO()), patch("sys.stderr", stderr):
            smoke.main(["--provider", "auto"])

        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
