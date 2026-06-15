from enum import IntFlag
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wiki_tool.desktop_gui import (
    GUI_ACTION_LABELS,
    GUI_GRAPH_TYPE_LABELS,
    GUI_PANEL_TITLES,
    GUI_PANEL_WEIGHTS,
    GUI_STYLE_COLORS,
    AgentRouteResult,
    AgentWorkflowResult,
    AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE,
    DesktopGuiPresenter,
    DirectAdapterAgentFallback,
    DomainCreationRequest,
    GuiTaskSpec,
    GuiTaskResult,
    McpCodexAgentRoute,
    _agent_route_line,
    append_agent_exchange,
    build_agent_pending_message,
    build_agent_provider_panel_status,
    build_maintenance_pending_message,
    create_gui_user_domain,
    domain_controls_enabled,
    format_maintenance_report,
    agent_provider_detail_toggle_label,
    advanced_maintenance_default_visible,
    advanced_maintenance_toggle_label,
    build_maintenance_task_specs,
    maintenance_controls_enabled,
    open_domain_raw_folder,
    primary_maintenance_task_spec,
    toggle_agent_provider_detail_visible,
    toggle_advanced_maintenance_visible,
    render_chat_messages_html,
    replace_chat_message,
    summarize_maintenance_status,
    worker_failure_result,
    worker_success_result,
    build_domain_runtime,
    build_page_navigation_items,
    navigation_item_flags,
    _graph_item_label,
    _graph_status_text,
    build_local_graph_layout,
    resolve_wiki_link,
)
from wiki_tool.desktop_styles import configure_status_bar, configure_status_label, set_elided_status_text
from wiki_tool.user_domain import create_user_domain


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.saved_updates = []
        self.fail_save = False
        self.answer_payload = None
        self.save_result = None
        self.answer_draft_result = {"draft_count": 1, "skipped_count": 1, "drafts": [], "skipped": []}
        self.applied_answer_draft_result = None
        self.answer_update_result = {
            "applied_count": 1,
            "skipped_count": 1,
            "applied": [
                {
                    "answer_path": "wiki/answers/capm.md",
                    "target_concept_path": "wiki/concepts/capm.md",
                    "reason": "answer-derived note appended to concept page.",
                }
            ],
            "skipped": [
                {
                    "answer_path": "wiki/answers/beta.md",
                    "target_concept_path": "wiki/concepts/beta.md",
                    "reason": "source evidence is required before concept update.",
                }
            ],
            "applied_examples": ["wiki/answers/capm.md -> wiki/concepts/capm.md"],
            "skipped_reason_summary": [{"reason": "source evidence required", "count": 1}],
            "navigation_refreshed": True,
            "graph_refreshed": True,
        }

    def scan_raw_sources(self):
        self.calls.append("scan")
        return {"scanned_count": 1, "new_count": 1, "changed_count": 0, "ignored_count": 0}

    def summarize_new_sources(self):
        self.calls.append("summarize")
        return {
            "provider": "codex",
            "summarized_count": 1,
            "needs_review_count": 0,
            "skipped_count": 2,
            "codex_used_count": 1,
            "fallback_count": 0,
            "navigation_refreshed": True,
            "generated_pages": [
                "wiki/sources/chapter-10.md",
                "wiki/sources/chapter-11.md",
                "wiki/sources/chapter-12.md",
                "wiki/sources/chapter-13.md",
            ],
        }

    def organize_pending_sources(self):
        self.calls.append("organize")
        return {
            "provider": "codex",
            "promoted_count": 1,
            "merged_count": 0,
            "skipped_count": 0,
            "dropped_count": 0,
            "codex_used_count": 1,
            "fallback_count": 1,
            "navigation_refreshed": True,
            "changed_pages": [
                "wiki/concepts/risk.md",
                "wiki/concepts/return.md",
                "wiki/concepts/beta.md",
                "wiki/concepts/capm.md",
            ],
        }

    def run_wiki_lint(self):
        self.calls.append("lint")
        return {"ok": True, "issues": []}

    def analyze_answer_candidates(self):
        self.calls.append("answers")
        return {"candidate_count": 2, "skipped_count": 1, "candidates": [], "skipped": []}

    def draft_answer_concept_updates(self):
        self.calls.append("answer_drafts")
        return self.answer_draft_result

    def apply_answer_concept_updates(self, draft_result=None):
        self.calls.append("answer_updates")
        self.applied_answer_draft_result = draft_result
        return self.answer_update_result

    def review_wiki_changes_with_agent(self, changes_summary):
        self.calls.append("review")
        self.review_changes_summary = changes_summary
        return {
            "role": "review",
            "provider": "gemini",
            "fallback": False,
            "status": "ok",
            "draft": "- review ok",
            "error": "",
        }

    def answer_question(self, query):
        self.calls.append(("answer", query))
        if self.answer_payload is not None:
            return self.answer_payload
        return {
            "status": "ok",
            "answer": "wiki 근거를 기준으로 답합니다.",
            "used_pages": [{"path": "wiki/concepts/capm.md", "title": "CAPM"}],
            "related_pages": [],
            "evidence": [{"path": "wiki/sources/capm.md", "quote": "CAPM"}],
            "provider": "rule_based",
            "fallback": False,
            "save_decision": {
                "save_action": "save",
                "save_eligible": True,
                "save_reason": "근거 문서가 있어 위키 저장 대상으로 판단했습니다.",
                "suggested_title": "CAPM은 무엇인가",
            },
        }

    def apply_wiki_update(self, **kwargs):
        if self.fail_save:
            raise RuntimeError("save unavailable")
        self.saved_updates.append(kwargs)
        if self.save_result is not None:
            return self.save_result
        return {"path": "wiki/answers/capm.md", "status": kwargs.get("status", "ok")}

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


