import tempfile
import unittest
from pathlib import Path

from wiki_tool.config import load_domain_config
from wiki_tool.mcp_tools import WikiToolAdapter
from wiki_tool.scanner import scan_raw_sources
from wiki_tool.summarizer import summarize_new_sources
from wiki_tool.organizer import organize_pending_sources


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


def build_sample_wiki(root: Path) -> WikiToolAdapter:
    domain = load_domain_config(write_domain(root), root=root)
    raw_file = root / "raw" / "capm.md"
    raw_file.parent.mkdir()
    raw_file.write_text(
        "# CAPM\nCAPM은 기대수익률과 체계적 위험을 연결한다. 베타는 시장 위험 민감도다.",
        encoding="utf-8",
    )
    scan_raw_sources(domain)
    summarize_new_sources(domain)
    organize_pending_sources(domain)
    return WikiToolAdapter(domain)


class McpToolAdapterTests(unittest.TestCase):
    def test_lists_reads_searches_and_blocks_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)

            concepts = adapter.list_wiki_pages(page_type="concept")
            self.assertEqual(concepts[0]["path"], "wiki/concepts/capm.md")

            content = adapter.read_wiki_page("wiki/concepts/capm.md")
            self.assertIn("## Source Evidence", content)

            search_result = adapter.search_wiki("기대수익률", limit=5)
            self.assertTrue(any(item["path"] == "wiki/concepts/capm.md" for item in search_result))

            with self.assertRaises(ValueError):
                adapter.read_wiki_page("../prd.md")

    def test_context_and_related_pages_include_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)

            context = adapter.ask_wiki_context("CAPM", limit=3)
            self.assertTrue(context)
            self.assertIn("wiki/concepts/capm.md", [item["path"] for item in context])

            related = adapter.get_related_pages("wiki/concepts/capm.md", depth=1)
            self.assertIn("wiki/sources/capm.md", [item["path"] for item in related])

    def test_apply_wiki_update_saves_answer_page_with_metadata_separated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)

            result = adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM은 기대수익률과 체계적 위험의 관계를 설명하는 모델입니다.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[{"path": "wiki/sources/capm.md"}],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "CAPM은 기대수익률과 체계적 위험을 연결한다."}],
                status="ok",
            )

            answer_path = root / result["path"]
            content = answer_path.read_text(encoding="utf-8")
            self.assertIn("## Answer", content)
            self.assertIn("## Used Pages", content)
            self.assertIn("## Evidence", content)
            self.assertIn("## Related Pages", content)
            self.assertIn("wiki/concepts/capm.md", content)
            self.assertIn("체계적 위험", content)

    def test_pipeline_tool_methods_return_korean_status_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            adapter = WikiToolAdapter(domain)

            scan = adapter.scan_raw_sources()
            summary = adapter.summarize_new_sources()
            organized = adapter.organize_pending_sources()
            lint = adapter.run_wiki_lint()

            self.assertEqual(scan["message"], "raw source scan 완료")
            self.assertEqual(summary["summarized_count"], 1)
            self.assertEqual(summary["provider"], "rule_based")
            self.assertEqual(summary["codex_used_count"], 0)
            self.assertEqual(summary["fallback_count"], 0)
            self.assertEqual(organized["promoted_count"], 1)
            self.assertEqual(organized["provider"], "rule_based")
            self.assertEqual(organized["codex_used_count"], 0)
            self.assertEqual(organized["fallback_count"], 0)
            self.assertTrue(lint["ok"])

    def test_agent_hook_methods_default_to_rule_based_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)

            ingest = adapter.draft_source_summary_with_agent("raw text")
            concept = adapter.draft_concept_update_with_agent("# Source")
            review = adapter.review_wiki_changes_with_agent("changes")

            self.assertEqual(ingest["role"], "ingest")
            self.assertEqual(concept["role"], "concept")
            self.assertEqual(review["role"], "review")
            self.assertTrue(ingest["fallback"])
            self.assertEqual(ingest["provider"], "rule_based")


if __name__ == "__main__":
    unittest.main()
