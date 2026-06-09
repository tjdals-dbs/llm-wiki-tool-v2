from __future__ import annotations

import re


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


def configure_status_bar(status_bar: object, *, height: int = 28) -> None:
    status_bar.setMinimumHeight(height)
    status_bar.setMaximumHeight(height)


def configure_status_label(label: object, *, height: int | None = None) -> None:
    label.setWordWrap(False)
    metrics = label.fontMetrics()
    stable_height = height or max(18, metrics.height() + 6)
    label.setMinimumHeight(stable_height)
    label.setMaximumHeight(stable_height)


def set_elided_status_text(
    label: object,
    message: str,
    *,
    available_width: int | None = None,
    fallback_width: int = 320,
    min_elide_width: int = 80,
    tooltip_targets: tuple[object, ...] = (),
) -> str:
    full_message = str(message or "")
    label.setToolTip(full_message)
    for target in tooltip_targets:
        target.setToolTip(full_message)
    label.setProperty("fullStatusText", full_message)
    display_message = _single_line_status_text(full_message)
    width = _status_label_width(label, available_width)
    if width < min_elide_width:
        width = fallback_width
    visible_text = label.fontMetrics().elidedText(display_message, _elide_right_mode(), width)
    label.setText(visible_text)
    return visible_text


def _single_line_status_text(message: str) -> str:
    return re.sub(r"\s+", " ", message.replace("\r", " ").replace("\n", " ").replace("\t", " ")).strip()


def _status_label_width(label: object, available_width: int | None) -> int:
    if available_width is not None:
        return max(0, int(available_width))
    try:
        contents_rect = label.contentsRect()
        width = contents_rect.width()
        if width > 0:
            return width
    except AttributeError:
        pass
    try:
        return max(0, int(label.width()))
    except AttributeError:
        return 0


def _elide_right_mode() -> object:
    try:
        from PySide6.QtCore import Qt

        return Qt.TextElideMode.ElideRight
    except Exception:
        return 0


def stylesheet() -> str:
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
    QLabel#AgentProviderSummary {{
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 12px;
        padding: 0 2px;
    }}
    QLabel#AgentProviderDetail {{
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 11px;
        line-height: 1.35;
        padding: 0 2px 4px 2px;
    }}
    QPushButton#InlineToggleButton {{
        background: transparent;
        border: 0;
        color: {GUI_STYLE_COLORS["accent"]};
        padding: 2px 4px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#InlineToggleButton:hover {{
        background: #e8eef9;
        border-radius: 5px;
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
        padding: 0 2px;
    }}
    QFrame#StatusBar {{
        background: #eef1f6;
        border: 1px solid {GUI_STYLE_COLORS["border"]};
        border-radius: 7px;
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
