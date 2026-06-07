from enum import IntFlag
import tempfile
import unittest
from pathlib import Path

from wiki_tool.desktop_gui import (
    GUI_ACTION_LABELS,
    GUI_GRAPH_TYPE_LABELS,
    GUI_PANEL_TITLES,
    GUI_PANEL_WEIGHTS,
    GUI_STYLE_COLORS,
    AgentRouteResult,
    DesktopGuiPresenter,
    DirectAdapterAgentFallback,
    DomainCreationRequest,
    GuiTaskSpec,
    GuiTaskResult,
    McpCodexAgentRoute,
    _agent_route_line,
    append_agent_exchange,
    build_agent_pending_message,
    build_maintenance_pending_message,
    create_gui_user_domain,
    domain_controls_enabled,
    build_maintenance_task_specs,
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
from wiki_tool.user_domain import create_user_domain


class FakeAdapter:
    def __init__(self):
        self.calls = []

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
        }

    def run_wiki_lint(self):
        self.calls.append("lint")
        return {"ok": True, "issues": []}

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

    def test_agent_route_line_extracts_status_for_gui_label(self):
        self.assertEqual(_agent_route_line("answer\nagent route: mcp/codex\nstatus: ok"), "agent route: mcp/codex")
        self.assertEqual(_agent_route_line("answer only"), "agent route: 알 수 없음")

    def test_agent_worker_pending_message_is_immediate_and_route_visible(self):
        message = build_agent_pending_message()

        self.assertIn("답변 생성 중", message)
        self.assertIn("agent route: 실행 중", message)

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

        status = presenter.run_maintenance_workflow()

        self.assertIn("Maintenance Run Report", status)
        self.assertIn("상태: fallback 포함 성공", status)
        self.assertIn("raw scan: 신규 1개, 변경 0개, 유지 0개, 제외 0개", status)
        self.assertIn("source summary: provider codex, 요약 1개, Codex 1개, fallback 0개, 검토 필요 0개", status)
        self.assertIn("concept organize: provider codex, 승격 1개, 병합 0개, 건너뜀 0개, Codex 1개, fallback 1개", status)
        self.assertIn("lint: 통과, issue 0개", status)
        self.assertIn("안전성: raw 불변성 확인 불가, lint 통과, fallback 발생", status)
        self.assertIn("산출물: source 1개, concept 변경 1개, graph node 2개, edge 0개", status)
        self.assertIn("원인:", status)
        self.assertIn("concept organize fallback 1개", status)
        self.assertEqual(adapter.calls, ["scan", "summarize", "organize", "graph", "lint"])

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
        self.assertIn("concept organize: provider codex, 승격 4개, 병합 2개", status)
        self.assertIn("fallback 없음", status)
        self.assertNotIn("{", status)
        self.assertNotIn("}", status)

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
