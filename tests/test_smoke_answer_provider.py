import importlib.util
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


def load_smoke_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_answer_provider.py"
    spec = importlib.util.spec_from_file_location("smoke_answer_provider", script_path)
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


class SmokeAnswerProviderTests(unittest.TestCase):
    def test_cli_diagnostics_report_codex_and_gemini_success_and_failure(self):
        smoke = load_smoke_module()

        diagnostics = smoke.collect_cli_diagnostics({}, runner=FakeCliRunner({"gemini"}))

        codex = diagnostics["codex"]
        gemini = diagnostics["gemini"]
        self.assertFalse(codex.usable)
        self.assertIn("version command failed", codex.status_message)
        self.assertTrue(gemini.usable)
        self.assertEqual(gemini.command, "gemini")

    def test_run_answer_smoke_can_force_gemini_provider_env(self):
        smoke = load_smoke_module()

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def answer_question(self, question):
                return {
                    "provider": os.environ.get("LLM_WIKI_ANSWER_PROVIDER"),
                    "fallback": False,
                    "status": "ok",
                    "answer": "Gemini answer",
                    "used_pages": [{"path": "wiki/sources/capm.md"}],
                    "evidence": [{"path": "wiki/sources/capm.md", "text": "CAPM"}],
                }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            domain_path = self._write_domain(Path(tmp))
            result = smoke.run_answer_smoke(domain_path, "CAPM은 무엇인가?", provider="gemini", adapter_cls=FakeAdapter)

        self.assertEqual(result["provider"], "gemini")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["used_pages_count"], 1)
        self.assertEqual(result["evidence_count"], 1)

    def test_forced_gemini_fallback_is_fail_exit_code(self):
        smoke = load_smoke_module()
        diagnostics = {
            "codex": smoke.CliDiagnostic("codex", "codex.cmd", False, False, "missing"),
            "gemini": smoke.CliDiagnostic("gemini", "gemini", True, True, "usable"),
        }
        answer = {
            "provider": "rule_based",
            "fallback": True,
            "status": "ok",
            "gemini_status": "gemini_timeout",
            "fallback_reason": "Gemini timeout",
            "evidence_count": 1,
        }

        classification = smoke.classify_smoke_result(answer, diagnostics, forced_provider="gemini")

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)
        self.assertIn("forced gemini provider fell back", classification.reason)

    def test_forced_gemini_readiness_answer_is_fail_exit_code(self):
        smoke = load_smoke_module()
        diagnostics = {
            "codex": smoke.CliDiagnostic("codex", "codex.cmd", False, False, "missing"),
            "gemini": smoke.CliDiagnostic("gemini", "gemini", True, True, "usable"),
        }
        answer = {
            "provider": "gemini",
            "fallback": False,
            "status": "ok",
            "answer_preview": "Okay, I'm ready. Please tell me what you'd like me to do.",
            "used_pages_count": 1,
            "evidence_count": 1,
        }

        classification = smoke.classify_smoke_result(
            answer,
            diagnostics,
            forced_provider="gemini",
            question="CAPM은 무엇인가?",
        )

        self.assertEqual(classification.label, "FAIL")
        self.assertEqual(classification.exit_code, 1)
        self.assertIn("readiness_response", classification.reason)

    def test_forced_gemini_unrelated_answer_is_fail_exit_code(self):
        smoke = load_smoke_module()
        diagnostics = {
            "codex": smoke.CliDiagnostic("codex", "codex.cmd", False, False, "missing"),
            "gemini": smoke.CliDiagnostic("gemini", "gemini", True, True, "usable"),
        }
        answer = {
            "provider": "gemini",
            "fallback": False,
            "status": "ok",
            "answer_preview": "이 답변은 질문과 무관한 일반 안내입니다.",
            "used_pages_count": 1,
            "evidence_count": 1,
        }

        classification = smoke.classify_smoke_result(
            answer,
            diagnostics,
            forced_provider="gemini",
            question="CAPM은 무엇인가?",
        )

        self.assertEqual(classification.label, "FAIL")
        self.assertIn("answer_not_related_to_question", classification.reason)

    def test_auto_mode_fallback_is_zero_exit_code(self):
        smoke = load_smoke_module()
        diagnostics = {
            "codex": smoke.CliDiagnostic("codex", "codex.cmd", False, False, "missing"),
            "gemini": smoke.CliDiagnostic("gemini", "gemini", False, False, "missing"),
        }
        answer = {"provider": "rule_based", "fallback": True, "status": "ok", "evidence_count": 1}

        classification = smoke.classify_smoke_result(answer, diagnostics, forced_provider="")

        self.assertEqual(classification.label, "FALLBACK")
        self.assertEqual(classification.exit_code, 0)

    def test_fallback_details_are_printed_for_gemini_failure(self):
        smoke = load_smoke_module()
        answer = {
            "provider": "rule_based",
            "fallback": True,
            "status": "ok",
            "gemini_status": "gemini_timeout",
            "fallback_reason": "Gemini timeout",
            "answer_preview": "fallback answer",
            "used_pages_count": 1,
            "evidence_count": 2,
        }

        rendered = "\n".join(smoke.format_answer_smoke(answer))

        self.assertIn("provider: rule_based", rendered)
        self.assertIn("fallback: true", rendered)
        self.assertIn("gemini_status: gemini_timeout", rendered)
        self.assertIn("fallback_reason: Gemini timeout", rendered)

    def test_main_reports_forced_gemini_failure_without_traceback(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            domain_path = self._write_domain(Path(tmp))
            smoke.load_environment_for_smoke = lambda ignore_dotenv=False: {"exists": False, "loaded": False, "loaded_keys": [], "ignored": ignore_dotenv}
            smoke.collect_cli_diagnostics = lambda env: {
                "codex": smoke.CliDiagnostic("codex", "codex.cmd", False, False, "missing"),
                "gemini": smoke.CliDiagnostic("gemini", "gemini", False, False, "version command failed: missing"),
            }
            smoke.run_answer_smoke = lambda domain, question, provider="", adapter_cls=None: {
                "provider": "rule_based",
                "fallback": True,
                "status": "ok",
                "gemini_status": "gemini_command_not_found",
                "fallback_reason": "Gemini CLI command not found",
                "answer_preview": "fallback answer",
                "used_pages_count": 0,
                "evidence_count": 1,
            }
            output = StringIO()
            with redirect_stdout(output):
                exit_code = smoke.main(["--domain", str(domain_path), "--question", "CAPM", "--provider", "gemini"])

        self.assertEqual(exit_code, 1)
        text = output.getvalue()
        self.assertIn("SMOKE RESULT: FAIL", text)
        self.assertIn("Gemini CLI command not found", text)
        self.assertNotIn("Traceback", text)

    def test_ignore_dotenv_skips_repo_env_and_reports_gemini_default_model(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LLM_WIKI_ANSWER_PROVIDER": "gemini"}, clear=True):
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

            env_load = smoke.load_environment_for_smoke(root, ignore_dotenv=True)
            summary = smoke.summarize_environment(os.environ, env_load)

        rendered = "\n".join(smoke.format_environment_summary(summary))

        self.assertTrue(env_load["exists"])
        self.assertFalse(env_load["loaded"])
        self.assertTrue(env_load["ignored"])
        self.assertEqual(summary["resolved_answer_provider"], "gemini")
        self.assertEqual(summary["resolved_answer_model"], "gemini-2.5-flash")
        self.assertIn(".env loaded: no (--ignore-dotenv)", rendered)

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
        (root / "wiki").mkdir()
        return domain


if __name__ == "__main__":
    unittest.main()
