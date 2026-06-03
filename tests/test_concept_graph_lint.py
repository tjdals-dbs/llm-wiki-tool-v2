import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_tool.agent_hooks import AgentHookResult
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
            self.assertEqual(result.provider, "rule_based")
            self.assertEqual(result.codex_used_count, 0)
            self.assertEqual(result.fallback_count, 0)
            concept_page = root / "wiki" / "concepts" / "capm.md"
            content = concept_page.read_text(encoding="utf-8")
            self.assertIn("## Definition", content)
            self.assertIn("## Explanation", content)
            self.assertIn("## Key Points", content)
            self.assertLess(content.index("## Definition"), content.index("## Explanation"))
            self.assertLess(content.index("## Explanation"), content.index("## Key Points"))
            self.assertLess(content.index("## Key Points"), content.index("## Related Concepts"))
            self.assertLess(content.index("## Related Concepts"), content.index("## Source Evidence"))
            self.assertLess(content.index("## Source Evidence"), content.index("## Maintenance Notes"))
            self.assertIn("## Source Evidence", content)
            self.assertIn("[capm](../sources/capm.md)", content)
            self.assertNotIn("sha256", content.lower())

            graph = build_wiki_graph(domain)
            edge_types = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
            self.assertIn(("wiki/concepts/capm.md", "wiki/sources/capm.md", "derived_from"), edge_types)
            concept_node = next(node for node in graph["nodes"] if node["path"] == "wiki/concepts/capm.md")
            self.assertEqual(concept_node["label"], "CAPM")
            self.assertEqual(concept_node["tooltip"], "CAPM")
            self.assertEqual(concept_node["style"]["shape"], "circle")

            graph_file = root / "wiki" / "graph" / "graph.json"
            self.assertEqual(json.loads(graph_file.read_text(encoding="utf-8"))["nodes"][0]["type"], "concept")

            related = get_related_pages(domain, "wiki/concepts/capm.md", depth=1)
            self.assertIn("wiki/sources/capm.md", [page["path"] for page in related])

            lint_result = run_wiki_lint(domain)
            self.assertTrue(lint_result.ok)
            self.assertEqual(lint_result.issues, [])

    def test_codex_concept_draft_is_used_when_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)
            codex_draft = "\n".join(
                [
                    "# CAPM",
                    "",
                    "## Definition",
                    "",
                    "Codex가 작성한 CAPM 정의입니다.",
                    "",
                    "## Explanation",
                    "",
                    "Codex concept draft가 반영되었습니다.",
                    "",
                    "## Source Evidence",
                    "",
                    "- [capm](../sources/capm.md)",
                    "- CAPM은 기대수익률과 위험을 연결한다.",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.organizer.draft_concept_update_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="concept",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=codex_draft,
                )
                result = organize_pending_sources(domain)

            content = (root / "wiki" / "concepts" / "capm.md").read_text(encoding="utf-8")
            self.assertEqual(result.provider, "codex")
            self.assertEqual(result.codex_used_count, 1)
            self.assertEqual(result.fallback_count, 0)
            self.assertIn("Codex concept draft가 반영되었습니다.", content)
            self.assertIn("## Agent Metadata", content)
            self.assertIn("- provider: codex", content)
            self.assertIn("- fallback: false", content)

    def test_invalid_codex_concept_draft_falls_back_to_rule_based_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.organizer.draft_concept_update_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="concept",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft="# CAPM\n\n## Definition\n\n근거 섹션이 없습니다.",
                )
                result = organize_pending_sources(domain)

            content = (root / "wiki" / "concepts" / "capm.md").read_text(encoding="utf-8")
            self.assertEqual(result.codex_used_count, 0)
            self.assertEqual(result.fallback_count, 1)
            self.assertIn("## Source Evidence", content)
            self.assertIn("missing_source_evidence", content)

    def test_codex_concept_merge_preserves_existing_human_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            existing = root / "wiki" / "concepts" / "capm.md"
            existing.parent.mkdir(parents=True)
            existing.write_text(
                "\n".join(
                    [
                        "# CAPM",
                        "",
                        "## Definition",
                        "",
                        "사람이 작성한 기존 설명입니다.",
                        "",
                        "## Source Evidence",
                        "",
                        "- [old](../sources/old.md)",
                    ]
                ),
                encoding="utf-8",
            )
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)
            codex_draft = "\n".join(
                [
                    "# CAPM",
                    "",
                    "## Definition",
                    "",
                    "Codex가 제안한 새 설명입니다.",
                    "",
                    "## Source Evidence",
                    "",
                    "- [capm](../sources/capm.md)",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.organizer.draft_concept_update_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="concept",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=codex_draft,
                )
                result = organize_pending_sources(domain)

            content = existing.read_text(encoding="utf-8")
            self.assertEqual(result.merged_count, 1)
            self.assertEqual(result.codex_used_count, 1)
            self.assertIn("사람이 작성한 기존 설명입니다.", content)
            self.assertIn("[capm](../sources/capm.md)", content)
            self.assertIn("## Agent Draft Notes", content)
            self.assertIn("Codex가 제안한 새 설명입니다.", content)

    def test_graph_uses_short_label_tooltip_and_type_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            concept = root / "wiki" / "concepts" / "long.md"
            concept.parent.mkdir(parents=True)
            concept.write_text(
                "\n".join(
                    [
                        "# 매우 긴 채권 듀레이션과 금리 위험 설명 문서",
                        "",
                        "## Definition",
                        "",
                        "듀레이션은 금리 변화에 대한 채권 가격의 민감도다.",
                        "",
                        "## Source Evidence",
                        "",
                        "- [duration](../sources/duration.md)",
                    ]
                ),
                encoding="utf-8",
            )
            source = root / "wiki" / "sources" / "duration.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Duration Source\n\n## Evidence\n\n- 듀레이션은 금리 변화와 관련된다.", encoding="utf-8")

            graph = build_wiki_graph(domain)

            node = next(item for item in graph["nodes"] if item["path"] == "wiki/concepts/long.md")
            self.assertLessEqual(len(node["label"]), 18)
            self.assertEqual(node["tooltip"], "매우 긴 채권 듀레이션과 금리 위험 설명 문서")
            self.assertEqual(node["style"]["color"], "#76d6a3")

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

    def test_existing_concept_is_merged_instead_of_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "first.md").write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            (raw_dir / "second.md").write_text("# CAPM\nCAPM은 베타와도 연결된다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            first = organize_pending_sources(domain, limit=1)
            second = organize_pending_sources(domain, limit=1)

            self.assertEqual(first.promoted_count, 1)
            self.assertEqual(second.merged_count, 1)
            self.assertEqual(len(list((root / "wiki" / "concepts").glob("capm*.md"))), 1)
            content = (root / "wiki" / "concepts" / "capm.md").read_text(encoding="utf-8")
            self.assertIn("[first](../sources/first.md)", content)
            self.assertIn("[second](../sources/second.md)", content)

    def test_existing_concept_alias_prevents_duplicate_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            existing = root / "wiki" / "concepts" / "capm-model.md"
            existing.parent.mkdir(parents=True)
            existing.write_text(
                "\n".join(
                    [
                        "# CAPM (Capital Asset Pricing Model)",
                        "",
                        "## Definition",
                        "",
                        "CAPM은 기존 개념 문서입니다.",
                        "",
                        "## Source Evidence",
                        "",
                        "- [old](../sources/old.md)",
                    ]
                ),
                encoding="utf-8",
            )
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.merged_count, 1)
            self.assertFalse((root / "wiki" / "concepts" / "capm.md").exists())
            content = existing.read_text(encoding="utf-8")
            self.assertIn("[capm](../sources/capm.md)", content)

    def test_existing_concept_filename_alias_prevents_duplicate_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            existing = root / "wiki" / "concepts" / "capital-asset-pricing-model.md"
            existing.parent.mkdir(parents=True)
            existing.write_text(
                "\n".join(
                    [
                        "# 기존 투자모형 문서",
                        "",
                        "## Definition",
                        "",
                        "사람이 작성한 설명입니다.",
                        "",
                        "## Source Evidence",
                        "",
                        "- [old](../sources/old.md)",
                    ]
                ),
                encoding="utf-8",
            )
            raw_file = root / "raw" / "capm-model.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# Capital Asset Pricing Model (CAPM)\nCapital Asset Pricing Model (CAPM)은 기대수익률과 위험을 연결한다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.merged_count, 1)
            self.assertFalse((root / "wiki" / "concepts" / "capm.md").exists())
            self.assertFalse((root / "wiki" / "concepts" / "capital-asset-pricing-model-capm.md").exists())
            content = existing.read_text(encoding="utf-8")
            self.assertIn("사람이 작성한 설명입니다.", content)
            self.assertIn("[capm-model](../sources/capm-model.md)", content)

    def test_parenthesized_acronym_drives_new_concept_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "dcf.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# Discounted Cash Flow (DCF)\nDCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.promoted_count, 1)
            self.assertTrue((root / "wiki" / "concepts" / "dcf.md").exists())
            self.assertFalse((root / "wiki" / "concepts" / "discounted-cash-flow-dcf.md").exists())

    def test_one_source_promotes_multiple_evidence_backed_concepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "valuation.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "\n".join(
                    [
                        "# Valuation",
                        "이 문서는 수업 전에 적은 짧은 안내다.",
                        "DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.",
                        "할인율은 현금흐름의 위험과 자본비용을 반영한다.",
                    ]
                ),
                encoding="utf-8",
            )
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.promoted_count, 2)
            dcf_page = root / "wiki" / "concepts" / "dcf.md"
            discount_page = root / "wiki" / "concepts" / "할인율.md"
            self.assertTrue(dcf_page.exists())
            self.assertTrue(discount_page.exists())
            dcf_content = dcf_page.read_text(encoding="utf-8")
            self.assertIn("## Definition", dcf_content)
            self.assertIn("## Key Points", dcf_content)
            self.assertIn("DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.", dcf_content)
            self.assertIn("## Related Concepts", dcf_content)
            self.assertIn("- 할인율", dcf_content)
            self.assertNotIn("Raw path", dcf_content)
            self.assertNotIn("SHA256", dcf_content)

    def test_generic_candidate_concept_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "notes.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# Notes\n이 문서는 일반적인 메모이며 명확한 개념 후보가 없다.", encoding="utf-8")
            scan_raw_sources(domain)
            summarize_new_sources(domain)

            result = organize_pending_sources(domain)

            self.assertEqual(result.promoted_count, 0)
            self.assertEqual(result.skipped_count, 1)

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
