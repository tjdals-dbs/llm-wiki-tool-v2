import unittest

from wiki_tool.desktop_gui import (
    GUI_ACTION_LABELS,
    GUI_PANEL_TITLES,
    GUI_PANEL_WEIGHTS,
    GUI_STYLE_COLORS,
    DesktopGuiPresenter,
)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def scan_raw_sources(self):
        self.calls.append("scan")
        return {"new_count": 1, "changed_count": 0, "ignored_count": 0}

    def summarize_new_sources(self):
        self.calls.append("summarize")
        return {"summarized_count": 1, "needs_review_count": 0}

    def organize_pending_sources(self):
        self.calls.append("organize")
        return {"promoted_count": 1, "merged_count": 0, "dropped_count": 0}

    def run_wiki_lint(self):
        self.calls.append("lint")
        return {"ok": True, "issues": []}

    def ask_wiki_context(self, query, limit=5):
        self.calls.append(("context", query, limit))
        return [{"path": "wiki/concepts/capm.md", "title": "CAPM"}]

    def answer_question(self, query):
        self.calls.append(("answer", query))
        return {
            "status": "ok",
            "answer": "wiki 근거를 기준으로 답합니다.",
            "used_pages": [{"path": "wiki/concepts/capm.md", "title": "CAPM"}],
            "related_pages": [],
        }

    def list_wiki_pages(self, page_type=None):
        pages = [
            {"path": "wiki/sources/capm.md", "type": "source", "title": "CAPM Source"},
            {"path": "wiki/concepts/capm.md", "type": "concept", "title": "CAPM"},
        ]
        if page_type is None:
            return pages
        return [page for page in pages if page["type"] == page_type]

    def read_wiki_page(self, path):
        if path == "wiki/sources/capm.md":
            return "\n".join(
                [
                    "# CAPM Source",
                    "",
                    "## Quality Review",
                    "",
                    "- quality: usable",
                    "- warnings: []",
                    "- recommended_actions: []",
                ]
            )
        return "# CAPM"

    def get_related_pages(self, path, depth=1):
        return [{"path": "wiki/sources/capm.md", "type": "source", "label": "CAPM Source"}]


class DesktopGuiTests(unittest.TestCase):
    def test_korean_three_panel_labels_do_not_offer_upload_ux(self):
        labels = " ".join(GUI_PANEL_TITLES + GUI_ACTION_LABELS)

        self.assertIn("위키 페이지", labels)
        self.assertIn("선택한 페이지", labels)
        self.assertIn("에이전트 제어", labels)
        self.assertIn("raw 스캔", labels)
        self.assertIn("새 source 요약", labels)
        self.assertIn("pending concept 조직", labels)
        self.assertNotIn("upload", labels.lower())
        self.assertNotIn("dropzone", labels.lower())
        self.assertNotIn("파일 업로드", labels)
        self.assertEqual(GUI_PANEL_WEIGHTS, (280, 796, 364))
        self.assertEqual(GUI_STYLE_COLORS["document_bg"], "#f7f7f5")

    def test_presenter_returns_korean_status_messages_for_agent_actions(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        self.assertIn("raw 스캔 완료", presenter.scan_raw_sources())
        self.assertIn("source 요약 완료", presenter.summarize_new_sources())
        self.assertIn("concept 조직 완료", presenter.organize_pending_sources())
        self.assertIn("lint 통과", presenter.run_wiki_lint())
        self.assertIn("wiki/concepts/capm.md", presenter.ask_agent("CAPM"))
        self.assertEqual(adapter.calls[:4], ["scan", "summarize", "organize", "lint"])

    def test_presenter_reports_pending_sources_and_source_quality(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        status = presenter.wiki_status()

        self.assertIn("pending source", status)
        self.assertIn("source quality", status)
        self.assertIn("usable", status)


if __name__ == "__main__":
    unittest.main()
