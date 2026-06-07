from __future__ import annotations

import hashlib
import math
import posixpath
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .agent_provider import PROVIDER_CODEX, load_agent_provider_config
from .config import DomainConfig
from .mcp_registry import create_tool_registry
from .mcp_tools import WikiToolAdapter


GUI_PANEL_TITLES = ["위키 라이브러리", "문서와 Graphify", "Wiki Agent"]
GUI_ACTION_LABELS = ["raw 스캔", "새 source 요약", "pending concept 조직", "wiki lint", "maintenance 실행", "에이전트에게 질문"]
GUI_GRAPH_TYPE_LABELS = {
    "concept": "개념",
    "source": "원문",
    "answer": "답변",
    "journal": "저널",
    "index": "색인",
    "overview": "개요",
    "page": "문서",
}
GUI_PANEL_WEIGHTS = (280, 796, 364)
GUI_STYLE_COLORS = {
    "app_bg": "#e9ebef",
    "sidebar_bg": "#eef0f4",
    "document_bg": "#f7f7f5",
    "agent_bg": "#f3f5f8",
    "surface": "#ffffff",
    "border": "#d5dbe6",
    "text": "#242936",
    "muted": "#6f7785",
    "accent": "#4e7fd8",
    "accent_soft": "#dbe7ff",
}


@dataclass(frozen=True)
class AgentRouteResult:
    route: str
    status: str
    answer: str
    used_pages: list[dict[str, Any]]
    related_pages: list[dict[str, Any]]
    error: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class GuiTaskResult:
    kind: str
    ok: bool
    message: str
    refresh_pages: bool = False
    route_line: str | None = None
    error: str | None = None
    label: str = "작업"


@dataclass(frozen=True)
class GuiTaskSpec:
    key: str
    kind: str
    label: str
    pending_message: str
    task: Callable[[], str]
    refresh_pages: bool


class DirectAdapterAgentFallback:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def ask(self, query: str) -> AgentRouteResult:
        answer = self.adapter.answer_question(query)
        return _route_result_from_answer(answer, route="direct fallback")


class McpCodexAgentRoute:
    """GUI-facing route that asks through the local MCP tool registry first."""

    def __init__(
        self,
        config: DomainConfig,
        *,
        registry_factory: Callable[[DomainConfig], dict[str, Callable[..., Any]]] = create_tool_registry,
        fallback: DirectAdapterAgentFallback | None = None,
    ) -> None:
        self.config = config
        self.registry_factory = registry_factory
        self.fallback = fallback

    def ask(self, query: str) -> AgentRouteResult:
        provider = load_agent_provider_config("answer").provider
        route = "mcp/codex" if provider == PROVIDER_CODEX else "mcp/rule_based"
        try:
            registry = self.registry_factory(self.config)
            answer_tool = registry["answer_question"]
            answer = answer_tool(query)
            result = _route_result_from_answer(answer, route=route)
            if result.route == route and answer.get("fallback") and provider == PROVIDER_CODEX:
                return AgentRouteResult(
                    route="mcp/codex fallback",
                    status=result.status,
                    answer=result.answer,
                    used_pages=result.used_pages,
                    related_pages=result.related_pages,
                    error=result.error,
                    fallback_reason=result.fallback_reason,
                )
            return result
        except Exception as exc:
            if self.fallback is None:
                raise
            result = self.fallback.ask(query)
            return AgentRouteResult(
                route="direct fallback",
                status=result.status,
                answer=result.answer,
                used_pages=result.used_pages,
                related_pages=result.related_pages,
                error=str(exc),
                fallback_reason="MCP route 실행 실패로 direct adapter fallback 사용",
            )


class DesktopGuiPresenter:
    def __init__(self, adapter: Any, *, agent_route: Any | None = None) -> None:
        self.adapter = adapter
        self.agent_route = agent_route or DirectAdapterAgentFallback(adapter)

    def scan_raw_sources(self) -> str:
        result = self.adapter.scan_raw_sources()
        return (
            "raw 스캔 완료: "
            f"새 파일 {result.get('new_count', 0)}개, "
            f"변경 {result.get('changed_count', 0)}개, "
            f"무시 {result.get('ignored_count', 0)}개"
        )

    def summarize_new_sources(self) -> str:
        result = self.adapter.summarize_new_sources()
        return (
            "source 요약 완료: "
            f"요약 {result.get('summarized_count', 0)}개, "
            f"Codex {result.get('codex_used_count', 0)}개, "
            f"fallback {result.get('fallback_count', 0)}개, "
            f"검토 필요 {result.get('needs_review_count', 0)}개"
        )

    def organize_pending_sources(self) -> str:
        result = self.adapter.organize_pending_sources()
        return (
            "concept 조직 완료: "
            f"승격 {result.get('promoted_count', 0)}개, "
            f"병합 {result.get('merged_count', 0)}개, "
            f"보류 {result.get('skipped_count', result.get('dropped_count', 0))}개, "
            f"fallback {result.get('fallback_count', 0)}개"
        )

    def run_wiki_lint(self) -> str:
        result = self.adapter.run_wiki_lint()
        if result.get("ok"):
            return "wiki lint 통과"
        issues = result.get("issues", [])
        return "wiki lint 실패:\n" + "\n".join(f"- {_short_path(str(item['path']))}: {item['message']}" for item in issues)

    def run_maintenance_workflow(self) -> str:
        raw_before = _raw_snapshot(self.adapter)
        scan = self.adapter.scan_raw_sources()
        summarize = self.adapter.summarize_new_sources()
        organize = self.adapter.organize_pending_sources()
        graph = self.adapter.get_wiki_graph()
        lint = self.adapter.run_wiki_lint()
        raw_after = _raw_snapshot(self.adapter)
        return format_maintenance_report(scan, summarize, organize, lint, graph, raw_before=raw_before, raw_after=raw_after)

    def wiki_status(self) -> str:
        sources = self.adapter.list_wiki_pages(page_type="source")
        concepts = self.adapter.list_wiki_pages(page_type="concept")
        pending_count = 0
        quality_lines: list[str] = []
        for page in sources:
            content = self.adapter.read_wiki_page(page["path"])
            quality = _quality_value(content)
            if quality in {"weak", "needs_review"}:
                pending_count += 1
            quality_lines.append(f"- {page['path']}: {quality}")
        return "\n".join(
            [
                f"pending source: {pending_count}",
                f"concept pages: {len(concepts)}",
                "source quality:",
                *(quality_lines or ["- source page 없음"]),
            ]
        )

    def ask_agent(self, query: str) -> str:
        if not query.strip():
            return "질문을 입력하세요."
        result = self.agent_route.ask(query)
        lines = [
            result.answer,
            "",
            f"agent route: {result.route}",
            f"status: {result.status}",
        ]
        if result.error:
            lines.append(f"route error: {result.error}")
        if result.fallback_reason:
            lines.append(f"fallback reason: {result.fallback_reason}")

        lines.extend(["", "used pages:"])
        if result.used_pages:
            for item in result.used_pages:
                lines.append(f"- {item.get('path', '')}: {item.get('title', '')}")
        else:
            lines.append("- 없음")

        lines.extend(["", "related pages:"])
        if result.related_pages:
            for item in result.related_pages:
                lines.append(f"- {item.get('path', '')}: {item.get('title', '')}")
        else:
            lines.append("- 없음")
        return "\n".join(lines)


