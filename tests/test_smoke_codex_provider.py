import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
