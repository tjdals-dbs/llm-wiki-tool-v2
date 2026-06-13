from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from .config import DomainConfig, load_domain_config
from .desktop_chat import (
    append_agent_exchange,
    build_agent_pending_message,
    render_chat_messages_html,
    replace_chat_message,
)
from .desktop_domain import (
    DomainCreationRequest,
    GuiDomainCreationResult,
    RawFolderOpenResult,
    create_gui_user_domain,
    domain_controls_enabled,
    open_domain_raw_folder,
)
from .desktop_graph import _fallback_graph_node, _graph_item_label, _graph_status_text, build_local_graph_layout
from .desktop_navigation import (
    PAGE_NAVIGATION_CHILD_INDENT,
    build_page_navigation_items,
    navigation_item_flags,
    resolve_wiki_link,
)
from .desktop_presenter import (
    AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE,
    AgentRouteResult,
    AgentWorkflowResult,
    DesktopGuiPresenter,
    DirectAdapterAgentFallback,
    McpCodexAgentRoute,
    _agent_route_line,
    agent_provider_detail_toggle_label,
    build_agent_provider_panel_status,
    format_maintenance_report,
    toggle_agent_provider_detail_visible,
)
from .desktop_runtime import (
    ADVANCED_MAINTENANCE_DEFAULT_VISIBLE,
    PRIMARY_MAINTENANCE_TASK_KEY,
    DomainRuntime,
    GuiTaskResult,
    GuiTaskSpec,
    advanced_maintenance_default_visible,
    advanced_maintenance_toggle_label,
    build_domain_runtime,
    build_maintenance_pending_message,
    build_maintenance_task_specs,
    create_background_task_worker_class,
    maintenance_controls_enabled,
    primary_maintenance_task_spec,
    summarize_maintenance_status,
    toggle_advanced_maintenance_visible,
    worker_failure_result,
    worker_success_result,
)
from .desktop_styles import (
    GUI_ACTION_LABELS,
    GUI_GRAPH_TYPE_LABELS,
    GUI_PANEL_TITLES,
    GUI_PANEL_WEIGHTS,
    GUI_STYLE_COLORS,
    configure_status_bar,
    configure_status_label,
    set_elided_status_text,
    stylesheet as _stylesheet,
)
from .mcp_tools import WikiToolAdapter
from .user_domain import UserDomainInitError, discover_domain_files, domain_display_name


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _load_pyside6() -> dict[str, Any]:
    try:
        from PySide6.QtCore import QObject, QPointF, Qt, QThread, QUrl, Signal
        from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
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
    QComboBox = deps["QComboBox"]
    QDialog = deps["QDialog"]
    QDialogButtonBox = deps["QDialogButtonBox"]
    QFormLayout = deps["QFormLayout"]
    QFrame = deps["QFrame"]
    QHBoxLayout = deps["QHBoxLayout"]
    QLabel = deps["QLabel"]
    QLineEdit = deps["QLineEdit"]
    QListWidget = deps["QListWidget"]
    QListWidgetItem = deps["QListWidgetItem"]
    QMainWindow = deps["QMainWindow"]
    QMessageBox = deps["QMessageBox"]
    QIcon = deps["QIcon"]
    QObject = deps["QObject"]
    QPointF = deps["QPointF"]
    QPainter = deps["QPainter"]
    QPen = deps["QPen"]
    QPixmap = deps["QPixmap"]
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

    BackgroundTaskWorker = create_background_task_worker_class(QObject, Signal)

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

    def _navigation_marker_icon(marker: dict[str, str]) -> Any:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(str(marker.get("color") or GUI_STYLE_COLORS["muted"]))
        painter.setBrush(color)
        painter.setPen(QPen(color, 1))
        shape = str(marker.get("shape") or "circle")
        if shape == "square":
            painter.drawRect(4, 4, 8, 8)
        elif shape == "hexagon":
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(8, 2),
                        QPointF(13, 5),
                        QPointF(13, 11),
                        QPointF(8, 14),
                        QPointF(3, 11),
                        QPointF(3, 5),
                    ]
                )
            )
        else:
            painter.drawEllipse(4, 4, 8, 8)
        painter.end()
        return QIcon(pixmap)

    class NewDomainDialog(QDialog):
        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("새 도메인")
            self.setModal(True)
            layout = QVBoxLayout(self)
            form = QFormLayout()
            self.name_input = QLineEdit()
            self.name_input.setPlaceholderText("예: 내 금융 위키")
            self.slug_input = QLineEdit()
            self.slug_input.setPlaceholderText("예: finance-private")
            self.description_input = QLineEdit()
            self.description_input.setPlaceholderText("선택: 도메인 설명")
            self.disclaimer_input = QLineEdit()
            self.disclaimer_input.setPlaceholderText("선택: 안내 문구")
            form.addRow("도메인 이름", self.name_input)
            form.addRow("slug", self.slug_input)
            form.addRow("설명", self.description_input)
            form.addRow("안내 문구", self.disclaimer_input)
            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def request(self) -> DomainCreationRequest:
            return DomainCreationRequest(
                name=self.name_input.text().strip(),
                slug=self.slug_input.text().strip(),
                description=self.description_input.text().strip(),
                disclaimer=self.disclaimer_input.text().strip(),
            )

    class WikiDesktopWindow(QMainWindow):
        def __init__(self, domain_config: DomainConfig) -> None:
            super().__init__()
            runtime = build_domain_runtime(domain_config)
            self.config = runtime.config
            self.adapter = runtime.adapter
            self.presenter = runtime.presenter
            self._maintenance_task_specs = runtime.maintenance_task_specs
            self._domain_files: list[Path] = []
            self._pages: list[dict[str, Any]] = []
            self._selected_path: str | None = None
            self._valid_paths: set[str] = set()
            self._background_tasks: list[tuple[Any, Any]] = []
            self._chat_messages: list[dict[str, str]] = []
            self._pending_agent_message_index: int | None = None
            self._agent_running = False
            self._maintenance_running = False
            self._full_status_message = "준비됨"
            self._agent_provider_detail_visible = AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE
            self.maintenance_buttons: list[Any] = []
            self.setWindowTitle("LLM Wiki Tool v2")
            self.resize(1440, 840)
            self._build_layout()
            self.refresh_domain_options()
            self.refresh_pages()

        def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            super().resizeEvent(event)
            if hasattr(self, "status_label"):
                self._refresh_status_text_elision()
            if hasattr(self, "agent_provider_summary_label"):
                self._refresh_agent_provider_status()

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

            self.domain_combo = QComboBox()
            self.domain_combo.setObjectName("DomainCombo")
            layout.addWidget(self.domain_combo)
            domain_row = QHBoxLayout()
            self.domain_refresh_button = QPushButton("새로고침")
            self.domain_refresh_button.clicked.connect(self.refresh_domain_options)
            self.domain_switch_button = QPushButton("도메인 전환")
            self.domain_switch_button.clicked.connect(self._switch_selected_domain)
            self.new_domain_button = QPushButton("새 도메인")
            self.new_domain_button.clicked.connect(self._open_new_domain_dialog)
            domain_row.addWidget(self.domain_refresh_button)
            domain_row.addWidget(self.domain_switch_button)
            domain_row.addWidget(self.new_domain_button)
            layout.addLayout(domain_row)
            self.raw_folder_button = QPushButton("raw 폴더 열기")
            self.raw_folder_button.clicked.connect(self._open_raw_folder)
            layout.addWidget(self.raw_folder_button)

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

            provider_row = QHBoxLayout()
            provider_row.setContentsMargins(0, 0, 0, 0)
            provider_row.setSpacing(6)
            self.agent_provider_summary_label = QLabel("")
            self.agent_provider_summary_label.setObjectName("AgentProviderSummary")
            configure_status_label(self.agent_provider_summary_label, height=24)
            provider_row.addWidget(self.agent_provider_summary_label, stretch=1)
            self.agent_provider_detail_toggle = QPushButton(agent_provider_detail_toggle_label(self._agent_provider_detail_visible))
            self.agent_provider_detail_toggle.setObjectName("InlineToggleButton")
            self.agent_provider_detail_toggle.clicked.connect(self._toggle_agent_provider_detail)
            provider_row.addWidget(self.agent_provider_detail_toggle)
            layout.addLayout(provider_row)

            self.agent_provider_detail_label = QLabel("")
            self.agent_provider_detail_label.setObjectName("AgentProviderDetail")
            self.agent_provider_detail_label.setWordWrap(True)
            self.agent_provider_detail_label.setVisible(self._agent_provider_detail_visible)
            layout.addWidget(self.agent_provider_detail_label)
            self._refresh_agent_provider_status()

            maintenance = QFrame()
            maintenance.setObjectName("MaintenanceBox")
            maintenance_layout = QVBoxLayout(maintenance)
            maintenance_layout.setContentsMargins(10, 10, 10, 10)
            maintenance_layout.setSpacing(6)
            self.update_wiki_button = QPushButton("위키 업데이트")
            self.update_wiki_button.setObjectName("PrimaryButton")
            self.update_wiki_button.clicked.connect(lambda: self._run_maintenance_task(PRIMARY_MAINTENANCE_TASK_KEY))
            self.maintenance_buttons.append(self.update_wiki_button)
            maintenance_layout.addWidget(self.update_wiki_button)

            self.advanced_maintenance_toggle = QPushButton(advanced_maintenance_toggle_label(advanced_maintenance_default_visible()))
            self.advanced_maintenance_toggle.clicked.connect(self._toggle_advanced_maintenance)
            self.maintenance_buttons.append(self.advanced_maintenance_toggle)
            maintenance_layout.addWidget(self.advanced_maintenance_toggle)

            self.advanced_maintenance_box = QFrame()
            self.advanced_maintenance_box.setVisible(advanced_maintenance_default_visible())
            advanced_layout = QVBoxLayout(self.advanced_maintenance_box)
            advanced_layout.setContentsMargins(0, 4, 0, 0)
            advanced_layout.setSpacing(6)
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
                advanced_layout.addWidget(button)
            maintenance_layout.addWidget(self.advanced_maintenance_box)
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

            self.status_bar = QFrame()
            self.status_bar.setObjectName("StatusBar")
            configure_status_bar(self.status_bar)
            status_layout = QHBoxLayout(self.status_bar)
            status_layout.setContentsMargins(8, 0, 8, 0)
            status_layout.setSpacing(0)
            self.status_label = QLabel("준비됨")
            self.status_label.setObjectName("StatusLabel")
            configure_status_label(self.status_label)
            status_layout.addWidget(self.status_label, stretch=1)
            self._refresh_status_text_elision()
            layout.addWidget(self.status_bar)
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

        def refresh_domain_options(self) -> None:
            if self._agent_running or self._maintenance_running:
                self._set_status_text("작업 중에는 도메인 목록을 새로고침할 수 없습니다.")
                return
            current_domain = self._current_domain_file()
            self._domain_files = discover_domain_files(PROJECT_ROOT, current_domain=current_domain)
            self.domain_combo.blockSignals(True)
            self.domain_combo.clear()
            selected_index = 0
            for index, domain_file in enumerate(self._domain_files):
                self.domain_combo.addItem(domain_display_name(domain_file), str(domain_file))
                if domain_file == current_domain:
                    selected_index = index
            if self._domain_files:
                self.domain_combo.setCurrentIndex(selected_index)
            self.domain_combo.blockSignals(False)

        def _current_domain_file(self) -> Path:
            return (self.config.root / "domain.yml").resolve()

        def _switch_selected_domain(self) -> None:
            if self._agent_running or self._maintenance_running:
                self._set_status_text("작업 중에는 도메인을 전환할 수 없습니다.")
                return
            domain_value = self.domain_combo.currentData(Qt.ItemDataRole.UserRole)
            if not domain_value:
                self._set_status_text("전환할 도메인이 없습니다.")
                return
            domain_file = Path(str(domain_value)).resolve()
            if domain_file == self._current_domain_file():
                self._set_status_text(f"이미 선택된 도메인입니다: {domain_display_name(domain_file)}")
                return
            try:
                self._apply_domain_config(load_domain_config(domain_file))
            except Exception as exc:
                self._set_status_text(f"도메인 전환 실패: {exc}")

        def _open_new_domain_dialog(self) -> None:
            if self._agent_running or self._maintenance_running:
                self._set_status_text("작업 중에는 새 도메인을 만들 수 없습니다.")
                return
            dialog = NewDomainDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                result = create_gui_user_domain(PROJECT_ROOT, dialog.request())
            except UserDomainInitError as exc:
                self._show_domain_error(str(exc))
                return
            except Exception as exc:
                self._show_domain_error(f"도메인 생성 실패: {exc}")
                return
            self._apply_domain_config(result.config, status_message=result.message)

        def _show_domain_error(self, message: str) -> None:
            self._set_status_text(message)
            QMessageBox.warning(self, "도메인 생성 실패", message)

        def _open_raw_folder(self) -> None:
            result = open_domain_raw_folder(self.config)
            self._set_status_text(result.message)
            if not result.ok:
                QMessageBox.warning(self, "raw 폴더 열기 실패", result.message)

        def _apply_domain_config(self, config: DomainConfig, *, status_message: str | None = None) -> None:
            runtime = build_domain_runtime(config)
            self.config = runtime.config
            self.adapter = runtime.adapter
            self.presenter = runtime.presenter
            self._maintenance_task_specs = runtime.maintenance_task_specs
            self._pages = []
            self._selected_path = None
            self._valid_paths = set()
            self._chat_messages = []
            self._pending_agent_message_index = None
            self.search_input.clear()
            self.route_label.setText("agent route: 준비됨")
            self._agent_provider_detail_visible = AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE
            self._refresh_agent_provider_status()
            self._set_status_text(status_message or f"도메인 전환 완료: {config.name} ({config.slug})")
            self._render_chat_log()
            self.refresh_domain_options()
            self.refresh_pages()

        def _render_page_list(self) -> None:
            self.page_list.clear()
            if not self._pages:
                item = QListWidgetItem("검색 결과 없음")
                item.setData(Qt.ItemDataRole.UserRole, "")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.page_list.addItem(item)
                return
            header_font = QFont("Segoe UI", 10)
            header_font.setBold(True)
            page_font = QFont("Segoe UI", 9)
            for nav_item in build_page_navigation_items(self._pages):
                if nav_item["kind"] == "header":
                    header = QListWidgetItem(str(nav_item["title"]))
                    header.setData(Qt.ItemDataRole.UserRole, "")
                    header.setFlags(navigation_item_flags(nav_item, Qt.ItemFlag))
                    header.setFont(header_font)
                    header.setForeground(QColor(GUI_STYLE_COLORS["text"]))
                    header.setIcon(_navigation_marker_icon(nav_item.get("marker") or {}))
                    self.page_list.addItem(header)
                    continue
                item = QListWidgetItem(PAGE_NAVIGATION_CHILD_INDENT + str(nav_item["title"]))
                item.setToolTip(str(nav_item.get("tooltip") or nav_item.get("path") or nav_item["title"]))
                item.setData(Qt.ItemDataRole.UserRole, str(nav_item.get("path", "")))
                item.setFlags(navigation_item_flags(nav_item, Qt.ItemFlag))
                item.setFont(page_font)
                item.setForeground(QColor(GUI_STYLE_COLORS["text"]))
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
            self._update_domain_controls_enabled()
            self._set_status_text(spec.pending_message)
            self._start_background_task(
                kind=spec.kind,
                label=spec.label,
                task=spec.task,
                refresh_pages=spec.refresh_pages,
            )

        def _toggle_advanced_maintenance(self) -> None:
            visible = toggle_advanced_maintenance_visible(self.advanced_maintenance_box.isVisible())
            self.advanced_maintenance_box.setVisible(visible)
            self.advanced_maintenance_toggle.setText(advanced_maintenance_toggle_label(visible))

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
            self._update_domain_controls_enabled()
            self._pending_agent_message_index = append_agent_exchange(self._chat_messages, query)
            self.route_label.setText(_agent_route_line(build_agent_pending_message()))
            self._render_chat_log()
            self._start_background_task(
                kind="agent",
                label="에이전트 질문",
                task=lambda: self.presenter.ask_agent_workflow(query),
                refresh_pages=False,
            )

        def _start_background_task(self, *, kind: str, label: str, task: Callable[[], Any], refresh_pages: bool) -> None:
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
                self._update_domain_controls_enabled()
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
                if result.status_message:
                    self._set_status_text(result.status_message)
            elif result.kind == "maintenance":
                self._maintenance_running = False
                self._set_maintenance_enabled(True)
                self._update_domain_controls_enabled()
                self._refresh_agent_provider_status()
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
            enabled = enabled and maintenance_controls_enabled(maintenance_running=self._maintenance_running)
            for button in self.maintenance_buttons:
                button.setEnabled(enabled)

        def _update_domain_controls_enabled(self) -> None:
            enabled = domain_controls_enabled(agent_running=self._agent_running, maintenance_running=self._maintenance_running)
            self.domain_combo.setEnabled(enabled)
            self.domain_refresh_button.setEnabled(enabled)
            self.domain_switch_button.setEnabled(enabled)
            self.new_domain_button.setEnabled(enabled)

        def _set_status_text(self, message: str) -> None:
            self._full_status_message = str(message or "")
            self._refresh_status_text_elision()

        def _refresh_status_text_elision(self) -> None:
            tooltip_targets = (self.status_bar,) if hasattr(self, "status_bar") else ()
            set_elided_status_text(self.status_label, self._full_status_message, tooltip_targets=tooltip_targets)

        def _toggle_agent_provider_detail(self) -> None:
            self._agent_provider_detail_visible = toggle_agent_provider_detail_visible(self._agent_provider_detail_visible)
            self.agent_provider_detail_label.setVisible(self._agent_provider_detail_visible)
            self.agent_provider_detail_toggle.setText(agent_provider_detail_toggle_label(self._agent_provider_detail_visible))
            self._refresh_agent_provider_status()

        def _refresh_agent_provider_status(self) -> None:
            status = build_agent_provider_panel_status()
            self.agent_provider_detail_label.setText("\n".join(status.detail_lines))
            self.agent_provider_detail_label.setToolTip(status.tooltip)
            self.agent_provider_detail_toggle.setText(agent_provider_detail_toggle_label(self._agent_provider_detail_visible))
            set_elided_status_text(
                self.agent_provider_summary_label,
                status.summary,
                fallback_width=260,
                min_elide_width=60,
                tooltip_targets=(self.agent_provider_detail_toggle,),
            )
            tooltip = f"{status.summary}\n\n" + status.tooltip
            self.agent_provider_summary_label.setToolTip(tooltip)
            self.agent_provider_detail_toggle.setToolTip(tooltip)

        def _render_chat_log(self) -> None:
            self.chat_log.setHtml(render_chat_messages_html(self._chat_messages))
            scrollbar = self.chat_log.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    return WikiDesktopWindow(config)

