import subprocess
import unittest

from wiki_tool.agent_provider import AgentProviderConfig
from wiki_tool.agent_prompts import build_gemini_answer_prompt
from wiki_tool.gemini_agent import GeminiAgentBridge, build_gemini_command


class GeminiAgentBridgeTests(unittest.TestCase):
    def test_gemini_command_uses_env_command_prompt_mode_and_model(self):
        config = AgentProviderConfig(
            provider="gemini",
            model="gemini-model",
            codex_command="codex.cmd",
            provider_command="gemini-custom",
        )

        command = build_gemini_command(config)

        self.assertEqual(
            command,
            [
                "gemini-custom",
                "--skip-trust",
                "--approval-mode",
                "plan",
                "--output-format",
                "json",
                "--model",
                "gemini-model",
                "-p",
                "Follow the task from stdin. Output only the requested result.",
            ],
        )

    def test_gemini_command_omits_model_when_not_configured(self):
        config = AgentProviderConfig(
            provider="gemini",
            model="",
            codex_command="codex.cmd",
            provider_command="gemini",
        )

        command = build_gemini_command(config)

        self.assertNotIn("--model", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("--output-format", command)
        self.assertEqual(command[-2:], ["-p", "Follow the task from stdin. Output only the requested result."])

    def test_gemini_bridge_passes_prompt_via_stdin_not_command_argument(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="Gemini answer", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        bridge.run_prompt("very long prompt body")

        command = calls[0][0][0]
        kwargs = calls[0][1]
        self.assertNotIn("very long prompt body", command)
        self.assertEqual(kwargs["input"], "very long prompt body")

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
        self.assertEqual(calls[0][1]["input"], "질문")

    def test_gemini_bridge_extracts_text_from_cli_json_wrapper(self):
        def runner(*args, **kwargs):
            stdout = (
                '{"response":"{\\"status\\":\\"ok\\",\\"answer\\":\\"Wrapped answer\\",'
                '\\"used_pages\\":[],\\"related_pages\\":[],\\"evidence\\":[]}"}'
            )
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_prompt("question")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "Wrapped answer")

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

    def test_gemini_bridge_parses_fenced_json_answer_payload(self):
        def runner(*args, **kwargs):
            stdout = "\n".join(
                [
                    "```json",
                    '{"status":"ok","answer":"Fenced JSON answer",'
                    '"used_pages":[{"path":"wiki/sources/source.md"}],'
                    '"related_pages":[],"evidence":[{"path":"wiki/sources/source.md","text":"evidence"}]}',
                    "```",
                ]
            )
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_prompt("question")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "Fenced JSON answer")
        self.assertEqual(result.used_pages, [{"path": "wiki/sources/source.md"}])

    def test_gemini_bridge_strips_markdown_fence_and_intro_from_draft(self):
        def runner(*args, **kwargs):
            stdout = "\n".join(
                [
                    "Here is the requested draft:",
                    "",
                    "```markdown",
                    "# Source Title",
                    "",
                    "## Summary",
                    "",
                    "Source summary.",
                    "```",
                ]
            )
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_ingest("raw source text")

        self.assertTrue(result.ok)
        self.assertTrue(result.answer.startswith("# Source Title"))
        self.assertNotIn("```", result.answer)
        self.assertNotIn("Here is the requested draft", result.answer)

    def test_gemini_answer_prompt_limits_context_and_evidence(self):
        long_text = "x" * 2000
        prompt = build_gemini_answer_prompt(
            "What is this?",
            wiki_context=[
                {"path": f"wiki/sources/{idx}.md", "type": "source", "title": f"Source {idx}", "snippet": long_text}
                for idx in range(6)
            ],
            evidence=[
                {"path": f"wiki/sources/{idx}.md", "type": "source", "title": f"Evidence {idx}", "text": long_text}
                for idx in range(5)
            ],
        )

        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn('"status"', prompt)
        self.assertIn("wiki/sources/0.md", prompt)
        self.assertNotIn("wiki/sources/4.md", prompt)
        self.assertLess(len(prompt), 3500)

    def test_gemini_bridge_can_run_review_prompt(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append(kwargs["input"])
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="- review ok", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_review("source 1, concept 1")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "- review ok")
        self.assertIn("changes summary", calls[0])
        self.assertIn("source 1, concept 1", calls[0])

    def test_gemini_bridge_can_run_ingest_prompt(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append(kwargs["input"])
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="# Source\n\n## Summary\n\nok", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_ingest("raw source text")

        self.assertTrue(result.ok)
        self.assertIn("# Source", result.answer)
        self.assertIn("raw", calls[0])
        self.assertIn("## Summary", calls[0])
        self.assertIn("## Candidate Concept Evidence", calls[0])
        self.assertIn("raw source text", calls[0])

    def test_gemini_bridge_can_run_concept_prompt(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append(kwargs["input"])
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="# Concept\n\n## Source Evidence\n\n- ok", stderr="")

        bridge = GeminiAgentBridge(
            AgentProviderConfig(provider="gemini", model="", codex_command="codex.cmd", provider_command="gemini"),
            runner=runner,
        )

        result = bridge.run_concept("# Source\n\n## Candidate Concepts\n\n- Concept")

        self.assertTrue(result.ok)
        self.assertIn("# Concept", result.answer)
        self.assertIn("Concept Agent", calls[0])
        self.assertIn("## Source Evidence", calls[0])
        self.assertIn("## Candidate Concepts", calls[0])

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