def create_desktop_application(config: DomainConfig) -> tuple[Any, Any]:
    deps = _load_pyside6()
    QApplication = deps["QApplication"]
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(_stylesheet())
    window = _create_desktop_window(config, deps)
    return app, window


def run_desktop_gui(config: DomainConfig) -> None:
    app, window = create_desktop_application(config)
    window.show()
    app.exec()


def build_agent_pending_message() -> str:
    return "\n".join(["답변 생성 중...", "agent route 실행 중...", "agent route: 실행 중"])


def append_agent_exchange(messages: list[dict[str, str]], query: str) -> int:
    messages.append({"role": "user", "content": query, "status": "complete"})
    messages.append({"role": "assistant", "content": build_agent_pending_message(), "status": "pending"})
    return len(messages) - 1


def replace_chat_message(messages: list[dict[str, str]], index: int, content: str, *, status: str = "complete") -> None:
    if index < 0 or index >= len(messages):
        return
    messages[index] = {**messages[index], "content": content, "status": status}


def render_chat_messages_html(messages: list[dict[str, str]]) -> str:
    rendered = "\n".join(_render_chat_message_html(message) for message in messages)
    return f"""
    <html>
    <head>
    <style>
      body {{
        margin: 0;
        padding: 10px 8px 14px 8px;
        background: {GUI_STYLE_COLORS["surface"]};
        color: {GUI_STYLE_COLORS["text"]};
        font-family: "Segoe UI", sans-serif;
        font-size: 13px;
      }}
      .message-row {{
        display: block;
        margin: 8px 0;
        width: 100%;
        clear: both;
      }}
      .message-row.user {{ text-align: right; }}
      .message-row.assistant {{ text-align: left; }}
      .bubble {{
        display: inline-block;
        max-width: 82%;
        padding: 8px 10px;
        border-radius: 8px;
        line-height: 1.48;
        text-align: left;
        white-space: normal;
      }}
      .user-bubble {{
        background: {GUI_STYLE_COLORS["accent_soft"]};
        border: 1px solid #c5d6fb;
      }}
      .assistant-bubble {{
        background: #f7f7f5;
        border: 1px solid {GUI_STYLE_COLORS["border"]};
      }}
      .message-support {{
        margin-top: 8px;
        padding-top: 6px;
        border-top: 1px solid #dfe4ed;
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 11px;
        line-height: 1.42;
      }}
      .pending {{
        color: {GUI_STYLE_COLORS["muted"]};
      }}
    </style>
    </head>
    <body>{rendered}</body>
    </html>
    """


