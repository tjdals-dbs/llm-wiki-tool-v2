import tempfile
import unittest
from pathlib import Path

from wiki_tool.agent_runtime import run_maintenance_once
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


class WikiNavigationAndSourceTypeTests(unittest.TestCase):
    def test_maintenance_pipeline_writes_index_overview_and_log_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")

            run_maintenance_once(domain)

            self.assertIn("## Concepts", (root / "wiki" / "index.md").read_text(encoding="utf-8"))
            self.assertIn("현재 wiki 상태", (root / "wiki" / "overview.md").read_text(encoding="utf-8"))
            self.assertIn("maintenance run", (root / "wiki" / "log.md").read_text(encoding="utf-8"))

    def test_html_summary_removes_chrome_and_preserves_article_alt_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "article.html"
            raw_file.parent.mkdir()
            raw_file.write_text(
                """
                <html>
                  <head><title>CAPM 기사</title><style>.x{}</style><script>ignore()</script></head>
                  <body>
                    <nav>메뉴 텍스트</nav>
                    <h1>CAPM 기사</h1>
                    <p>CAPM은 기대수익률과 위험을 설명한다.</p>
                    <img src="capm.png" alt="CAPM 그래프 설명">
                    <footer>사이트 푸터</footer>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "article.md").read_text(encoding="utf-8")
            self.assertIn("CAPM은 기대수익률과 위험을 설명한다.", content)
            self.assertIn("CAPM 그래프 설명", content)
            self.assertNotIn("메뉴 텍스트", content)
            self.assertNotIn("사이트 푸터", content)
            self.assertNotIn("ignore()", content)

    def test_image_summary_is_needs_review_and_recommends_vision_or_manual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "diagram.png"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"\x89PNG\r\n\x1a\n")
            scan_raw_sources(domain)

            summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "diagram.md").read_text(encoding="utf-8")
            self.assertIn("quality: weak", content)
            self.assertIn("enable_image_vision", content)
            self.assertIn("manual_review", content)


if __name__ == "__main__":
    unittest.main()
