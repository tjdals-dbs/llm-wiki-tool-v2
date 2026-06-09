import json
import subprocess
import unittest

from wiki_tool.agent_provider import AgentProviderConfig
from wiki_tool.claude_agent import ClaudeAgentBridge, build_claude_command, parse_claude_output


class ClaudeAgentBridgeTests(unittest.TestCase):
    def test_claude_command_uses_prompt_mode_command_override_and_model(self):
        config = AgentProviderConfig(
            provider="claude",
            model="answer-model",
            codex_command="codex.cmd",
            provider_command="claude-custom",
        )

        command = build_claude_command(config, "질문")

        self.assertEqual(command[:2], ["claude-custom", "-p"])
        self.assertIn("--model", command)
        self.assertIn("answer-model", command)
        self.assertEqual(command[-1], "질문")

    def test_claude_command_omits_model_when_not_configured(self):
        config = AgentProviderConfig(
            provider="claude",
            model="",
            codex_command="codex.cmd",
            provider_command="claude",
        )

        command = build_claude_command(config, "질문")

        self.assertNotIn("--model", command)
        self.assertEqual(command, ["claude", "-p", "질문"])

    def test_claude_json_response_becomes_answer_payload(self):
        payload = {
            "status": "ok",
            "answer": "Claude가 wiki 근거로 답했습니다.",
            "used_pages": [{"path": "wiki/concepts/capm.md"}],
            "related_pages": [],
            "evidence": [{"path": "wiki/concepts/capm.md", "text": "근거"}],
        }

        result = parse_claude_output(json.dumps(payload, ensure_ascii=False))

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "Claude가 wiki 근거로 답했습니다.")
        self.assertEqual(result.to_answer_payload()["provider"], "claude")

    def test_claude_parse_failure_is_not_treated_as_success(self):
        result = parse_claude_output("JSON이 아닌 응답")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "claude_invalid_json")

    def test_claude_bridge_reports_command_failures(self):
        def error_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="not logged in")

        bridge = ClaudeAgentBridge(
            AgentProviderConfig(
                provider="claude",
                model="",
                codex_command="codex.cmd",
                provider_command="claude",
            ),
            runner=error_runner,
        )

        result = bridge.run_answer("CAPM은 무엇인가?")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "claude_error")
        self.assertIn("not logged in", result.error)


if __name__ == "__main__":
    unittest.main()