def summarize_maintenance_status(label: str, message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return f"{label} 완료"
    if lines[0] == "Maintenance Run Report":
        status_line = next((line for line in lines if line.startswith("상태:")), "")
        return "\n".join(line for line in [f"{label} 완료", status_line] if line)
    return "\n".join(lines[:2])


def build_maintenance_pending_message() -> str:
    return "maintenance 실행 중...\nraw scan, source summary, concept organize, lint를 순서대로 실행합니다."


def build_maintenance_task_specs(presenter: Any) -> dict[str, GuiTaskSpec]:
    return {
        "scan": GuiTaskSpec(
            key="scan",
            kind="maintenance",
            label="raw 스캔",
            pending_message="raw 스캔 실행 중...",
            task=presenter.scan_raw_sources,
            refresh_pages=True,
        ),
        "summarize": GuiTaskSpec(
            key="summarize",
            kind="maintenance",
            label="새 source 요약",
            pending_message="새 source 요약 실행 중...",
            task=presenter.summarize_new_sources,
            refresh_pages=True,
        ),
        "organize": GuiTaskSpec(
            key="organize",
            kind="maintenance",
            label="pending concept 조직",
            pending_message="pending concept 조직 실행 중... concept 후보가 많으면 오래 걸릴 수 있습니다.",
            task=presenter.organize_pending_sources,
            refresh_pages=True,
        ),
        "lint": GuiTaskSpec(
            key="lint",
            kind="maintenance",
            label="wiki lint",
            pending_message="wiki lint 실행 중...",
            task=presenter.run_wiki_lint,
            refresh_pages=False,
        ),
        "maintenance": GuiTaskSpec(
            key="maintenance",
            kind="maintenance",
            label="maintenance 실행",
            pending_message=build_maintenance_pending_message(),
            task=presenter.run_maintenance_workflow,
            refresh_pages=True,
        ),
        "status": GuiTaskSpec(
            key="status",
            kind="maintenance",
            label="상태 새로고침",
            pending_message="상태 새로고침 실행 중...",
            task=presenter.wiki_status,
            refresh_pages=False,
        ),
    }


def worker_success_result(kind: str, message: str, *, refresh_pages: bool, label: str = "작업") -> GuiTaskResult:
    return GuiTaskResult(kind=kind, ok=True, message=message, refresh_pages=refresh_pages, route_line=_agent_route_line(message) if kind == "agent" else None, label=label)


def worker_failure_result(kind: str, label: str, error: BaseException, *, refresh_pages: bool = False) -> GuiTaskResult:
    message = f"{label} 실패\n오류: {error}"
    route_line = "agent route: 실패" if kind == "agent" else None
    return GuiTaskResult(kind=kind, ok=False, message=message, refresh_pages=refresh_pages, route_line=route_line, error=str(error), label=label)


def _load_pyside6() -> dict[str, Any]:
    try:
        from PySide6.QtCore import QObject, QPointF, Qt, QThread, QUrl, Signal
        from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen, QPolygonF
        from PySide6.QtWidgets import (
            QApplication,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QPushButton,
            QSizePolicy,
            QSplitter,
            QTextBrowser,
            QVBoxLayout,
            QWidget,
        )
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise RuntimeError("PySide6 desktop GUI를 실행하려면 `pip install -r requirements.txt`를 실행하세요.") from exc
        raise
    return locals()


def _create_desktop_window(config: DomainConfig, deps: dict[str, Any]) -> Any:
    QColor = deps["QColor"]
    QDesktopServices = deps["QDesktopServices"]
    QFont = deps["QFont"]
    QFrame = deps["QFrame"]
    QHBoxLayout = deps["QHBoxLayout"]
    QLabel = deps["QLabel"]
    QLineEdit = deps["QLineEdit"]
    QListWidget = deps["QListWidget"]
    QListWidgetItem = deps["QListWidgetItem"]
    QMainWindow = deps["QMainWindow"]
    QObject = deps["QObject"]
    QPointF = deps["QPointF"]
    QPainter = deps["QPainter"]
    QPen = deps["QPen"]
    QPolygonF = deps["QPolygonF"]
    QPushButton = deps["QPushButton"]
    QSizePolicy = deps["QSizePolicy"]
    QSplitter = deps["QSplitter"]
    QTextBrowser = deps["QTextBrowser"]
    Qt = deps["Qt"]
    QThread = deps["QThread"]
    QUrl = deps["QUrl"]
    Signal = deps["Signal"]
    QVBoxLayout = deps["QVBoxLayout"]
    QWidget = deps["QWidget"]

    class BackgroundTaskWorker(QObject):
        succeeded = Signal(object)
        failed = Signal(object)

        def __init__(self, kind: str, label: str, task: Callable[[], str], *, refresh_pages: bool) -> None:
            super().__init__()
            self.kind = kind
            self.label = label
            self.task = task
            self.refresh_pages = refresh_pages

        def run(self) -> None:
            try:
                self.succeeded.emit(worker_success_result(self.kind, self.task(), refresh_pages=self.refresh_pages, label=self.label))
            except Exception as exc:
                self.failed.emit(worker_failure_result(self.kind, self.label, exc))

    class MiniGraphWidget(QWidget):
        nodeClicked = Signal(str)

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("MiniGraph")
            self.setMinimumHeight(230)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._selected: dict[str, Any] = _fallback_graph_node("")
            self._related: list[dict[str, Any]] = []
            self._layout: dict[str, list[dict[str, Any]]] = {"nodes": [], "edges": []}
            self.setMouseTracking(True)

        def set_graph(self, selected: dict[str, Any], related: list[dict[str, Any]]) -> None:
            self._selected = selected
            self._related = related[:10]
            self._rebuild_layout()
            self.update()

        def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            self._rebuild_layout()
            super().resizeEvent(event)

        def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#f0f2f5"))
            painter.setPen(QPen(QColor("#c9d0dc"), 2))
            for edge in self._layout.get("edges", []):
                painter.drawLine(float(edge["x1"]), float(edge["y1"]), float(edge["x2"]), float(edge["y2"]))
            for node in self._layout.get("nodes", []):
                self._draw_node(painter, node)
            super().paintEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            node = self._node_at(event.position().x(), event.position().y())
            if node:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setToolTip(_graph_status_text(node))
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.setToolTip("")
            super().mouseMoveEvent(event)

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            if event.button() == Qt.MouseButton.LeftButton:
                node = self._node_at(event.position().x(), event.position().y())
                if node and node.get("path"):
                    self.nodeClicked.emit(str(node["path"]))
            super().mousePressEvent(event)

        def _rebuild_layout(self) -> None:
            width = max(self.width(), 520)
            height = max(self.height(), 230)
            self._layout = build_local_graph_layout(self._selected, self._related, width=width, height=height)

        def _node_at(self, x: float, y: float) -> dict[str, Any] | None:
            for node in reversed(self._layout.get("nodes", [])):
                dx = x - float(node["x"])
                dy = y - float(node["y"])
                if math.sqrt(dx * dx + dy * dy) <= float(node["r"]) + 8:
                    return node
            return None

        def _draw_node(self, painter: Any, node: dict[str, Any]) -> None:
            x = float(node["x"])
            y = float(node["y"])
            radius = float(node["r"])
            fill = QColor(str(node.get("color") or "#d5dbe6"))
            painter.setBrush(fill)
            painter.setPen(QPen(QColor("#6f7785"), 2 if node.get("selected") else 1))
            shape = str(node.get("shape") or "circle")
            if shape == "square":
                painter.drawRect(x - radius, y - radius, radius * 2, radius * 2)
            elif shape == "diamond":
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(x, y - radius),
                            QPointF(x + radius, y),
                            QPointF(x, y + radius),
                            QPointF(x - radius, y),
                        ]
                    )
                )
            elif shape == "hexagon":
                points = [
                    QPointF(x + math.cos(math.pi / 6 + math.tau * index / 6) * radius, y + math.sin(math.pi / 6 + math.tau * index / 6) * radius)
                    for index in range(6)
                ]
                painter.drawPolygon(QPolygonF(points))
            else:
                painter.drawEllipse(QPointF(x, y), radius, radius)
            painter.setPen(QColor(GUI_STYLE_COLORS["text"]))
            font = QFont("Segoe UI", 8)
            font.setBold(True)
            painter.setFont(font)
            label = str(node.get("label") or "")
            painter.drawText(int(x - 58), int(y + radius + 5), 116, 30, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

    class WikiDesktopWindow(QMainWindow):
        def __init__(self, domain_config: DomainConfig) -> None:
            super().__init__()
            self.config = domain_config
            self.adapter = WikiToolAdapter(domain_config)
            self.presenter = DesktopGuiPresenter(
                self.adapter,
                agent_route=McpCodexAgentRoute(domain_config, fallback=DirectAdapterAgentFallback(self.adapter)),
            )
            self._maintenance_task_specs = build_maintenance_task_specs(self.presenter)
            self._pages: list[dict[str, Any]] = []
            self._selected_path: str | None = None
            self._valid_paths: set[str] = set()
            self._background_tasks: list[tuple[Any, Any]] = []
            self._chat_messages: list[dict[str, str]] = []
            self._pending_agent_message_index: int | None = None
            self._agent_running = False
            self._maintenance_running = False
            self.maintenance_buttons: list[Any] = []
            self.setWindowTitle("LLM Wiki Tool v2")
            self.resize(1440, 840)
            self._build_layout()
            self.refresh_pages()

        def _build_layout(self) -> None:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setObjectName("RootSplitter")
            splitter.addWidget(self._build_sidebar())
            splitter.addWidget(self._build_document_panel())
            splitter.addWidget(self._build_agent_panel())
            splitter.setSizes(list(GUI_PANEL_WEIGHTS))
            self.setCentralWidget(splitter)

        def _build_sidebar(self) -> Any:
            panel = QFrame()
            panel.setObjectName("Sidebar")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(18, 18, 14, 18)
            layout.setSpacing(10)

            title = QLabel("LLM Wiki")
            title.setObjectName("AppTitle")
            layout.addWidget(title)
            subtitle = QLabel(GUI_PANEL_TITLES[0])
            subtitle.setObjectName("MutedLabel")
            layout.addWidget(subtitle)

            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("문서 검색")
            self.search_input.returnPressed.connect(self.refresh_pages)
            layout.addWidget(self.search_input)

            self.page_list = QListWidget()
            self.page_list.setObjectName("PageList")
            self.page_list.currentItemChanged.connect(self._on_page_selected)
            layout.addWidget(self.page_list, stretch=1)
            return panel

        def _build_document_panel(self) -> Any:
            panel = QFrame()
            panel.setObjectName("DocumentPanel")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(24, 18, 24, 18)
            layout.setSpacing(10)

            header = QLabel(GUI_PANEL_TITLES[1])
            header.setObjectName("PanelTitle")
            layout.addWidget(header)

            self.document_view = QTextBrowser()
            self.document_view.setObjectName("DocumentView")
            self.document_view.setOpenExternalLinks(False)
            self.document_view.anchorClicked.connect(self._open_document_link)
            layout.addWidget(self.document_view, stretch=1)

            graph_title = QLabel("Graphify")
            graph_title.setObjectName("PanelTitle")
            layout.addWidget(graph_title)
            self.graph_widget = MiniGraphWidget()
            self.graph_widget.nodeClicked.connect(self._select_path)
            layout.addWidget(self.graph_widget)
            self.graph_status = QLabel("graph node에 마우스를 올리면 전체 제목을 볼 수 있습니다.")
            self.graph_status.setObjectName("MutedLabel")
            layout.addWidget(self.graph_status)
            return panel

        def _build_agent_panel(self) -> Any:
            panel = QFrame()
            panel.setObjectName("AgentPanel")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(14, 18, 18, 18)
            layout.setSpacing(10)

            header = QLabel(GUI_PANEL_TITLES[2])
            header.setObjectName("PanelTitle")
            layout.addWidget(header)
            self.route_label = QLabel("agent route: 준비됨")
            self.route_label.setObjectName("RouteLabel")
            layout.addWidget(self.route_label)

            maintenance = QFrame()
            maintenance.setObjectName("MaintenanceBox")
            maintenance_layout = QVBoxLayout(maintenance)
            maintenance_layout.setContentsMargins(10, 10, 10, 10)
            maintenance_layout.setSpacing(6)
            for label, command in [
                ("raw 스캔", self._scan),
                ("새 source 요약", self._summarize),
                ("pending concept 조직", self._organize),
                ("wiki lint", self._lint),
                ("maintenance 실행", self._maintenance),
                ("상태 새로고침", self._status),
            ]:
                button = QPushButton(label)
                button.clicked.connect(command)
                self.maintenance_buttons.append(button)
                maintenance_layout.addWidget(button)
            layout.addWidget(maintenance)

            self.chat_log = QTextBrowser()
            self.chat_log.setObjectName("ChatLog")
            self.chat_log.setOpenExternalLinks(False)
            self.chat_log.setHtml(render_chat_messages_html(self._chat_messages))
            layout.addWidget(self.chat_log, stretch=1)

            self.question_input = QLineEdit()
            self.question_input.setPlaceholderText("질문을 입력하세요")
            self.question_input.returnPressed.connect(self._ask)
            ask_row = QHBoxLayout()
            ask_row.addWidget(self.question_input, stretch=1)
            self.ask_button = QPushButton("에이전트에게 질문")
            self.ask_button.setObjectName("PrimaryButton")
            self.ask_button.clicked.connect(self._ask)
            ask_row.addWidget(self.ask_button)
            layout.addLayout(ask_row)

            self.status_label = QLabel("준비됨")
            self.status_label.setObjectName("StatusLabel")
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)
            return panel

        def refresh_pages(self) -> None:
            query = self.search_input.text().strip() if hasattr(self, "search_input") else ""
            self._pages = self.adapter.search_wiki(query, limit=100) if query else self.adapter.list_wiki_pages()
            self._valid_paths = {str(page.get("path", "")) for page in self.adapter.list_wiki_pages()}
            self._render_page_list()
            if self._selected_path and self._selected_path in self._valid_paths:
                self._select_path(self._selected_path)
            elif self._pages:
                self._select_path(str(self._pages[0]["path"]))
            else:
                self.document_view.setPlainText("wiki page가 없습니다. raw 폴더에 자료를 넣고 maintenance를 실행하세요.")
                self.graph_widget.set_graph(_fallback_graph_node(""), [])

        def _render_page_list(self) -> None:
            self.page_list.clear()
            if not self._pages:
                item = QListWidgetItem("검색 결과 없음")
                item.setData(Qt.ItemDataRole.UserRole, "")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.page_list.addItem(item)
                return
            for group_title, pages in _group_pages(self._pages):
                header = QListWidgetItem(group_title)
                header.setData(Qt.ItemDataRole.UserRole, "")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor(GUI_STYLE_COLORS["muted"]))
                self.page_list.addItem(header)
                for page in pages:
                    label = f"{page.get('label') or page.get('title') or page.get('path')}"
                    item = QListWidgetItem(label)
                    item.setToolTip(str(page.get("tooltip") or page.get("title") or page.get("path")))
                    item.setData(Qt.ItemDataRole.UserRole, str(page.get("path", "")))
                    self.page_list.addItem(item)

        def _on_page_selected(self, current: Any, _previous: Any) -> None:
            if current is None:
                return
            path = current.data(Qt.ItemDataRole.UserRole)
            if path:
                self._show_page(str(path))

        def _select_path(self, path: str) -> None:
            if not path:
                return
            for index in range(self.page_list.count()):
                item = self.page_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == path:
                    self.page_list.setCurrentItem(item)
                    return
            self._show_page(path)

        def _show_page(self, path: str) -> None:
            self._selected_path = path
            content = self.adapter.read_wiki_page(path)
            self.document_view.setMarkdown(content)
            graph = self.adapter.get_wiki_graph()
            node_by_path = {node["path"]: node for node in graph.get("nodes", [])}
            selected = node_by_path.get(path, _fallback_graph_node(path))
            related = self.adapter.get_related_pages(path, depth=1)
            self.graph_widget.set_graph(selected, related)
            self.graph_status.setText("관련 문서 없음" if not related else "node를 클릭하면 해당 wiki page로 이동합니다.")

        def _open_document_link(self, url: Any) -> None:
            href = url.toString()
            target = resolve_wiki_link(self._selected_path or "", href, self._valid_paths)
            if target:
                self._select_path(target)
            else:
                QDesktopServices.openUrl(QUrl(href))

        def _scan(self) -> None:
            self._run_maintenance_task("scan")

        def _summarize(self) -> None:
            self._run_maintenance_task("summarize")

        def _organize(self) -> None:
            self._run_maintenance_task("organize")

        def _lint(self) -> None:
            self._run_maintenance_task("lint")

        def _maintenance(self) -> None:
            self._run_maintenance_task("maintenance")

        def _status(self) -> None:
            self._run_maintenance_task("status")

        def _run_maintenance_task(self, key: str) -> None:
            if self._maintenance_running:
                return
            spec = self._maintenance_task_specs[key]
            self._maintenance_running = True
            self._set_maintenance_enabled(False)
            self._set_status_text(spec.pending_message)
            self._start_background_task(
                kind=spec.kind,
                label=spec.label,
                task=spec.task,
                refresh_pages=spec.refresh_pages,
            )

        def _ask(self) -> None:
            if self._agent_running:
                return
            query = self.question_input.text().strip()
            if not query.strip():
                self._set_status_text(self.presenter.ask_agent(query))
                return
            self.question_input.clear()
            self._agent_running = True
            self._set_agent_enabled(False)
            self._pending_agent_message_index = append_agent_exchange(self._chat_messages, query)
            self.route_label.setText(_agent_route_line(build_agent_pending_message()))
            self._render_chat_log()
            self._start_background_task(
                kind="agent",
                label="에이전트 질문",
                task=lambda: self.presenter.ask_agent(query),
                refresh_pages=False,
            )

        def _start_background_task(self, *, kind: str, label: str, task: Callable[[], str], refresh_pages: bool) -> None:
            thread = QThread(self)
            worker = BackgroundTaskWorker(kind, label, task, refresh_pages=refresh_pages)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.succeeded.connect(self._on_background_task_done)
            worker.failed.connect(self._on_background_task_done)
            worker.succeeded.connect(thread.quit)
            worker.failed.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: self._cleanup_background_task(thread, worker))
            self._background_tasks.append((thread, worker))
            thread.start()

        def _on_background_task_done(self, result: GuiTaskResult) -> None:
            if result.kind == "agent":
                self._agent_running = False
                self._set_agent_enabled(True)
                self.route_label.setText(result.route_line or _agent_route_line(result.message))
                if self._pending_agent_message_index is not None:
                    replace_chat_message(
                        self._chat_messages,
                        self._pending_agent_message_index,
                        result.message,
                        status="complete" if result.ok else "failed",
                    )
                    self._pending_agent_message_index = None
                else:
                    self._chat_messages.append({"role": "assistant", "content": result.message, "status": "complete" if result.ok else "failed"})
                self._render_chat_log()
            elif result.kind == "maintenance":
                self._maintenance_running = False
                self._set_maintenance_enabled(True)
                self._set_status_text(summarize_maintenance_status(result.label, result.message))
            if result.refresh_pages:
                self.refresh_pages()

        def _cleanup_background_task(self, thread: Any, worker: Any) -> None:
            try:
                self._background_tasks.remove((thread, worker))
            except ValueError:
                pass

        def _set_agent_enabled(self, enabled: bool) -> None:
            self.question_input.setEnabled(enabled)
            self.ask_button.setEnabled(enabled)

        def _set_maintenance_enabled(self, enabled: bool) -> None:
            for button in self.maintenance_buttons:
                button.setEnabled(enabled)

        def _set_status_text(self, message: str) -> None:
            self.status_label.setText(message)

        def _render_chat_log(self) -> None:
            self.chat_log.setHtml(render_chat_messages_html(self._chat_messages))
            scrollbar = self.chat_log.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    return WikiDesktopWindow(config)


