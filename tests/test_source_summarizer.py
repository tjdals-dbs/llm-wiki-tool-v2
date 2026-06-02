import csv
import tempfile
import unittest
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
            self.assertIn("PDF 텍스트 추출 결과가 충분하지 않습니다.", content)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
