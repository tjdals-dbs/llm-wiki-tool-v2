from __future__ import annotations


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