def _route_result_from_answer(answer: dict[str, Any], *, route: str) -> AgentRouteResult:
    fallback = bool(answer.get("fallback"))
    status = str(answer.get("status") or ("fallback" if fallback else "ok"))
    if fallback and answer.get("codex_status"):
        status = str(answer["codex_status"])
    return AgentRouteResult(
        route=route,
        status=status,
        answer=str(answer.get("answer") or ""),
        used_pages=list(answer.get("used_pages") or []),
        related_pages=list(answer.get("related_pages") or []),
        fallback_reason=str(answer["fallback_reason"]) if answer.get("fallback_reason") else None,
        error=str(answer["error"]) if answer.get("error") else None,
    )


def _agent_route_line(message: str) -> str:
    for line in message.splitlines():
        if line.startswith("agent route:"):
            return line
    return "agent route: 알 수 없음"


def _plain_text_html(message: str) -> str:
    return "<div class='agent-message'>" + "<br>".join(escape(line) for line in message.splitlines()) + "</div>"


def _render_chat_message_html(message: dict[str, str]) -> str:
    role = message.get("role", "assistant")
    status = message.get("status", "complete")
    content = message.get("content", "")
    body, support = _split_assistant_support(content) if role == "assistant" else (content, "")
    role_class = "user" if role == "user" else "assistant"
    bubble_class = "user-bubble" if role == "user" else "assistant-bubble"
    status_class = " pending" if status == "pending" else ""
    html = [
        f'<div class="message-row {role_class}">',
        f'<div class="bubble {bubble_class}{status_class}">',
        _text_to_html(body),
    ]
    if support:
        html.append(f'<div class="message-support">{_text_to_html(support)}</div>')
    html.extend(["</div>", "</div>"])
    return "".join(html)


