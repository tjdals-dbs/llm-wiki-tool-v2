import csv
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from wiki_tool.config import load_domain_config
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


class SourceSummarizerTests(unittest.TestCase):
    def test_markdown_source_becomes_korean_source_summary_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# CAPM\nCAPM은 기대수익률과 체계적 위험을 연결한다. 베타는 시장 위험에 대한 민감도다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            source_page = root / "wiki" / "sources" / "capm.md"
            content = source_page.read_text(encoding="utf-8")
            self.assertIn("## Source Metadata", content)
            self.assertIn("- Raw path: capm.md", content)
            self.assertIn("## Summary", content)
            self.assertIn("## Key Points", content)
            self.assertIn("## Evidence", content)
            self.assertIn("## Candidate Concepts", content)
            self.assertIn("CAPM", content)
            self.assertIn("quality: usable", content)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "summarized")
            self.assertEqual(rows[0]["source_page"], "wiki/sources/capm.md")

    def test_weak_pdf_is_left_as_needs_review_with_pdf_vision_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "slides.pdf"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"%PDF-1.7\n%%EOF")
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.needs_review_count, 1)
            source_page = root / "wiki" / "sources" / "slides.md"
            content = source_page.read_text(encoding="utf-8")
            self.assertIn("quality: weak", content)
            self.assertIn("enable_pdf_vision", content)
            self.assertIn("manual_review", content)
            self.assertIn("PDF 텍스트 추출 결과가 충분하지 않습니다.", content)
            self.assertIn("텍스트 레이어", content)
            self.assertIn("수동 요약", content)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "needs_review")

    def test_pdf_summary_preserves_page_boundary_when_text_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "lecture.pdf"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"%PDF-1.7\n%%EOF")
            scan_raw_sources(domain)

            with patch(
                "wiki_tool.extractors._extract_pdf_pages",
                return_value=["1쪽 CAPM 설명은 기대수익률과 위험을 연결한다.", "2쪽 베타는 시장 위험 민감도다."],
            ):
                result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "lecture.md").read_text(encoding="utf-8")
            self.assertIn("PDF page 1", content)
            self.assertIn("PDF page 2", content)

    def test_summary_prefers_substantive_evidence_over_markdown_chrome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "valuation.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "\n".join(
                    [
                        "# Memo",
                        "",
                        "## 잡담",
                        "이 문서는 수업 전에 적은 짧은 안내다.",
                        "",
                        "## DCF",
                        "DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.",
                        "할인율은 현금흐름의 위험과 자본비용을 반영한다.",
                    ]
                ),
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "valuation.md").read_text(encoding="utf-8")
            self.assertIn("## Candidate Concept Evidence", content)
            self.assertIn("DCF: DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.", content)
            self.assertIn("할인율은 현금흐름의 위험과 자본비용을 반영한다.", content)
            self.assertNotIn("# Memo", content.split("## Summary", 1)[1].split("## Key Points", 1)[0])

    def test_markdown_frontmatter_stays_out_of_reader_facing_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "frontmatter.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "\n".join(
                    [
                        "---",
                        "source_path: private/lecture.pdf",
                        "sha256: should-not-appear-in-summary",
                        "tool_trace: extractor-v1",
                        "---",
                        "# 듀레이션",
                        "sha256: body-metadata-should-not-appear",
                        "메뉴",
                        "듀레이션은 금리 변화에 대한 채권 가격의 민감도를 설명하는 개념이다.",
                        "듀레이션은 금리 변화에 대한 채권 가격의 민감도를 설명하는 개념이다.",
                        "만기가 길고 쿠폰이 낮을수록 듀레이션은 커지는 경향이 있다.",
                    ]
                ),
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "frontmatter.md").read_text(encoding="utf-8")
            reader_body = content.split("## Quality Review", 1)[0]
            self.assertIn("## Summary", reader_body)
            self.assertIn("듀레이션은 금리 변화", reader_body)
            self.assertNotIn("source_path", reader_body)
            self.assertNotIn("tool_trace", reader_body)
            self.assertNotIn("body-metadata-should-not-appear", reader_body)
            self.assertNotIn("메뉴", reader_body)
            self.assertLess(content.index("## Summary"), content.index("## Source Metadata"))


if __name__ == "__main__":
    unittest.main()
