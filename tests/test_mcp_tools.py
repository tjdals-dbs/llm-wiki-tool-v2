import tempfile
import time
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


def _answer_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata


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

    def test_apply_wiki_update_updates_existing_answer_without_duplicate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)

            first = adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="첫 답변",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "첫 근거"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )
            answer_path = root / first["path"]
            first_metadata = _answer_metadata(answer_path)
            time.sleep(0.002)

            second = adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="갱신된 답변",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "갱신된 근거"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            answer_files = list((root / "wiki" / "answers").glob("*.md"))
            second_metadata = _answer_metadata(answer_path)
            self.assertEqual(first["path"], second["path"])
            self.assertEqual(len(answer_files), 1)
            self.assertTrue(first["created"])
            self.assertFalse(first["updated"])
            self.assertFalse(second["created"])
            self.assertTrue(second["updated"])
            self.assertEqual(first_metadata["created"], second_metadata["created"])
            self.assertNotEqual(first_metadata["updated"], second_metadata["updated"])
            self.assertEqual(second_metadata["question"], "CAPM은 무엇인가?")
            self.assertIn("갱신된 답변", answer_path.read_text(encoding="utf-8"))

    def test_apply_wiki_update_refreshes_navigation_graph_and_log_for_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)

            result = adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM 답변",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "근거"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            page_paths = [page["path"] for page in adapter.list_wiki_pages()]
            graph = adapter.get_wiki_graph()
            graph_paths = [node["path"] for node in graph["nodes"]]
            index = (root / "wiki" / "index.md").read_text(encoding="utf-8")
            overview = (root / "wiki" / "overview.md").read_text(encoding="utf-8")
            log = (root / "wiki" / "log.md").read_text(encoding="utf-8")

            self.assertTrue(result["navigation_refreshed"])
            self.assertTrue(result["graph_refreshed"])
            self.assertIn(result["path"], page_paths)
            self.assertIn(result["path"], graph_paths)
            self.assertIn(result["path"].replace("wiki/", "", 1), index)
            self.assertIn("answer pages: 1", overview)
            self.assertIn(f"answer saved: {result['path']}", log)

    def test_adapter_analyzes_saved_answer_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)
            saved = adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM is a model.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "Evidence"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            result = adapter.analyze_answer_candidates()

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["skipped_count"], 0)
            self.assertEqual(result["candidates"][0]["answer_path"], saved["path"])

    def test_adapter_drafts_answer_concept_updates_without_modifying_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = build_sample_wiki(root)
            concept_path = root / "wiki" / "concepts" / "capm.md"
            before = concept_path.read_text(encoding="utf-8")
            adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM is a model.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/sources/capm.md", "text": "Evidence"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            result = adapter.draft_answer_concept_updates()

            self.assertEqual(result["draft_count"], 1)
            self.assertEqual(result["drafts"][0]["draft_action"], "update_existing_concept")
            self.assertEqual(concept_path.read_text(encoding="utf-8"), before)

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

    def test_summarize_and_organize_refresh_navigation_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            adapter = WikiToolAdapter(domain)

            adapter.scan_raw_sources()
            summary = adapter.summarize_new_sources()

            index = root / "wiki" / "index.md"
            overview = root / "wiki" / "overview.md"
            log = root / "wiki" / "log.md"
            self.assertTrue(summary["navigation_refreshed"])
            self.assertTrue(index.exists())
            self.assertTrue(overview.exists())
            self.assertTrue(log.exists())
            self.assertIn("sources/capm.md", index.read_text(encoding="utf-8"))

            organized = adapter.organize_pending_sources()
            refreshed_index = index.read_text(encoding="utf-8")

            self.assertTrue(organized["navigation_refreshed"])
            self.assertIn("concepts/capm.md", refreshed_index)
            self.assertIn("concept pages: 1", overview.read_text(encoding="utf-8"))

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