def _split_assistant_support(content: str) -> tuple[str, str]:
    markers = ["\nused pages:", "\nrelated pages:"]
    positions = [content.find(marker) for marker in markers if content.find(marker) >= 0]
    if not positions:
        return content, ""
    split_at = min(positions)
    return content[:split_at].rstrip(), content[split_at:].strip()


def _text_to_html(text: str) -> str:
    return "<br>".join(escape(line) for line in text.splitlines())


def _stylesheet() -> str:
    return f"""
    QMainWindow {{
        background: {GUI_STYLE_COLORS["app_bg"]};
        color: {GUI_STYLE_COLORS["text"]};
    }}
    QFrame#Sidebar {{
        background: {GUI_STYLE_COLORS["sidebar_bg"]};
        border-right: 1px solid {GUI_STYLE_COLORS["border"]};
    }}
    QFrame#DocumentPanel {{
        background: {GUI_STYLE_COLORS["document_bg"]};
    }}
    QFrame#AgentPanel {{
        background: {GUI_STYLE_COLORS["agent_bg"]};
        border-left: 1px solid {GUI_STYLE_COLORS["border"]};
    }}
    QLabel#AppTitle {{
        font-family: "Segoe UI";
        font-size: 24px;
        font-weight: 700;
        color: {GUI_STYLE_COLORS["text"]};
    }}
    QLabel#PanelTitle {{
        font-family: "Segoe UI";
        font-size: 15px;
        font-weight: 700;
        color: {GUI_STYLE_COLORS["text"]};
    }}
    QLabel#MutedLabel {{
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 12px;
    }}
    QLabel#RouteLabel {{
        color: {GUI_STYLE_COLORS["accent"]};
        background: {GUI_STYLE_COLORS["accent_soft"]};
        border: 1px solid #bdd1fb;
        border-radius: 7px;
        padding: 6px 8px;
        font-weight: 600;
    }}
    QLineEdit {{
        background: {GUI_STYLE_COLORS["surface"]};
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 7px;
        padding: 8px 9px;
        color: {GUI_STYLE_COLORS["text"]};
        selection-background-color: {GUI_STYLE_COLORS["accent"]};
    }}
    QPushButton {{
        background: {GUI_STYLE_COLORS["surface"]};
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 7px;
        padding: 8px 10px;
        color: {GUI_STYLE_COLORS["text"]};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: #f6f8fc;
        border-color: #b8c6dd;
    }}
    QPushButton#PrimaryButton {{
        background: {GUI_STYLE_COLORS["accent"]};
        color: white;
        border-color: {GUI_STYLE_COLORS["accent"]};
    }}
    QListWidget#PageList {{
        background: {GUI_STYLE_COLORS["surface"]};
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 8px;
        padding: 6px;
        outline: 0;
    }}
    QListWidget#PageList::item {{
        padding: 8px 8px;
        border-radius: 6px;
    }}
    QListWidget#PageList::item:selected {{
        background: {GUI_STYLE_COLORS["accent_soft"]};
        color: {GUI_STYLE_COLORS["text"]};
    }}
    QTextBrowser#DocumentView {{
        background: {GUI_STYLE_COLORS["surface"]};
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 8px;
        padding: 18px;
        font-family: "Segoe UI";
        font-size: 14px;
        line-height: 1.48;
    }}
    QTextBrowser#ChatLog {{
        background: {GUI_STYLE_COLORS["surface"]};
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 8px;
        padding: 0;
        font-family: "Segoe UI";
        font-size: 13px;
    }}
    QLabel#StatusLabel {{
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 11px;
        padding: 2px 2px 0 2px;
    }}
    QFrame#MaintenanceBox {{
        background: #edf1f7;
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 8px;
    }}
    QWidget#MiniGraph {{
        background: #f0f2f5;
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 8px;
    }}
    QSplitter::handle {{
        background: {GUI_STYLE_COLORS["border"]};
        width: 1px;
    }}
    """


