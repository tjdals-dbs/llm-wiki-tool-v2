import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from wiki_tool.config import load_domain_config
from wiki_tool.claude_agent import ClaudeAgentResult
from wiki_tool.codex_agent import CodexAgentResult
from wiki_tool.mcp_server import create_fastmcp_server, register_mcp_tools
from wiki_tool.mcp_tools import WikiToolAdapter
from wiki_tool.scanner import scan_raw_sources
from wiki_tool.summarizer import summarize_new_sources
from wiki_tool.organizer import organize_pending_sources


class FakeMcpServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def decorator(fn):
            self.tools[name or fn.__name__] = fn
            return fn

        return decorator


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


def build_adapter(root: Path) -> WikiToolAdapter:
    domain = load_domain_config(write_domain(root), root=root)
    raw_file = root / "raw" / "capm.md"
    raw_file.parent.mkdir()
    raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험의 관계를 설명한다.", encoding="utf-8")
    scan_raw_sources(domain)
    summarize_new_sources(domain)
    organize_pending_sources(domain)
    return WikiToolAdapter(domain)


class AnswerAndMcpServerTests(unittest.TestCase):
    def test_answer_question_separates_body_used_pages_and_related_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))

            answer = adapter.answer_question("CAPM은 무엇인가?")

            self.assertEqual(answer["status"], "ok")
            self.assertEqual(answer["provider"], "rule_based")
            self.assertFalse(answer["fallback"])
            self.assertIn("wiki 근거", answer["answer"])
            self.assertTrue(answer["used_pages"])
            self.assertTrue(answer["related_pages"])
            self.assertTrue(answer["evidence"])
            self.assertIn("CAPM", answer["evidence"][0]["text"])
            self.assertNotIn("## Used Pages", answer["answer"])

    def test_answer_question_admits_when_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)

            answer = adapter.answer_question("없는 개념은?")

            self.assertEqual(answer["status"], "no_evidence")
            self.assertIn("근거가 부족합니다", answer["answer"])
            self.assertEqual(answer["used_pages"], [])
            self.assertEqual(answer["evidence"], [])

    def test_answer_question_uses_codex_provider_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))
            codex_result = CodexAgentResult(
                ok=True,
                status="ok",
                answer="Codex가 MCP wiki tools 근거로 답했습니다.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[],
            )

            with patch.dict(
                "os.environ",
                {"LLM_WIKI_AGENT_PROVIDER": "codex", "LLM_WIKI_ANSWER_MODEL": "answer-model"},
                clear=True,
            ), patch("wiki_tool.mcp_tools.CodexAgentBridge") as bridge_cls:
                bridge_cls.return_value.run_answer.return_value = codex_result
                answer = adapter.answer_question("CAPM은 무엇인가?")

            self.assertEqual(answer["provider"], "codex")
            self.assertFalse(answer["fallback"])
            self.assertIn("Codex가", answer["answer"])
            call = bridge_cls.return_value.run_answer.call_args
            self.assertEqual(call.args, ("CAPM은 무엇인가?",))
            self.assertIn("wiki_context", call.kwargs)
            self.assertIn("evidence", call.kwargs)

    def test_answer_question_falls_back_when_codex_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))
            codex_result = CodexAgentResult(
                ok=False,
                status="codex_command_not_found",
                answer="",
                used_pages=[],
                related_pages=[],
                evidence=[],
                error="Codex CLI command를 찾지 못했습니다.",
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.mcp_tools.CodexAgentBridge"
            ) as bridge_cls:
                bridge_cls.return_value.run_answer.return_value = codex_result
                answer = adapter.answer_question("CAPM은 무엇인가?")

            self.assertEqual(answer["provider"], "rule_based")
            self.assertTrue(answer["fallback"])
            self.assertEqual(answer["codex_status"], "codex_command_not_found")
            self.assertIn("Codex CLI", answer["fallback_reason"])
            self.assertIn("wiki 근거", answer["answer"])

    def test_answer_question_falls_back_when_codex_answer_has_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))
            codex_result = CodexAgentResult(
                ok=True,
                status="ok",
                answer="알겠습니다. 질문을 보내주세요.",
                used_pages=[],
                related_pages=[],
                evidence=[],
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.mcp_tools.CodexAgentBridge"
            ) as bridge_cls:
                bridge_cls.return_value.run_answer.return_value = codex_result
                answer = adapter.answer_question("CAPM은 무엇인가?")

            self.assertEqual(answer["provider"], "rule_based")
            self.assertTrue(answer["fallback"])
            self.assertEqual(answer["codex_status"], "codex_invalid_answer")
            self.assertIn("missing_evidence", answer["fallback_reason"])

    def test_answer_question_falls_back_safely_for_unsupported_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "gemini"}, clear=True), patch(
                "wiki_tool.mcp_tools.CodexAgentBridge"
            ) as bridge_cls, patch("wiki_tool.mcp_tools.ClaudeAgentBridge") as claude_bridge_cls:
                answer = adapter.answer_question("CAPM은 무엇인가?")

            bridge_cls.assert_not_called()
            claude_bridge_cls.assert_not_called()
            self.assertEqual(answer["provider"], "rule_based")
            self.assertTrue(answer["fallback"])
            self.assertEqual(answer["codex_status"], "unsupported_provider_fallback")
            self.assertIn("gemini", answer["fallback_reason"])

    def test_answer_question_uses_claude_provider_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))
            claude_result = ClaudeAgentResult(
                ok=True,
                status="ok",
                answer="Claude가 MCP wiki tools 근거로 답했습니다.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "CAPM 근거"}],
            )

            with patch.dict(
                "os.environ",
                {"LLM_WIKI_AGENT_PROVIDER": "claude", "LLM_WIKI_ANSWER_MODEL": "answer-model"},
                clear=True,
            ), patch("wiki_tool.mcp_tools.ClaudeAgentBridge") as bridge_cls, patch(
                "wiki_tool.mcp_tools.CodexAgentBridge"
            ) as codex_bridge_cls:
                bridge_cls.return_value.run_answer.return_value = claude_result
                answer = adapter.answer_question("CAPM은 무엇인가?")

            codex_bridge_cls.assert_not_called()
            self.assertEqual(answer["provider"], "claude")
            self.assertFalse(answer["fallback"])
            self.assertIn("Claude가", answer["answer"])
            call = bridge_cls.return_value.run_answer.call_args
            self.assertEqual(call.args, ("CAPM은 무엇인가?",))
            self.assertIn("wiki_context", call.kwargs)
            self.assertIn("evidence", call.kwargs)

    def test_answer_question_falls_back_when_claude_fails_or_returns_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))
            claude_result = ClaudeAgentResult(
                ok=False,
                status="claude_invalid_json",
                answer="",
                used_pages=[],
                related_pages=[],
                evidence=[],
                error="Claude CLI 응답에서 JSON 객체를 찾지 못했습니다.",
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "claude"}, clear=True), patch(
                "wiki_tool.mcp_tools.ClaudeAgentBridge"
            ) as bridge_cls:
                bridge_cls.return_value.run_answer.return_value = claude_result
                answer = adapter.answer_question("CAPM은 무엇인가?")

            self.assertEqual(answer["provider"], "rule_based")
            self.assertTrue(answer["fallback"])
            self.assertEqual(answer["claude_status"], "claude_invalid_json")
            self.assertIn("Claude CLI", answer["fallback_reason"])

    def test_answer_question_uses_question_type_specific_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_adapter(Path(tmp))

            definition = adapter.answer_question("CAPM은 무엇인가?")
            reason = adapter.answer_question("CAPM은 왜 중요한가?")
            comparison = adapter.answer_question("CAPM과 베타의 차이는?")
            how = adapter.answer_question("CAPM은 어떻게 활용해?")

            self.assertIn("정의하면", definition["answer"])
            self.assertIn("핵심 이유", reason["answer"])
            self.assertIn("비교의 기준", comparison["answer"])
            self.assertIn("활용 방법", how["answer"])
            self.assertLessEqual(len(definition["evidence"]), 3)

    def test_answer_evidence_filters_operational_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            concept = root / "wiki" / "concepts" / "capm.md"
            concept.parent.mkdir(parents=True)
            concept.write_text(
                "\n".join(
                    [
                        "# CAPM",
                        "",
                        "## Definition",
                        "",
                        "CAPM은 기대수익률과 체계적 위험을 연결한다.",
                        "",
                        "## Source Evidence",
                        "",
                        "- [capm](../sources/capm.md)",
                        "- Raw path: private/capm.pdf",
                        "- SHA256: abc123",
                        "- tool_trace: extractor-v1",
                        "- CAPM은 베타와 시장 위험 프리미엄을 사용한다.",
                    ]
                ),
                encoding="utf-8",
            )
            adapter = WikiToolAdapter(domain)

            answer = adapter.answer_question("CAPM")

            self.assertEqual(answer["status"], "ok")
            self.assertLessEqual(len(answer["evidence"]), 3)
            evidence_text = " ".join(item["text"] for item in answer["evidence"])
            self.assertIn("CAPM은", evidence_text)
            self.assertNotIn("Raw path", evidence_text)
            self.assertNotIn("SHA256", evidence_text)
            self.assertNotIn("tool_trace", evidence_text)

    def test_register_mcp_tools_exposes_adapter_methods_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            server = FakeMcpServer()

            registered = register_mcp_tools(server, domain)

            self.assertIn("list_wiki_pages", server.tools)
            self.assertIn("answer_question", server.tools)
            self.assertEqual(set(registered), set(server.tools))

    def test_create_fastmcp_server_registers_required_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)

            server = create_fastmcp_server(domain)
            tools = asyncio.run(server.list_tools())
            tool_names = {tool.name for tool in tools}

            self.assertIn("list_wiki_pages", tool_names)
            self.assertIn("scan_raw_sources", tool_names)
            self.assertIn("answer_question", tool_names)


if __name__ == "__main__":
    unittest.main()
