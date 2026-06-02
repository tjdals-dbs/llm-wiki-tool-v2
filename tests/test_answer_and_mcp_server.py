import tempfile
import unittest
from pathlib import Path

from wiki_tool.config import load_domain_config
from wiki_tool.mcp_server import register_mcp_tools
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
            self.assertIn("wiki 근거", answer["answer"])
            self.assertTrue(answer["used_pages"])
            self.assertTrue(answer["related_pages"])
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

    def test_register_mcp_tools_exposes_adapter_methods_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            server = FakeMcpServer()

            registered = register_mcp_tools(server, domain)

            self.assertIn("list_wiki_pages", server.tools)
            self.assertIn("answer_question", server.tools)
            self.assertEqual(set(registered), set(server.tools))


if __name__ == "__main__":
    unittest.main()