def resolve_wiki_link(current_path: str, href: str, valid_paths: set[str]) -> str | None:
    if not href or href.startswith("#"):
        return None
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme not in {"file"}:
        return None
    candidate = unquote(parsed.path or href).replace("\\", "/")
    if candidate in valid_paths:
        return candidate
    if current_path:
        base_dir = PurePosixPath(current_path).parent.as_posix()
        relative = posixpath.normpath(posixpath.join(base_dir, candidate))
        if relative in valid_paths:
            return relative
    trimmed = candidate.lstrip("/")
    if trimmed in valid_paths:
        return trimmed
    return None


def _group_pages(pages: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    order = [
        ("sources", "source"),
        ("concepts", "concept"),
        ("answers", "answer"),
        ("journal", "journal"),
        ("index", "index"),
        ("overview", "overview"),
    ]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        buckets.setdefault(str(page.get("type", "page")), []).append(page)
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    for label, page_type in order:
        items = buckets.pop(page_type, [])
        if items:
            grouped.append((label, items))
    for page_type, items in sorted(buckets.items()):
        grouped.append((page_type, items))
    return grouped


def _quality_value(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("- quality:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def format_maintenance_report(
    scan: dict[str, Any],
    summarize: dict[str, Any],
    organize: dict[str, Any],
    lint: dict[str, Any],
    graph: dict[str, Any],
    *,
    raw_before: dict[str, str] | None = None,
    raw_after: dict[str, str] | None = None,
) -> str:
    lint_issues = lint.get("issues", []) or []
    source_fallback = int(summarize.get("fallback_count", 0) or 0)
    concept_fallback = int(organize.get("fallback_count", 0) or 0)
    fallback_count = source_fallback + concept_fallback
    raw_integrity = _raw_integrity_status(raw_before, raw_after)
    lint_ok = bool(lint.get("ok"))

    if raw_integrity == "raw 변경 감지" or not lint_ok:
        status = "실패"
    elif fallback_count > 0:
        status = "fallback 포함 성공"
    else:
        status = "성공"

    scanned_count = int(scan.get("scanned_count", 0) or 0)
    new_count = int(scan.get("new_count", 0) or 0)
    changed_count = int(scan.get("changed_count", 0) or 0)
    ignored_count = int(scan.get("ignored_count", 0) or 0)
    unchanged_count = max(scanned_count - new_count - changed_count, 0)
    lint_status = "통과" if lint_ok else "실패"
    fallback_status = "fallback 발생" if fallback_count else "fallback 없음"

    lines = [
        "Maintenance Run Report",
        "전체 동기화 완료",
        f"상태: {status}",
        f"raw scan: 신규 {new_count}개, 변경 {changed_count}개, 유지 {unchanged_count}개, 제외 {ignored_count}개",
        (
            "source summary: "
            f"provider {summarize.get('provider', 'rule_based')}, "
            f"요약 {summarize.get('summarized_count', 0)}개, "
            f"Codex {summarize.get('codex_used_count', 0)}개, "
            f"fallback {source_fallback}개, "
            f"검토 필요 {summarize.get('needs_review_count', 0)}개"
        ),
        (
            "concept organize: "
            f"provider {organize.get('provider', 'rule_based')}, "
            f"승격 {organize.get('promoted_count', 0)}개, "
            f"병합 {organize.get('merged_count', 0)}개, "
            f"건너뜀 {organize.get('skipped_count', 0)}개, "
            f"Codex {organize.get('codex_used_count', 0)}개, "
            f"fallback {concept_fallback}개"
        ),
        f"lint: {lint_status}, issue {len(lint_issues)}개",
        f"안전성: {raw_integrity}, lint {lint_status}, {fallback_status}",
        (
            "산출물: "
            f"source {int(summarize.get('summarized_count', 0) or 0) + int(summarize.get('needs_review_count', 0) or 0)}개, "
            f"concept 변경 {int(organize.get('promoted_count', 0) or 0) + int(organize.get('merged_count', 0) or 0)}개, "
            f"graph node {len(graph.get('nodes', []) or [])}개, "
            f"edge {len(graph.get('edges', []) or [])}개"
        ),
    ]

    causes = _maintenance_fallback_reasons(source_fallback, concept_fallback)
    if raw_integrity == "raw 변경 감지":
        causes.append("raw 파일 해시가 동기화 실행 전후로 달라졌습니다.")
    if causes:
        lines.extend(["", "원인:", *(f"- {cause}" for cause in causes)])

    if lint_issues:
        lines.extend(["", "문제:", *(_format_lint_issue(issue) for issue in lint_issues[:5])])

    return "\n".join(lines)


def _maintenance_fallback_reasons(source_fallback: int, concept_fallback: int) -> list[str]:
    reasons: list[str] = []
    if source_fallback:
        reasons.append(f"source summary fallback {source_fallback}개: Codex draft 검증 실패 또는 실행 오류로 rule-based 요약 사용")
    if concept_fallback:
        reasons.append(f"concept organize fallback {concept_fallback}개: Codex draft 검증 실패 또는 실행 오류로 rule-based 조직 사용")
    return reasons


def _format_lint_issue(issue: dict[str, Any]) -> str:
    path = _short_path(str(issue.get("path", "")))
    message = str(issue.get("message", "")).strip()
    if path and message:
        return f"- {path}: {message}"
    if path:
        return f"- {path}"
    return f"- {message or '메시지 없는 lint issue'}"


def _short_path(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _raw_integrity_status(raw_before: dict[str, str] | None, raw_after: dict[str, str] | None) -> str:
    if raw_before is None or raw_after is None:
        return "raw 불변성 확인 불가"
    return "raw 변경 없음" if raw_before == raw_after else "raw 변경 감지"


def _raw_snapshot(adapter: Any) -> dict[str, str] | None:
    raw_dir = getattr(getattr(adapter, "config", None), "raw_dir", None)
    if not raw_dir:
        return None
    root = Path(raw_dir)
    if not root.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = _sha256(path)
    return snapshot


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _graph_item_label(item: dict[str, Any]) -> str:
    page_type = str(item.get("type", "page"))
    type_label = GUI_GRAPH_TYPE_LABELS.get(page_type, page_type)
    label = str(item.get("label") or item.get("title") or item.get("path") or "Untitled")
    tooltip = str(item.get("tooltip") or item.get("title") or "")
    if tooltip and tooltip != label:
        return f"{type_label} · {label} - {tooltip}"
    return f"{type_label} · {label}"


def _graph_status_text(item: dict[str, Any]) -> str:
    page_type = str(item.get("type", "page"))
    type_label = GUI_GRAPH_TYPE_LABELS.get(page_type, page_type)
    title = str(item.get("tooltip") or item.get("title") or item.get("label") or item.get("path") or "Untitled")
    path = str(item.get("path") or "")
    if path:
        return f"{type_label} · {title} · {path}"
    return f"{type_label} · {title}"


def build_local_graph_layout(
    selected: dict[str, Any],
    related: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, list[dict[str, Any]]]:
    center_x = width / 2
    center_y = height / 2
    radius_x = max(width * 0.34, 130)
    radius_y = max(height * 0.28, 54)
    selected_node = _layout_node(selected, center_x, center_y, selected=True)
    nodes = [selected_node]
    edges: list[dict[str, Any]] = []
    count = max(len(related), 1)
    for index, page in enumerate(related[:10]):
        angle = (math.tau * index) / count
        x = center_x + math.cos(angle) * radius_x
        y = center_y + math.sin(angle) * radius_y
        node = _layout_node(page, x, y, selected=False)
        nodes.append(node)
        edges.append({"from": selected_node["path"], "to": node["path"], "x1": center_x, "y1": center_y, "x2": x, "y2": y})
    return {"nodes": nodes, "edges": edges}


def _layout_node(page: dict[str, Any], x: float, y: float, *, selected: bool) -> dict[str, Any]:
    style = page.get("style") or {}
    return {
        "path": str(page.get("path", "")),
        "type": str(page.get("type", "page")),
        "label": str(page.get("label") or page.get("title") or page.get("path") or "Untitled"),
        "tooltip": str(page.get("tooltip") or page.get("title") or page.get("path") or ""),
        "shape": str(style.get("shape", "circle")),
        "color": str(style.get("color", "#d5dbe6")),
        "x": x,
        "y": y,
        "r": 24 if selected else 16,
        "selected": selected,
    }


def _fallback_graph_node(path: str) -> dict[str, Any]:
    return {"path": path, "type": "page", "label": path.rsplit("/", 1)[-1], "tooltip": path, "style": {"color": "#d5dbe6", "shape": "circle"}}
