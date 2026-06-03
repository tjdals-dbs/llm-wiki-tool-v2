import unittest

from wiki_tool.desktop_gui import (
    GUI_ACTION_LABELS,
    GUI_GRAPH_TYPE_LABELS,
    GUI_PANEL_TITLES,
    GUI_PANEL_WEIGHTS,
    GUI_STYLE_COLORS,
    DesktopGuiPresenter,
    build_local_graph_layout,
    _graph_item_label,
    _graph_status_text,
)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def scan_raw_sources(self):
        self.calls.append("scan")
        return {"new_count": 1, "changed_count": 0, "ignored_count": 0}

    def summarize_new_sources(self):
        self.calls.append("summarize")
        return {
            "provider": "codex",
            "summarized_count": 1,
            "needs_review_count": 0,
            "skipped_count": 2,
            "codex_used_count": 1,
            "fallback_count": 0,
        }

    def organize_pending_sources(self):
        self.calls.append("organize")
        return {
            "provider": "codex",
            "promoted_count": 1,
            "merged_count": 0,
            "dropped_count": 0,
            "codex_used_count": 1,
            "fallback_count": 1,
        }

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
            "provider": "rule_based",
            "fallback": False,
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
        return [
            {
                "path": "wiki/sources/capm.md",
                "type": "source",
                "label": "CAPM Source",
                "tooltip": "CAPM Source",
                "style": {"color": "#9fbfff", "shape": "square"},
            }
        ]

    def get_wiki_graph(self):
        self.calls.append("graph")
        return {
            "nodes": [
                {
                    "path": "wiki/concepts/capm.md",
                    "type": "concept",
                    "label": "CAPM",
                    "tooltip": "CAPM",
                    "style": {"color": "#76d6a3", "shape": "circle"},
                },
                {
                    "path": "wiki/sources/capm.md",
                    "type": "source",
                    "label": "CAPM Source",
                    "tooltip": "CAPM Source",
                    "style": {"color": "#9fbfff", "shape": "square"},
                },
            ],
            "edges": [],
        }


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
        self.assertEqual(GUI_GRAPH_TYPE_LABELS["concept"], "개념")

    def test_presenter_returns_korean_status_messages_for_agent_actions(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        self.assertIn("raw 스캔 완료", presenter.scan_raw_sources())
        self.assertIn("source 요약 완료", presenter.summarize_new_sources())
        self.assertIn("concept 조직 완료", presenter.organize_pending_sources())
        self.assertIn("lint 통과", presenter.run_wiki_lint())
        self.assertIn("wiki/concepts/capm.md", presenter.ask_agent("CAPM"))
        self.assertEqual(adapter.calls[:4], ["scan", "summarize", "organize", "lint"])

    def test_presenter_marks_codex_fallback_answer(self):
        adapter = FakeAdapter()
        adapter.answer_question = lambda query: {
            "status": "ok",
            "answer": "rule-based fallback 답변입니다.",
            "used_pages": [],
            "related_pages": [],
            "provider": "rule_based",
            "fallback": True,
            "codex_status": "codex_timeout",
            "fallback_reason": "Codex CLI 실행 시간이 초과되었습니다.",
        }
        presenter = DesktopGuiPresenter(adapter)

        message = presenter.ask_agent("CAPM")

        self.assertIn("provider: rule_based fallback (codex_timeout)", message)
        self.assertIn("fallback reason: Codex CLI 실행 시간이 초과되었습니다.", message)

    def test_presenter_reports_pending_sources_and_source_quality(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        status = presenter.wiki_status()

        self.assertIn("pending source", status)
        self.assertIn("source quality", status)
        self.assertIn("usable", status)

    def test_presenter_summarizes_maintenance_workflow_counts(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        status = presenter.run_maintenance_workflow()

        self.assertIn("maintenance 완료", status)
        self.assertIn("새 raw source: 1", status)
        self.assertIn("갱신된 source: 1", status)
        self.assertIn("needs_review source: 0", status)
        self.assertIn("promoted concept: 1", status)
        self.assertIn("merged concept: 0", status)
        self.assertIn("agent provider: source=codex, concept=codex", status)
        self.assertIn("Codex 사용: source 1개, concept 1개", status)
        self.assertIn("fallback: source 0개, concept 1개", status)
        self.assertIn("lint: 통과", status)
        self.assertIn("agent 사용: source Codex 1개/fallback 0개, concept Codex 1개/fallback 1개", status)
        self.assertIn("graph 갱신: node 2개, edge 0개", status)
        self.assertEqual(adapter.calls, ["scan", "summarize", "organize", "graph", "lint"])

    def test_graph_item_label_uses_short_label_and_tooltip(self):
        label = _graph_item_label(
            {
                "path": "wiki/concepts/duration.md",
                "type": "concept",
                "label": "듀레이션",
                "tooltip": "채권 듀레이션과 금리 위험",
            }
        )

        self.assertEqual(label, "개념 · 듀레이션 - 채권 듀레이션과 금리 위험")

    def test_graph_status_text_uses_full_tooltip_and_path(self):
        status = _graph_status_text(
            {
                "path": "wiki/concepts/duration.md",
                "type": "concept",
                "label": "듀레이션",
                "tooltip": "채권 듀레이션과 금리 위험",
            }
        )

        self.assertEqual(status, "개념 · 채권 듀레이션과 금리 위험 · wiki/concepts/duration.md")

    def test_local_graph_layout_places_selected_center_and_related_nodes(self):
        layout = build_local_graph_layout(
            {
                "path": "wiki/concepts/capm.md",
                "type": "concept",
                "label": "CAPM",
                "style": {"color": "#76d6a3", "shape": "circle"},
            },
            [
                {
                    "path": "wiki/sources/capm.md",
                    "type": "source",
                    "label": "CAPM Source",
                    "style": {"color": "#9fbfff", "shape": "square"},
                }
            ],
            width=600,
            height=220,
        )

        self.assertEqual(len(layout["nodes"]), 2)
        self.assertEqual(len(layout["edges"]), 1)
        self.assertTrue(layout["nodes"][0]["selected"])
        self.assertEqual(layout["nodes"][0]["shape"], "circle")
        self.assertEqual(layout["nodes"][1]["shape"], "square")
        self.assertEqual(layout["nodes"][0]["x"], 300)
        self.assertEqual(layout["nodes"][0]["y"], 110)


if __name__ == "__main__":
    unittest.main()
