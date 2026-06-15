import subprocess
import unittest

from wiki_tool.agent_provider import AgentProviderConfig
from wiki_tool.gemini_agent import GeminiAgentBridge, build_gemini_command


class GeminiAgentBridgeTests(unittest.TestCase):
    def test_gemini_command_uses_env_command_prompt_mode_and_model(self):
        config = AgentProviderConfig(
            provider="gemini",
            model="gemini-model",
            codex_command="codex.cmd",
            provider_command="gemini-custom",
        )

        command = build_gemini_command(config, "질문")

        self.assertEqual(command, ["gemini-custom", "--model", "gemini-model", "-p", "질문"])

    def test_gemini_command_omits_model_when_not_configured(self):
        config = AgentProviderConfig(
            provider="gemini",
            model="",
            codex_command="codex.cmd",
            provider_command="gemini",
        )

        command = build_gemini_command(config, "질문")

        self.assertEqual(command, ["gemini", "-p", "질문"])

    def test_gemini_bridge_returns_stdout_as_answer_payload(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="Gemini 응답", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_prompt("질문")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.answer, "Gemini 응답")
        self.assertEqual(result.to_answer_payload()["provider"], "gemini")
        self.assertEqual(calls[0][0][0], ["gemini", "-p", "질문"])

    def test_gemini_bridge_parses_json_answer_payload(self):
        def runner(*args, **kwargs):
            stdout = (
                '{"status":"ok","answer":"JSON Gemini 답변",'
                '"used_pages":[{"path":"wiki/sources/capm.md","title":"CAPM"}],'
                '"related_pages":[{"path":"wiki/concepts/beta.md"}],'
                '"evidence":[{"path":"wiki/sources/capm.md","text":"CAPM evidence"}]}'
            )
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_prompt("질문")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "JSON Gemini 답변")
        self.assertEqual(result.used_pages, [{"path": "wiki/sources/capm.md", "title": "CAPM"}])
        self.assertEqual(result.related_pages, [{"path": "wiki/concepts/beta.md"}])
        self.assertEqual(result.evidence, [{"path": "wiki/sources/capm.md", "text": "CAPM evidence"}])

    def test_gemini_bridge_can_run_review_prompt(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append(args[0])
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="- review ok", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_review("source 1, concept 1")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "- review ok")
        self.assertIn("changes summary", calls[0][-1])
        self.assertIn("source 1, concept 1", calls[0][-1])

    def test_gemini_bridge_handles_empty_stdout_as_graceful_failure(self):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="  ", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_prompt("질문")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "gemini_empty_output")
        self.assertIn("빈 응답", result.error)

    def test_gemini_bridge_reports_command_not_found_timeout_and_non_zero_exit(self):
        config = AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini")

        def missing(*_args, **_kwargs):
            raise FileNotFoundError("gemini")

        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="gemini", timeout=1)

        def non_zero(*args, **_kwargs):
            return subprocess.CompletedProcess(args=args[0], returncode=2, stdout="", stderr="bad auth")

        self.assertEqual(GeminiAgentBridge(config, runner=missing).run_prompt("질문").status, "gemini_command_not_found")
        self.assertEqual(GeminiAgentBridge(config, runner=timeout).run_prompt("질문").status, "gemini_timeout")
        error_result = GeminiAgentBridge(config, runner=non_zero).run_prompt("질문")
        self.assertEqual(error_result.status, "gemini_error")
        self.assertIn("bad auth", error_result.error)


if __name__ == "__main__":
    unittest.main()
