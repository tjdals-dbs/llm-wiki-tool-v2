import json
import tempfile
import unittest
from pathlib import Path

from wiki_tool.config import load_domain_config
from wiki_tool.graph import build_wiki_graph, get_related_pages
from wiki_tool.lint import run_wiki_lint
from wiki_tool.organizer import organize_pending_sources
from wiki_tool.scanner import scan_raw_sources
from wiki_tool.summarizer import summarize_new_sources


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


class ConceptGraphLintTests(unittest.TestCase):
    def test_usable_source_promotes_concept_and_graph_records_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# CAPM\nCAPM은 기대수익률과 체계적 위험을 연결한다. 베타는 시장 위험 민감도다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.promoted_count, 1)
            concept_page = root / "wiki" / "concepts" / "capm.md"
            content = concept_page.read_text(encoding="utf-8")
            self.assertIn("## Definition", content)
            self.assertIn("## Source Evidence", content)
            self.assertIn("[capm](../sources/capm.md)", content)
            self.assertNotIn("sha256", content.lower())

            graph = build_wiki_graph(domain)
            edge_types = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
            self.assertIn(("wiki/concepts/capm.md", "wiki/sources/capm.md", "derived_from"), edge_types)

            graph_file = root / "wiki" / "graph" / "graph.json"
            self.assertEqual(json.loads(graph_file.read_text(encoding="utf-8"))["nodes"][0]["type"], "concept")

            related = get_related_pages(domain, "wiki/concepts/capm.md", depth=1)
            self.assertIn("wiki/sources/capm.md", [page["path"] for page in related])

            lint_result = run_wiki_lint(domain)
            self.assertTrue(lint_result.ok)
            self.assertEqual(lint_result.issues, [])

    def test_weak_source_is_not_promoted_to_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "slides.pdf"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"%PDF-1.7\n%%EOF")
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.promoted_count, 0)
            self.assertEqual(list((root / "wiki" / "concepts").glob("*.md")), [])

    def test_lint_reports_concept_without_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            bad_concept = root / "wiki" / "concepts" / "bad.md"
            bad_concept.parent.mkdir(parents=True)
            bad_concept.write_text("# Bad\n\n## Definition\n\n근거 없는 개념", encoding="utf-8")

            result = run_wiki_lint(domain)

            self.assertFalse(result.ok)
            self.assertIn("Source Evidence", result.issues[0].message)


if __name__ == "__main__":
    unittest.main()