class FakeStatusFontMetrics:
    def elidedText(self, text, _mode, width):  # noqa: N802 - Qt-compatible test double
        char_width = 8
        if width <= 0 or len(text) * char_width <= width:
            return text
        visible_chars = max(1, width // char_width - 3)
        return text[:visible_chars] + "..."

    def height(self):
        return 14


class FakeStatusLabel:
    def __init__(self, width=160):
        self._width = width
        self._text = ""
        self._tooltip = ""
        self._properties = {}
        self._word_wrap = None
        self._min_height = None
        self._max_height = None
        self._metrics = FakeStatusFontMetrics()

    def width(self):
        return self._width

    def fontMetrics(self):  # noqa: N802 - Qt-compatible test double
        return self._metrics

    def setText(self, text):  # noqa: N802 - Qt-compatible test double
        self._text = text

    def text(self):
        return self._text

    def setToolTip(self, tooltip):  # noqa: N802 - Qt-compatible test double
        self._tooltip = tooltip

    def toolTip(self):  # noqa: N802 - Qt-compatible test double
        return self._tooltip

    def setProperty(self, key, value):  # noqa: N802 - Qt-compatible test double
        self._properties[key] = value

    def property(self, key):
        return self._properties.get(key)

    def setWordWrap(self, value):  # noqa: N802 - Qt-compatible test double
        self._word_wrap = value

    def setMinimumHeight(self, value):  # noqa: N802 - Qt-compatible test double
        self._min_height = value

    def setMaximumHeight(self, value):  # noqa: N802 - Qt-compatible test double
        self._max_height = value


class FakeStatusBar:
    def __init__(self):
        self._tooltip = ""
        self._min_height = None
        self._max_height = None

    def setToolTip(self, tooltip):  # noqa: N802 - Qt-compatible test double
        self._tooltip = tooltip

    def toolTip(self):  # noqa: N802 - Qt-compatible test double
        return self._tooltip

    def setMinimumHeight(self, value):  # noqa: N802 - Qt-compatible test double
        self._min_height = value

    def setMaximumHeight(self, value):  # noqa: N802 - Qt-compatible test double
        self._max_height = value


class FakeDomainAdapter(FakeAdapter):
    def __init__(self, config):
        super().__init__()
        self.config = config


class FakeRoute:
    def __init__(self):
        self.calls = []

    def ask(self, query):
        self.calls.append(query)
        return AgentRouteResult(
            route="mcp/codex",
            status="ok",
            answer="MCP tool route 답변입니다.",
            used_pages=[{"path": "wiki/concepts/capm.md", "title": "CAPM"}],
            related_pages=[],
        )


class FakePresenter:
    def __init__(self):
        self.calls = []

    def scan_raw_sources(self):
        self.calls.append("scan")
        return "raw 스캔 완료"

    def summarize_new_sources(self):
        self.calls.append("summarize")
        return "source 요약 완료"

    def organize_pending_sources(self):
        self.calls.append("organize")
        return "concept 조직 완료"

    def run_wiki_lint(self):
        self.calls.append("lint")
        return "wiki lint 통과"

    def run_maintenance_workflow(self):
        self.calls.append("maintenance")
        return "Maintenance Run Report\n상태: 성공"

    def wiki_status(self):
        self.calls.append("status")
        return "pending source: 0"


class FakeItemFlag(IntFlag):
    NoItemFlags = 0
    ItemIsSelectable = 1
    ItemIsEditable = 2
    ItemIsDragEnabled = 4
    ItemIsDropEnabled = 8
    ItemIsUserCheckable = 16
    ItemIsEnabled = 32


class DesktopStatusLabelTests(unittest.TestCase):
    def test_long_status_text_is_elided_and_preserves_full_tooltip(self):
        label = FakeStatusLabel(width=96)
        message = "pending concept 조직 실행 중... concept 후보가 많으면 오래 걸릴 수 있습니다."

        set_elided_status_text(label, message)

        self.assertEqual(label.toolTip(), message)
        self.assertEqual(label.property("fullStatusText"), message)
        self.assertLess(len(label.text()), len(message))
        self.assertTrue(label.text().endswith("..."))
        self.assertTrue(label.text().startswith("pending"))

    def test_short_status_text_is_not_elided(self):
        label = FakeStatusLabel(width=240)
        message = "wiki lint 통과"

        set_elided_status_text(label, message)

        self.assertEqual(label.text(), message)
        self.assertEqual(label.toolTip(), message)

    def test_status_text_elision_handles_tiny_width(self):
        label = FakeStatusLabel(width=1)
        message = "아주 긴 상태 메시지"

        set_elided_status_text(label, message, available_width=1)

        self.assertEqual(label.toolTip(), message)
        self.assertTrue(label.text())

    def test_status_label_is_configured_as_single_line_stable_height(self):
        label = FakeStatusLabel()

        configure_status_label(label)

        self.assertFalse(label._word_wrap)
        self.assertIsNotNone(label._min_height)
        self.assertEqual(label._min_height, label._max_height)

    def test_status_bar_is_configured_with_stable_hover_area_height(self):
        status_bar = FakeStatusBar()

        configure_status_bar(status_bar)

        self.assertEqual(status_bar._min_height, 28)
        self.assertEqual(status_bar._max_height, 28)

    def test_status_text_can_be_reelided_from_stored_full_message(self):
        label = FakeStatusLabel(width=240)
        message = "source summary fallback 1개: Codex draft schema 검증 실패로 rule-based 요약 사용"
        set_elided_status_text(label, message)
        full_message = label.property("fullStatusText")
        label._width = 80

        set_elided_status_text(label, full_message)

        self.assertEqual(label.toolTip(), message)
        self.assertLess(len(label.text()), len(message))

    def test_status_text_tooltip_is_applied_to_label_and_status_bar(self):
        label = FakeStatusLabel(width=128)
        status_bar = FakeStatusBar()
        message = "Maintenance Run Report\n상태: fallback 포함 성공\tCodex fallback 1개\nlint 통과"

        set_elided_status_text(label, message, tooltip_targets=(status_bar,))

        self.assertEqual(label.toolTip(), message)
        self.assertEqual(status_bar.toolTip(), message)
        self.assertNotIn("\n", label.text())
        self.assertTrue(label.text().endswith("..."))

    def test_multiline_status_text_is_flattened_but_tooltip_preserves_original(self):
        label = FakeStatusLabel(width=128)
        message = "Maintenance Run Report\n상태: fallback 포함 성공\tCodex fallback 1개\nlint 통과"

        set_elided_status_text(label, message)

        self.assertEqual(label.toolTip(), message)
        self.assertEqual(label.property("fullStatusText"), message)
        self.assertNotIn("\n", label.text())
        self.assertNotIn("\t", label.text())
        self.assertLess(len(label.text()), len(message))
        self.assertTrue(label.text().endswith("..."))

    def test_short_multiline_status_text_is_flattened_without_elision(self):
        label = FakeStatusLabel(width=240)
        message = "wiki lint\n통과"

        set_elided_status_text(label, message)

        self.assertEqual(label.toolTip(), message)
        self.assertEqual(label.text(), "wiki lint 통과")


class DesktopGuiTests(unittest.TestCase):
    def test_korean_three_panel_labels_do_not_offer_upload_ux(self):
        labels = " ".join(GUI_PANEL_TITLES + GUI_ACTION_LABELS)

        self.assertIn("위키 라이브러리", labels)
        self.assertIn("문서와 Graphify", labels)
        self.assertIn("Wiki Agent", labels)
        self.assertIn("raw 스캔", labels)
        self.assertIn("새 source 요약", labels)
        self.assertIn("pending concept 조직", labels)
        self.assertNotIn("upload", labels.lower())
        self.assertNotIn("dropzone", labels.lower())
        self.assertNotIn("파일 업로드", labels)
        self.assertEqual(GUI_PANEL_WEIGHTS, (280, 796, 364))
        self.assertEqual(GUI_STYLE_COLORS["document_bg"], "#f7f7f5")
        self.assertEqual(GUI_GRAPH_TYPE_LABELS["concept"], "개념")

    def test_domain_runtime_rebinds_adapter_presenter_and_task_specs_to_new_config(self):
        class Config:
            slug = "finance-private"

        runtime = build_domain_runtime(Config(), adapter_factory=FakeDomainAdapter)

        self.assertEqual(runtime.config.slug, "finance-private")
        self.assertIs(runtime.adapter.config, runtime.config)
        self.assertIs(runtime.presenter.adapter, runtime.adapter)
        self.assertIs(runtime.maintenance_task_specs["scan"].task.__self__, runtime.presenter)
        self.assertEqual(runtime.maintenance_task_specs["scan"].task.__name__, "scan_raw_sources")

    def test_gui_domain_creation_reuses_user_domain_initializer_and_loads_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def recording_creator(**kwargs):
                calls.append(kwargs)
                return create_user_domain(**kwargs)

            result = create_gui_user_domain(
                Path(tmp),
                DomainCreationRequest(
                    name="내 금융 위키",
                    slug="finance-private",
                    description="개인 금융 메모",
                    disclaimer="개인 학습용",
                ),
                creator=recording_creator,
            )

            self.assertTrue((Path(tmp) / "user_domains" / "finance-private" / "domain.yml").is_file())

        self.assertEqual(calls[0]["project_root"], Path(tmp))
        self.assertEqual(calls[0]["slug"], "finance-private")
        self.assertEqual(calls[0]["name"], "내 금융 위키")
        self.assertEqual(calls[0]["description"], "개인 금융 메모")
        self.assertEqual(calls[0]["disclaimer"], "개인 학습용")
        self.assertEqual(result.config.slug, "finance-private")
        self.assertEqual(result.config.disclaimer, "개인 학습용")
        self.assertIn("도메인 생성 완료", result.message)

    def test_domain_controls_are_disabled_during_agent_or_maintenance_work(self):
        self.assertTrue(domain_controls_enabled(agent_running=False, maintenance_running=False))
        self.assertFalse(domain_controls_enabled(agent_running=True, maintenance_running=False))
        self.assertFalse(domain_controls_enabled(agent_running=False, maintenance_running=True))

    def test_open_raw_folder_uses_current_domain_raw_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()

            calls = []
            result = open_domain_raw_folder(SimpleNamespace(raw_dir=raw_dir), opener=lambda path: calls.append(path))

        self.assertTrue(result.ok)
        self.assertEqual(calls, [str(raw_dir)])
        self.assertIn("raw 폴더를 열었습니다", result.message)

    def test_open_raw_folder_reports_missing_directory_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"

            calls = []
            result = open_domain_raw_folder(SimpleNamespace(raw_dir=raw_dir), opener=lambda path: calls.append(path))

            self.assertFalse(raw_dir.exists())

        self.assertFalse(result.ok)
        self.assertEqual(calls, [])
        self.assertIn("raw 폴더가 없습니다", result.message)

    def test_open_raw_folder_does_not_modify_raw_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()
            raw_file = raw_dir / "note.md"
            raw_file.write_text("raw fixture", encoding="utf-8")
            before = raw_file.read_text(encoding="utf-8")

            result = open_domain_raw_folder(SimpleNamespace(raw_dir=raw_dir), opener=lambda _path: None)
            after = raw_file.read_text(encoding="utf-8")

        self.assertTrue(result.ok)
        self.assertEqual(after, before)

    def test_page_navigation_groups_info_concepts_sources_and_logs_in_order(self):
        pages = [
            {"path": "wiki/sources/capm.md", "type": "source", "label": "CAPM Source"},
            {"path": "wiki/log.md", "type": "page", "label": "log"},
            {"path": "wiki/overview.md", "type": "overview", "label": "Overview"},
            {"path": "wiki/concepts/capm.md", "type": "concept", "label": "CAPM"},
            {"path": "wiki/index.md", "type": "index", "label": "Index"},
        ]

        items = build_page_navigation_items(pages)
        headers = [item for item in items if item["kind"] == "header"]

        self.assertEqual([header["title"] for header in headers], ["Wiki Info", "Concepts", "Sources", "Logs"])
        self.assertLess(
            next(index for index, item in enumerate(items) if item.get("title") == "Concepts"),
            next(index for index, item in enumerate(items) if item.get("title") == "Sources"),
        )

    def test_page_navigation_headers_have_marker_style_and_no_page_path(self):
        items = build_page_navigation_items(
            [
                {"path": "wiki/index.md", "type": "index", "label": "Index"},
                {"path": "wiki/concepts/capm.md", "type": "concept", "label": "CAPM"},
            ]
        )
        headers = [item for item in items if item["kind"] == "header"]
        pages = [item for item in items if item["kind"] == "page"]

        self.assertEqual(headers[0]["marker"], {"shape": "hexagon", "color": "#8b95a5"})
        self.assertEqual(headers[1]["marker"], {"shape": "circle", "color": "#4fb277"})
        self.assertTrue(all(not header.get("path") for header in headers))
        self.assertTrue(all("marker" not in page for page in pages))
        self.assertEqual([page["path"] for page in pages], ["wiki/index.md", "wiki/concepts/capm.md"])

    def test_page_navigation_header_flags_are_enabled_but_not_selectable(self):
        header = {"kind": "header", "title": "Concepts"}
        page = {"kind": "page", "title": "CAPM", "path": "wiki/concepts/capm.md"}

        header_flags = navigation_item_flags(header, FakeItemFlag)
        page_flags = navigation_item_flags(page, FakeItemFlag)

        self.assertTrue(header_flags & FakeItemFlag.ItemIsEnabled)
        self.assertFalse(header_flags & FakeItemFlag.ItemIsSelectable)
        self.assertTrue(page_flags & FakeItemFlag.ItemIsEnabled)
        self.assertTrue(page_flags & FakeItemFlag.ItemIsSelectable)

    def test_page_navigation_uses_labels_without_file_paths_or_extensions(self):
        items = build_page_navigation_items(
            [
                {"path": "wiki/sources/capm.md", "type": "source", "label": "CAPM"},
                {"path": "wiki/log.md", "type": "page", "title": "Maintenance Log"},
            ]
        )
        page_labels = [item["title"] for item in items if item["kind"] == "page"]

        self.assertEqual(page_labels, ["CAPM", "Maintenance Log"])
        self.assertFalse(any("wiki/" in label or label.endswith(".md") for label in page_labels))

    def test_presenter_returns_korean_status_messages_for_maintenance_actions(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter)

        self.assertIn("raw 스캔 완료", presenter.scan_raw_sources())
        self.assertIn("source 요약 완료", presenter.summarize_new_sources())
        self.assertIn("concept 조직 완료", presenter.organize_pending_sources())
        self.assertIn("lint 통과", presenter.run_wiki_lint())
        self.assertEqual(adapter.calls[:4], ["scan", "summarize", "organize", "lint"])

    def test_presenter_uses_mcp_first_route_for_agent_answers(self):
        adapter = FakeAdapter()
        route = FakeRoute()
        presenter = DesktopGuiPresenter(adapter, agent_route=route)

        message = presenter.ask_agent("CAPM")

        self.assertIn("MCP tool route 답변입니다.", message)
        self.assertIn("agent route: mcp/codex", message)
        self.assertIn("status: ok", message)
        self.assertIn("wiki/concepts/capm.md", message)
        self.assertEqual(route.calls, ["CAPM"])
        self.assertNotIn(("answer", "CAPM"), adapter.calls)

    def test_direct_fallback_route_marks_route_explicitly(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter, agent_route=DirectAdapterAgentFallback(adapter))

        message = presenter.ask_agent("CAPM")

        self.assertIn("agent route: direct fallback", message)
        self.assertIn("status: ok", message)
        self.assertIn("wiki/concepts/capm.md", message)

    def test_agent_workflow_auto_saves_save_eligible_answer(self):
        adapter = FakeAdapter()
        presenter = DesktopGuiPresenter(adapter, agent_route=DirectAdapterAgentFallback(adapter))

        result = presenter.ask_agent_workflow("CAPM은 무엇인가?")

        self.assertIn("wiki", result.message)
        self.assertIn("위키에 답변 저장됨", result.status_message)
        self.assertEqual(len(adapter.saved_updates), 1)
        self.assertTrue(result.refresh_pages)
        saved = adapter.saved_updates[0]
        self.assertEqual(saved["question"], "CAPM은 무엇인가?")
        self.assertIn("wiki", saved["answer"])
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["suggested_title"], "CAPM은 무엇인가")
        self.assertEqual(saved["used_pages"], [{"path": "wiki/concepts/capm.md", "title": "CAPM"}])
        self.assertEqual(saved["evidence"], [{"path": "wiki/sources/capm.md", "quote": "CAPM"}])

    def test_agent_workflow_skips_answer_when_save_decision_says_skip(self):
        adapter = FakeAdapter()
        adapter.answer_payload = {
            "status": "no_evidence",
            "answer": "근거가 부족합니다.",
            "used_pages": [],
            "related_pages": [],
            "evidence": [],
            "fallback": False,
            "save_decision": {
                "save_action": "skip",
                "save_eligible": False,
                "save_reason": "근거가 부족해 위키에 저장하지 않습니다.",
            },
        }
        presenter = DesktopGuiPresenter(adapter, agent_route=DirectAdapterAgentFallback(adapter))

        result = presenter.ask_agent_workflow("모르는 질문")

        self.assertEqual(adapter.saved_updates, [])
        self.assertFalse(result.refresh_pages)
        self.assertIn("근거가 부족합니다.", result.message)
        self.assertIn("답변 저장 제외", result.status_message)
        self.assertIn("근거가 부족해", result.status_message)

    def test_agent_workflow_preserves_answer_when_auto_save_fails(self):
        adapter = FakeAdapter()
        adapter.fail_save = True
        presenter = DesktopGuiPresenter(adapter, agent_route=DirectAdapterAgentFallback(adapter))

        result = presenter.ask_agent_workflow("CAPM은 무엇인가?")

        self.assertEqual(adapter.saved_updates, [])
        self.assertFalse(result.refresh_pages)
        self.assertIn("wiki", result.message)
        self.assertIn("답변 저장 실패", result.status_message)
        self.assertIn("save unavailable", result.status_message)

    def test_agent_workflow_reports_existing_answer_page_update(self):
        adapter = FakeAdapter()
        adapter.save_result = {
            "path": "wiki/answers/capm.md",
            "status": "ok",
            "created": False,
            "updated": True,
        }
        presenter = DesktopGuiPresenter(adapter, agent_route=DirectAdapterAgentFallback(adapter))

        result = presenter.ask_agent_workflow("CAPM은 무엇인가?")

        self.assertIn("기존 답변 페이지 업데이트됨", result.status_message)
        self.assertIn("wiki/answers/capm.md", result.status_message)
        self.assertTrue(result.refresh_pages)

    def test_mcp_route_falls_back_to_direct_adapter_when_registry_fails(self):
        adapter = FakeAdapter()

        def broken_registry(_config):
            raise RuntimeError("registry unavailable")

        route = McpCodexAgentRoute(object(), registry_factory=broken_registry, fallback=DirectAdapterAgentFallback(adapter))

        result = route.ask("CAPM")

        self.assertEqual(result.route, "direct fallback")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.error, "registry unavailable")
        self.assertEqual(result.fallback_reason, "MCP route 실행 실패로 direct adapter fallback 사용")
        self.assertIn(("answer", "CAPM"), adapter.calls)

    def test_mcp_route_labels_gemini_answer_provider(self):
        def registry(_config):
            return {
                "answer_question": lambda _query: {
                    "status": "ok",
                    "answer": "Gemini route answer",
                    "provider": "gemini",
                    "fallback": False,
                    "used_pages": [],
                    "related_pages": [],
                    "evidence": [],
                }
            }

        with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "gemini"}, clear=True):
            result = McpCodexAgentRoute(object(), registry_factory=registry).ask("CAPM")

        self.assertEqual(result.route, "mcp/gemini")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.answer, "Gemini route answer")

    def test_mcp_route_labels_gemini_fallback_status(self):
        def registry(_config):
            return {
                "answer_question": lambda _query: {
                    "status": "ok",
                    "answer": "rule-based fallback answer",
                    "provider": "rule_based",
                    "fallback": True,
                    "fallback_reason": "Gemini timeout",
                    "gemini_status": "gemini_timeout",
                    "used_pages": [],
                    "related_pages": [],
                    "evidence": [],
                }
            }

        with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "gemini"}, clear=True):
            result = McpCodexAgentRoute(object(), registry_factory=registry).ask("CAPM")

        self.assertEqual(result.route, "mcp/gemini fallback")
        self.assertEqual(result.status, "gemini_timeout")
        self.assertEqual(result.fallback_reason, "Gemini timeout")

    def test_agent_route_line_extracts_status_for_gui_label(self):
        self.assertEqual(_agent_route_line("answer\nagent route: mcp/codex\nstatus: ok"), "agent route: mcp/codex")
        self.assertEqual(_agent_route_line("answer only"), "agent route: 알 수 없음")

    def test_agent_worker_pending_message_is_immediate_and_route_visible(self):
        message = build_agent_pending_message()

        self.assertIn("답변 생성 중", message)
        self.assertIn("agent route: 실행 중", message)

    def test_agent_provider_status_summarizes_codex_roles(self):
        env = {
            "LLM_WIKI_AGENT_PROVIDER": "codex",
            "LLM_WIKI_AGENT_MODEL": "gpt-5.5",
        }

        status = build_agent_provider_panel_status(env=env)

        self.assertEqual(status.summary, "agent: codex / gpt-5.5")
        self.assertIn("answer: codex / gpt-5.5", status.detail_lines)
        self.assertIn("ingest: codex / gpt-5.5", status.detail_lines)
        self.assertIn("concept: codex / gpt-5.5", status.detail_lines)
        self.assertIn("review: codex / gpt-5.5", status.detail_lines)

    def test_agent_provider_status_marks_gemini_answer_and_review_as_supported(self):
        env = {
            "LLM_WIKI_AGENT_PROVIDER": "gemini",
            "LLM_WIKI_AGENT_MODEL": "gemini-pro",
        }

        status = build_agent_provider_panel_status(env=env)

        self.assertEqual(status.summary, "agent: gemini / gemini-pro")
        self.assertIn("answer: gemini / gemini-pro", status.detail_lines)
        self.assertIn("ingest: rule_based fallback", status.detail_lines)
        self.assertIn("concept: rule_based fallback", status.detail_lines)
        self.assertIn("review: gemini / gemini-pro", status.detail_lines)

    def test_agent_provider_status_summarizes_rule_based_without_model(self):
        status = build_agent_provider_panel_status(env={"LLM_WIKI_AGENT_PROVIDER": "rule_based"})

        self.assertEqual(status.summary, "agent: rule_based")
        self.assertEqual(
            status.detail_lines,
            [
                "answer: rule_based",
                "ingest: rule_based",
                "concept: rule_based",
                "review: rule_based",
            ],
        )

    def test_agent_provider_detail_toggle_defaults_collapsed(self):
        self.assertFalse(AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE)
        self.assertTrue(toggle_agent_provider_detail_visible(False))
        self.assertFalse(toggle_agent_provider_detail_visible(True))
        self.assertEqual(agent_provider_detail_toggle_label(False), "자세히")
        self.assertEqual(agent_provider_detail_toggle_label(True), "접기")

    def test_chat_question_adds_user_and_assistant_pending_messages(self):
        messages = []

        pending_index = append_agent_exchange(messages, "CAPM은 무엇인가?")

        self.assertEqual(pending_index, 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "CAPM은 무엇인가?")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["status"], "pending")
        self.assertIn("답변 생성 중", messages[1]["content"])

    def test_chat_html_uses_directional_bubbles_without_author_label(self):
        messages = [
            {"role": "user", "content": "CAPM?", "status": "complete"},
            {"role": "assistant", "content": "답변입니다.", "status": "complete"},
        ]

        html = render_chat_messages_html(messages)

        self.assertIn("message-row user", html)
        self.assertIn("message-row assistant", html)
        self.assertIn("bubble user-bubble", html)
        self.assertIn("bubble assistant-bubble", html)
        self.assertNotIn("haiku 서브에이전트", html)
        self.assertNotIn("assistant:", html.lower())

    def test_agent_completion_replaces_pending_message(self):
        messages = []
        pending_index = append_agent_exchange(messages, "CAPM?")

        replace_chat_message(messages, pending_index, "완료 답변\n\nagent route: mcp/codex\nstatus: ok")

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[pending_index]["status"], "complete")
        self.assertIn("완료 답변", messages[pending_index]["content"])
        self.assertNotIn("답변 생성 중", messages[pending_index]["content"])

    def test_chat_html_renders_used_pages_as_supporting_text(self):
        messages = [
            {
                "role": "assistant",
                "status": "complete",
                "content": "CAPM 답변\n\nused pages:\n- wiki/concepts/capm.md: CAPM\n\nrelated pages:\n- 없음",
            }
        ]

        html = render_chat_messages_html(messages)

        self.assertIn("message-support", html)
        self.assertIn("used pages:", html)
        self.assertIn("related pages:", html)

    def test_maintenance_status_summary_does_not_require_chat_message(self):
        summary = summarize_maintenance_status("maintenance 실행", "Maintenance Run Report\n전체 동기화 완료\n상태: 성공\nraw scan: 신규 0개")

        self.assertIn("maintenance 실행 완료", summary)
        self.assertIn("상태: 성공", summary)
        self.assertLessEqual(len([line for line in summary.splitlines() if line.strip()]), 2)

    def test_worker_success_result_preserves_agent_route_and_output(self):
        result = worker_success_result("agent", "답변\n\nagent route: mcp/codex\nstatus: ok", refresh_pages=False)

        self.assertIsInstance(result, GuiTaskResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.route_line, "agent route: mcp/codex")
        self.assertFalse(result.refresh_pages)
        self.assertIn("status: ok", result.message)

    def test_worker_success_result_preserves_agent_save_status_message(self):
        workflow_result = AgentWorkflowResult(
            message="답변\n\nagent route: mcp/codex\nstatus: ok",
            status_message="위키에 답변 저장됨: wiki/answers/capm.md",
        )

        result = worker_success_result("agent", workflow_result, refresh_pages=False)

        self.assertEqual(result.message, workflow_result.message)
        self.assertEqual(result.route_line, "agent route: mcp/codex")
        self.assertEqual(result.status_message, "위키에 답변 저장됨: wiki/answers/capm.md")

    def test_worker_success_result_uses_agent_workflow_refresh_flag(self):
        workflow_result = AgentWorkflowResult(
            message="답변\n\nagent route: mcp/codex\nstatus: ok",
            status_message="위키에 답변 저장됨: wiki/answers/capm.md",
            refresh_pages=True,
        )

        result = worker_success_result("agent", workflow_result, refresh_pages=False)

        self.assertTrue(result.refresh_pages)

    def test_maintenance_worker_success_result_preserves_report_format(self):
        report = "Maintenance Run Report\n상태: 성공"

        result = worker_success_result("maintenance", report, refresh_pages=True)

        self.assertTrue(result.ok)
        self.assertTrue(result.refresh_pages)
        self.assertIn("Maintenance Run Report", result.message)
        self.assertIn("상태: 성공", result.message)

    def test_worker_failure_result_is_user_visible(self):
        result = worker_failure_result("maintenance", "maintenance 실행", RuntimeError("boom"))

        self.assertFalse(result.ok)
        self.assertFalse(result.refresh_pages)
        self.assertIn("maintenance 실행 실패", result.message)
        self.assertIn("boom", result.message)

    def test_maintenance_pending_message_is_immediate(self):
        self.assertIn("maintenance 실행 중", build_maintenance_pending_message())

    def test_maintenance_task_specs_are_lazy_and_background_safe(self):
        presenter = FakePresenter()

        specs = build_maintenance_task_specs(presenter)
        organize = specs["organize"]

        self.assertIsInstance(organize, GuiTaskSpec)
        self.assertEqual(presenter.calls, [])
        self.assertIn("pending concept 조직 실행 중", organize.pending_message)
        self.assertIn("오래 걸릴 수 있습니다", organize.pending_message)
        self.assertTrue(organize.refresh_pages)
        self.assertEqual(organize.task(), "concept 조직 완료")
        self.assertEqual(presenter.calls, ["organize"])

    def test_primary_wiki_update_button_uses_existing_maintenance_task(self):
        presenter = FakePresenter()
        specs = build_maintenance_task_specs(presenter)

        primary = primary_maintenance_task_spec(specs)

        self.assertEqual(primary.key, "maintenance")
        self.assertEqual(primary.task.__self__, presenter)
        self.assertEqual(primary.task.__name__, "run_maintenance_workflow")
        self.assertTrue(primary.refresh_pages)

    def test_advanced_maintenance_area_is_collapsed_by_default_and_toggles(self):
        self.assertFalse(advanced_maintenance_default_visible())
        self.assertTrue(toggle_advanced_maintenance_visible(False))
        self.assertFalse(toggle_advanced_maintenance_visible(True))
        self.assertEqual(advanced_maintenance_toggle_label(False), "고급 관리 펼치기")
        self.assertEqual(advanced_maintenance_toggle_label(True), "고급 관리 접기")

    def test_existing_detail_maintenance_task_specs_are_preserved(self):
        specs = build_maintenance_task_specs(FakePresenter())

        self.assertEqual(list(specs), ["scan", "summarize", "organize", "lint", "maintenance", "status"])

    def test_maintenance_controls_disable_during_maintenance_run(self):
        self.assertTrue(maintenance_controls_enabled(maintenance_running=False))
        self.assertFalse(maintenance_controls_enabled(maintenance_running=True))

    def test_maintenance_task_specs_mark_refresh_requirements(self):
        specs = build_maintenance_task_specs(FakePresenter())

        self.assertTrue(specs["scan"].refresh_pages)
        self.assertTrue(specs["summarize"].refresh_pages)
        self.assertTrue(specs["organize"].refresh_pages)
        self.assertTrue(specs["maintenance"].refresh_pages)
        self.assertFalse(specs["lint"].refresh_pages)
        self.assertFalse(specs["status"].refresh_pages)

    def test_all_maintenance_task_specs_return_user_visible_messages(self):
        presenter = FakePresenter()

        specs = build_maintenance_task_specs(presenter)
        messages = [specs[key].task() for key in ["scan", "summarize", "organize", "lint", "status"]]

        self.assertEqual(presenter.calls, ["scan", "summarize", "organize", "lint", "status"])
        self.assertTrue(all(message for message in messages))

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

        with patch.dict("os.environ", {"LLM_WIKI_REVIEW_PROVIDER": "gemini"}, clear=True):
            status = presenter.run_maintenance_workflow()

        self.assertIn("Maintenance Run Report", status)
        self.assertIn("상태: fallback 포함 성공", status)
        self.assertIn("raw scan: 신규 1개, 변경 0개, 유지 0개, 제외 0개", status)
        self.assertIn("source summary: provider codex, 생성 1개, skipped 2개, fallback 0개, 검토 필요 0개", status)
        self.assertIn("concept organize: provider codex, promoted 1개, merged 0개, skipped 0개, fallback 1개", status)
        self.assertIn("answer candidates: 2개, skipped 1개", status)
        self.assertIn("answer concept drafts: 1개, skipped 1개", status)
        self.assertIn("answer concept updates: applied 1개, skipped 1개", status)
        self.assertIn("review: provider gemini, status ok, fallback false", status)
        self.assertIn("concept 반영: wiki/answers/capm.md -> wiki/concepts/capm.md", status)
        self.assertIn("skipped reasons: source evidence required 1개", status)
        self.assertIn("source 생성: wiki/sources/chapter-10.md, wiki/sources/chapter-11.md, wiki/sources/chapter-12.md 외 1개", status)
        self.assertIn("concept 변경: wiki/concepts/risk.md, wiki/concepts/return.md, wiki/concepts/beta.md 외 1개", status)
        self.assertNotIn("wiki/sources/chapter-13.md", status)
        concept_change_line = next(line for line in status.splitlines() if line.startswith("concept 변경:"))
        self.assertNotIn("wiki/concepts/capm.md", concept_change_line)
        self.assertIn("lint: 통과, issue 0개", status)
        self.assertIn("refresh: graph 갱신, navigation 갱신", status)
        self.assertIn("안전성: raw 불변성 확인 불가, lint 통과, fallback 발생", status)
        self.assertIn("산출물: source 1개, concept 변경 1개, graph node 2개, edge 0개", status)
        self.assertIn("원인:", status)
        self.assertIn("concept organize fallback 1개", status)
        self.assertEqual(
            adapter.calls,
            ["scan", "summarize", "organize", "answers", "answer_drafts", "answer_updates", "review", "graph", "lint"],
        )
        self.assertIs(adapter.applied_answer_draft_result, adapter.answer_draft_result)
        self.assertIn("source summarized", adapter.review_changes_summary)

    def test_maintenance_report_marks_success_when_every_stage_passes(self):
        adapter = FakeAdapter()
        adapter.scan_raw_sources = lambda: adapter.calls.append("scan") or {
            "scanned_count": 9,
            "new_count": 1,
            "changed_count": 0,
            "ignored_count": 0,
        }
        adapter.organize_pending_sources = lambda: adapter.calls.append("organize") or {
            "provider": "codex",
            "promoted_count": 4,
            "merged_count": 2,
            "skipped_count": 0,
            "codex_used_count": 4,
            "fallback_count": 0,
        }
        presenter = DesktopGuiPresenter(adapter)

        status = presenter.run_maintenance_workflow()

        self.assertIn("상태: 성공", status)
        self.assertIn("raw scan: 신규 1개, 변경 0개, 유지 8개, 제외 0개", status)
        self.assertIn("concept organize: provider codex, promoted 4개, merged 2개", status)
        self.assertIn("fallback 없음", status)
        self.assertNotIn("{", status)
        self.assertNotIn("}", status)

    def test_maintenance_report_summarizes_changed_items_with_limit(self):
        report = format_maintenance_report(
            {
                "scanned_count": 4,
                "new_count": 2,
                "changed_count": 1,
                "ignored_count": 1,
            },
            {
                "provider": "rule_based",
                "summarized_count": 4,
                "skipped_count": 1,
                "fallback_count": 0,
                "needs_review_count": 0,
                "navigation_refreshed": True,
                "generated_pages": [
                    "wiki/sources/a.md",
                    "wiki/sources/b.md",
                    "wiki/sources/c.md",
                    "wiki/sources/d.md",
                ],
            },
            {
                "provider": "rule_based",
                "promoted_count": 1,
                "merged_count": 2,
                "skipped_count": 3,
                "fallback_count": 0,
                "navigation_refreshed": True,
                "changed_pages": [
                    "wiki/concepts/alpha.md",
                    "wiki/concepts/beta.md",
                    "wiki/concepts/gamma.md",
                    "wiki/concepts/delta.md",
                ],
            },
            {"ok": True, "issues": []},
            {"nodes": [], "edges": []},
            answer_concept_updates={
                "applied_count": 4,
                "skipped_count": 3,
                "applied_examples": [
                    "wiki/answers/a.md -> wiki/concepts/a.md",
                    "wiki/answers/b.md -> wiki/concepts/b.md",
                    "wiki/answers/c.md -> wiki/concepts/c.md",
                    "wiki/answers/d.md -> wiki/concepts/d.md",
                ],
                "skipped_reason_summary": [
                    {"reason": "source evidence required", "count": 2},
                    {"reason": "already applied", "count": 1},
                ],
                "navigation_refreshed": True,
                "graph_refreshed": True,
            },
        )

        self.assertIn("raw scan: 신규 2개, 변경 1개, 유지 0개, 제외 1개", report)
        self.assertIn("source summary: provider rule_based, 생성 4개, skipped 1개, fallback 0개, 검토 필요 0개", report)
        self.assertIn("concept organize: provider rule_based, promoted 1개, merged 2개, skipped 3개, fallback 0개", report)
        self.assertIn("source 생성: wiki/sources/a.md, wiki/sources/b.md, wiki/sources/c.md 외 1개", report)
        self.assertIn("concept 변경: wiki/concepts/alpha.md, wiki/concepts/beta.md, wiki/concepts/gamma.md 외 1개", report)
        self.assertIn("concept 반영: wiki/answers/a.md -> wiki/concepts/a.md, wiki/answers/b.md -> wiki/concepts/b.md, wiki/answers/c.md -> wiki/concepts/c.md 외 1개", report)
        self.assertIn("skipped reasons: source evidence required 2개, already applied 1개", report)
        self.assertIn("refresh: graph 갱신, navigation 갱신", report)

    def test_maintenance_report_marks_lint_failure_with_short_issues(self):
        adapter = FakeAdapter()
        adapter.run_wiki_lint = lambda: adapter.calls.append("lint") or {
            "ok": False,
            "issues": [
                {"path": "wiki/concepts/very/deep/private/capm.md", "message": "broken link 시장위험프리미엄.md"},
                {"path": "wiki/sources/foo.md", "message": "missing evidence"},
            ],
        }
        presenter = DesktopGuiPresenter(adapter)

        status = presenter.run_maintenance_workflow()

        self.assertIn("상태: 실패", status)
        self.assertIn("lint: 실패, issue 2개", status)
        self.assertIn("문제:", status)
        self.assertIn("- capm.md: broken link 시장위험프리미엄.md", status)
        self.assertIn("- foo.md: missing evidence", status)
        self.assertNotIn("wiki/concepts/very/deep/private/capm.md", status)

    def test_maintenance_report_checks_raw_immutability_when_config_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "capm.md").write_text("public safe raw", encoding="utf-8")

            class Config:
                pass

            adapter = FakeAdapter()
            adapter.config = Config()
            adapter.config.raw_dir = raw_dir
            presenter = DesktopGuiPresenter(adapter)

            status = presenter.run_maintenance_workflow()

        self.assertIn("raw 변경 없음", status)

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

    def test_resolve_wiki_link_handles_relative_markdown_links(self):
        valid_paths = {"wiki/sources/capm.md", "wiki/concepts/beta.md"}

        self.assertEqual(resolve_wiki_link("wiki/concepts/capm.md", "../sources/capm.md", valid_paths), "wiki/sources/capm.md")
        self.assertEqual(resolve_wiki_link("wiki/concepts/capm.md", "wiki/concepts/beta.md", valid_paths), "wiki/concepts/beta.md")
        self.assertIsNone(resolve_wiki_link("wiki/concepts/capm.md", "https://example.com", valid_paths))


if __name__ == "__main__":
    unittest.main()
