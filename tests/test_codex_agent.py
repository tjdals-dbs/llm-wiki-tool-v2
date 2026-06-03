import json
import subprocess
import unittest

from wiki_tool.agent_prompts import (
    build_answer_prompt,
    build_concept_prompt,
    build_ingest_prompt,
    build_review_prompt,
)
from wiki_tool.agent_provider import AgentProviderConfig
from wiki_tool.codex_agent import CodexAgentBridge, build_codex_command, parse_codex_output


class CodexAgentBridgeTests(unittest.TestCase):
    def test_codex_command_includes_model_sandbox_and_stability_flags(self):
        config = AgentProviderConfig(provider="codex", model="answer-model", codex_command="codex.cmd")

        command = build_codex_command(config, "answer", "질문", output_path="last.txt")

        self.assertEqual(command[:2], ["codex.cmd", "exec"])
        self.assertIn("--model", command)
        self.assertIn("answer-model", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--output-last-message", command)
        self.assertIn("last.txt", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertEqual(command[-1], "질문")

    def test_ingest_concept_review_use_workspace_write_sandbox(self):
        config = AgentProviderConfig(provider="codex", model="model", codex_command="codex")

        for role in ["ingest", "concept", "review"]:
            command = build_codex_command(config, role, "prompt")
            self.assertIn("workspace-write", command)

    def test_bridge_parses_json_response(self):
        payload = {
            "status": "ok",
            "answer": "근거 기반 답변입니다.",
            "used_pages": [{"path": "wiki/concepts/capm.md"}],
            "related_pages": [{"path": "wiki/sources/capm.md"}],
            "evidence": [{"text": "CAPM은 위험과 수익을 연결한다."}],
        }

        result = parse_codex_output(json.dumps(payload, ensure_ascii=False))

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "근거 기반 답변입니다.")
        self.assertEqual(result.used_pages[0]["path"], "wiki/concepts/capm.md")

    def test_bridge_extracts_json_when_cli_logs_are_mixed_in_stdout(self):
        stdout = "\n".join(
            [
                "Reading additional input from stdin...",
                '{"status":"ok","answer":"pong","used_pages":[],"related_pages":[],"evidence":[]}',
                "tokens used",
            ]
        )

        result = parse_codex_output(stdout)

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "pong")

    def test_bridge_uses_raw_text_when_json_parse_fails(self):
        result = parse_codex_output("한국어 원문 답변")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "한국어 원문 답변")
        self.assertEqual(result.used_pages, [])

    def test_bridge_reads_output_last_message_file_before_stdout(self):
        calls = []
        inputs = []

        def runner(command, **kwargs):
            calls.append(command)
            inputs.append(kwargs.get("input"))
            output_path = command[command.index("--output-last-message") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write('{"status":"ok","answer":"from file","used_pages":[],"related_pages":[],"evidence":[]}')
            return subprocess.CompletedProcess(command, 0, stdout="noisy stdout", stderr="")

        bridge = CodexAgentBridge(
            AgentProviderConfig(provider="codex", model="m", codex_command="codex"),
            runner=runner,
        )

        result = bridge.run_answer("CAPM은?")

        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "from file")
        self.assertIn("--output-last-message", calls[0])
        self.assertIn("CAPM은?", inputs[0])

    def test_bridge_reports_command_not_found(self):
        def runner(*args, **kwargs):
            raise FileNotFoundError("missing")

        bridge = CodexAgentBridge(
            AgentProviderConfig(provider="codex", model="m", codex_command="missing-codex"),
            runner=runner,
        )

        result = bridge.run_answer("CAPM은?")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "codex_command_not_found")

    def test_bridge_reports_timeout_and_non_zero_exit(self):
        def timeout_runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        timeout_bridge = CodexAgentBridge(
            AgentProviderConfig(provider="codex", model="m", codex_command="codex"),
            runner=timeout_runner,
            timeout_seconds=1,
        )
        self.assertEqual(timeout_bridge.run_answer("CAPM은?").status, "codex_timeout")

        def error_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="invalid model")

        error_bridge = CodexAgentBridge(
            AgentProviderConfig(provider="codex", model="bad-model", codex_command="codex"),
            runner=error_runner,
        )
        result = error_bridge.run_answer("CAPM은?")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "codex_error")
        self.assertIn("invalid model", result.error)

    def test_answer_prompt_mentions_mcp_tools_context_evidence_and_json_contract(self):
        prompt = build_answer_prompt(
            "CAPM은 무엇인가?",
            wiki_context=[{"path": "wiki/concepts/capm.md", "title": "CAPM", "snippet": "요약"}],
            evidence=[{"path": "wiki/concepts/capm.md", "text": "CAPM 근거"}],
        )

        self.assertIn("ask_wiki_context", prompt)
        self.assertIn("search_wiki", prompt)
        self.assertIn("read_wiki_page", prompt)
        self.assertIn("get_related_pages", prompt)
        self.assertIn("한국어", prompt)
        self.assertIn('"used_pages"', prompt)
        self.assertIn("wiki context", prompt)
        self.assertIn("wiki evidence", prompt)

    def test_ingest_concept_review_prompts_forbid_raw_modification(self):
        prompts = [
            build_ingest_prompt("extracted"),
            build_concept_prompt("# Source"),
            build_review_prompt("changes"),
        ]

        for prompt in prompts:
            self.assertIn("raw 파일은 절대 수정, 이동, 삭제하지 마세요.", prompt)

    def test_ingest_prompt_requires_source_page_schema(self):
        prompt = build_ingest_prompt("CAPM text")

        self.assertIn("첫 줄은 반드시 '# <짧은 source 제목>'", prompt)
        for heading in ["## Summary", "## Key Points", "## Evidence", "## Candidate Concepts"]:
            self.assertIn(heading, prompt)


if __name__ == "__main__":
    unittest.main()
