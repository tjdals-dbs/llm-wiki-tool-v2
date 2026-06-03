from __future__ import annotations

import math
from typing import Any

from .config import DomainConfig
from .mcp_tools import WikiToolAdapter


GUI_PANEL_TITLES = ["위키 페이지", "선택한 페이지", "에이전트 제어"]
GUI_ACTION_LABELS = ["raw 스캔", "새 source 요약", "pending concept 조직", "wiki lint", "에이전트에게 질문"]
GUI_GRAPH_TYPE_LABELS = {
    "concept": "개념",
    "source": "원문",
    "answer": "답변",
    "journal": "답변",
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
    "border": "#d5dbe6",
    "text": "#242936",
    "muted": "#6f7785",
    "accent": "#74a7ff",
}


class DesktopGuiPresenter:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

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
            f"검토 필요 {result.get('needs_review_count', 0)}개"
        )

    def organize_pending_sources(self) -> str:
        result = self.adapter.organize_pending_sources()
        return (
            "concept 조직 완료: "
            f"승격 {result.get('promoted_count', 0)}개, "
            f"병합 {result.get('merged_count', 0)}개, "
            f"보류 {result.get('dropped_count', 0)}개"
        )

    def run_wiki_lint(self) -> str:
        result = self.adapter.run_wiki_lint()
        if result.get("ok"):
            return "wiki lint 통과"
        issues = result.get("issues", [])
        return "wiki lint 경고:\n" + "\n".join(f"- {item['path']}: {item['message']}" for item in issues)

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
        answer = self.adapter.answer_question(query)
        lines = [answer["answer"], "", "used pages:"]
        for item in answer.get("used_pages", []):
            lines.append(f"- {item['path']}: {item.get('title', '')}")
        lines.append("")
        lines.append("related pages:")
        related = answer.get("related_pages", [])
        if not related:
            lines.append("- 없음")
        for item in related:
            lines.append(f"- {item['path']}: {item.get('title', '')}")
        return "\n".join(lines)


class DesktopWikiApp:
    def __init__(self, config: DomainConfig) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.adapter = WikiToolAdapter(config)
        self.presenter = DesktopGuiPresenter(self.adapter)
        self.root = tk.Tk()
        self.root.title("LLM Wiki Tool v2")
        self.root.geometry("1440x840")
        self.root.configure(bg=GUI_STYLE_COLORS["app_bg"])

        self.search_var = tk.StringVar()
        self.question_var = tk.StringVar()
        self.graph_status_var = tk.StringVar(value="graph node에 마우스를 올리면 전체 제목을 볼 수 있습니다.")
        self.page_items: dict[str, str] = {}
        self.related_items: dict[str, str] = {}
        self.graph_tooltips: dict[str, str] = {}

        self._build_layout()
        self.refresh_pages()

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        ttk = self.ttk
        tk = self.tk
        self._configure_style()
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=12, style="Sidebar.TFrame")
        center = ttk.Frame(main, padding=(26, 18), style="Document.TFrame")
        right = ttk.Frame(main, padding=12, style="Agent.TFrame")
        main.add(left, weight=1)
        main.add(center, weight=3)
        main.add(right, weight=2)
        self.root.after(0, lambda: self._apply_initial_panel_sizes(main))

        ttk.Label(left, text="LLM 위키", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(left, text=GUI_PANEL_TITLES[0], style="Hint.TLabel").pack(anchor=tk.W, pady=(0, 10))
        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, pady=(6, 6))
        ttk.Entry(search_row, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(search_row, text="검색", command=self.refresh_pages).pack(side=tk.LEFT, padx=(6, 0))
        self.page_tree = ttk.Treeview(left, columns=("type",), show="tree headings", height=28)
        self.page_tree.heading("#0", text="page")
        self.page_tree.heading("type", text="type")
        self.page_tree.pack(fill=tk.BOTH, expand=True)
        self.page_tree.bind("<<TreeviewSelect>>", self._on_page_selected)

        ttk.Label(center, text=GUI_PANEL_TITLES[1], style="SectionTitle.TLabel").pack(anchor=tk.W)
        self.content_text = tk.Text(
            center,
            wrap=tk.WORD,
            height=30,
            bg=GUI_STYLE_COLORS["document_bg"],
            fg=GUI_STYLE_COLORS["text"],
            relief=tk.FLAT,
            padx=16,
            pady=14,
            font=("Segoe UI", 11),
        )
        self.content_text.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        ttk.Label(center, text="주변 graph", style="SectionTitle.TLabel").pack(anchor=tk.W)
        self.graph_canvas = tk.Canvas(
            center,
            height=220,
            bg="#f0f2f5",
            highlightthickness=1,
            highlightbackground=GUI_STYLE_COLORS["border"],
        )
        self.graph_canvas.pack(fill=tk.BOTH, expand=False)
        self.graph_canvas.bind("<Motion>", self._on_graph_motion)
        self.graph_canvas.bind("<Leave>", self._on_graph_leave)
        self.graph_canvas.bind("<Button-1>", self._on_graph_click)
        ttk.Label(center, textvariable=self.graph_status_var, style="GraphStatus.TLabel").pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(right, text=GUI_PANEL_TITLES[2], style="SectionTitle.TLabel").pack(anchor=tk.W)
        action_group = ttk.LabelFrame(right, text="raw maintenance", padding=8)
        action_group.pack(fill=tk.X, pady=(8, 10))
        for label, command in [
            ("raw 스캔", self._scan),
            ("새 source 요약", self._summarize),
            ("pending concept 조직", self._organize),
            ("wiki lint", self._lint),
            ("상태 새로고침", self._status),
        ]:
            ttk.Button(action_group, text=label, command=command).pack(fill=tk.X, pady=(5, 0))

        ttk.Label(right, text="질문", style="SectionTitle.TLabel").pack(anchor=tk.W, pady=(8, 2))
        ttk.Entry(right, textvariable=self.question_var).pack(fill=tk.X)
        ttk.Button(right, text="에이전트에게 질문", command=self._ask).pack(fill=tk.X, pady=(6, 6))
        self.agent_text = tk.Text(
            right,
            wrap=tk.WORD,
            height=22,
            bg="#ffffff",
            fg=GUI_STYLE_COLORS["text"],
            relief=tk.FLAT,
            padx=10,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.agent_text.pack(fill=tk.BOTH, expand=True)

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass
        style.configure("Sidebar.TFrame", background=GUI_STYLE_COLORS["sidebar_bg"])
        style.configure("Document.TFrame", background=GUI_STYLE_COLORS["document_bg"])
        style.configure("Agent.TFrame", background=GUI_STYLE_COLORS["agent_bg"])
        style.configure(
            "Title.TLabel",
            background=GUI_STYLE_COLORS["sidebar_bg"],
            foreground=GUI_STYLE_COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        )
        style.configure(
            "Hint.TLabel",
            background=GUI_STYLE_COLORS["sidebar_bg"],
            foreground=GUI_STYLE_COLORS["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=GUI_STYLE_COLORS["app_bg"],
            foreground=GUI_STYLE_COLORS["text"],
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "GraphStatus.TLabel",
            background=GUI_STYLE_COLORS["document_bg"],
            foreground=GUI_STYLE_COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", padding=6)
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _apply_initial_panel_sizes(self, main: Any) -> None:
        left_width, center_width, _right_width = GUI_PANEL_WEIGHTS
        try:
            main.sashpos(0, left_width)
            main.sashpos(1, left_width + center_width)
        except self.tk.TclError:
            return

    def refresh_pages(self) -> None:
        query = self.search_var.get().strip()
        pages = self.adapter.search_wiki(query, limit=100) if query else self.adapter.list_wiki_pages()
        self.page_tree.delete(*self.page_tree.get_children())
        self.page_items.clear()
        for page in pages:
            item_id = self.page_tree.insert("", "end", text=page["path"], values=(page["type"],))
            self.page_items[item_id] = page["path"]

    def _on_page_selected(self, _event: object) -> None:
        selected = self.page_tree.selection()
        if not selected:
            return
        path = self.page_items[selected[0]]
        self._show_page(path)

    def _show_page(self, path: str) -> None:
        self._set_text(self.content_text, self.adapter.read_wiki_page(path))
        graph = self.adapter.get_wiki_graph()
        node_by_path = {node["path"]: node for node in graph.get("nodes", [])}
        selected = node_by_path.get(path, _fallback_graph_node(path))
        related = self.adapter.get_related_pages(path, depth=1)
        self._draw_graph(selected, related)

    def _draw_graph(self, selected: dict[str, Any], related: list[dict[str, Any]]) -> None:
        width = max(self.graph_canvas.winfo_width(), 520)
        height = max(self.graph_canvas.winfo_height(), 220)
        layout = build_local_graph_layout(selected, related, width=width, height=height)
        self.graph_canvas.delete("all")
        self.related_items.clear()
        self.graph_tooltips.clear()
        for edge in layout["edges"]:
            self.graph_canvas.create_line(
                edge["x1"],
                edge["y1"],
                edge["x2"],
                edge["y2"],
                fill="#c9d0dc",
                width=2,
            )
        for node in layout["nodes"]:
            tag = f"graph-node-{len(self.related_items)}"
            self.related_items[tag] = node["path"]
            self.graph_tooltips[tag] = _graph_status_text(node)
            _draw_canvas_node(self.graph_canvas, node, tag)
        self.graph_status_var.set("관련 문서 없음" if not related else "node를 클릭하면 해당 wiki page로 이동합니다.")

    def _on_graph_motion(self, event: Any) -> None:
        tag = _current_graph_node_tag(self.graph_canvas)
        if not tag:
            self.graph_canvas.configure(cursor="")
            return
        path = self.related_items.get(tag)
        if path:
            self.graph_canvas.configure(cursor="hand2")
            self.graph_status_var.set(self.graph_tooltips.get(tag, path))

    def _on_graph_leave(self, _event: object) -> None:
        self.graph_canvas.configure(cursor="")
        self.graph_status_var.set("graph node에 마우스를 올리면 전체 제목을 볼 수 있습니다.")

    def _on_graph_click(self, _event: object) -> None:
        tag = _current_graph_node_tag(self.graph_canvas)
        path = self.related_items.get(tag or "")
        if path:
            self._show_page(path)

    def _scan(self) -> None:
        self._set_agent_status(self.presenter.scan_raw_sources())
        self.refresh_pages()

    def _summarize(self) -> None:
        self._set_agent_status(self.presenter.summarize_new_sources())
        self.refresh_pages()

    def _organize(self) -> None:
        self._set_agent_status(self.presenter.organize_pending_sources())
        self.refresh_pages()

    def _lint(self) -> None:
        self._set_agent_status(self.presenter.run_wiki_lint())

    def _status(self) -> None:
        self._set_agent_status(self.presenter.wiki_status())

    def _ask(self) -> None:
        self._set_agent_status(self.presenter.ask_agent(self.question_var.get()))

    def _set_agent_status(self, message: str) -> None:
        self._set_text(self.agent_text, message)

    def _set_text(self, widget: Any, value: str) -> None:
        widget.delete("1.0", self.tk.END)
        widget.insert(self.tk.END, value)


def run_desktop_gui(config: DomainConfig) -> None:
    app = DesktopWikiApp(config)
    app.run()


def _quality_value(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("- quality:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


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
        angle = (math.pi * 2 * index) / count
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


def _draw_canvas_node(canvas: Any, node: dict[str, Any], tag: str) -> None:
    x = float(node["x"])
    y = float(node["y"])
    radius = float(node["r"])
    fill = str(node["color"])
    shape = str(node["shape"])
    tags = (tag, "graph-node")
    if shape == "square":
        canvas.create_rectangle(x - radius, y - radius, x + radius, y + radius, fill=fill, outline="#6f7785", width=2, tags=tags)
    elif shape == "diamond":
        canvas.create_polygon(x, y - radius, x + radius, y, x, y + radius, x - radius, y, fill=fill, outline="#6f7785", width=2, tags=tags)
    elif shape == "hexagon":
        points = []
        for index in range(6):
            angle = math.pi / 6 + math.pi * 2 * index / 6
            points.extend([x + math.cos(angle) * radius, y + math.sin(angle) * radius])
        canvas.create_polygon(*points, fill=fill, outline="#6f7785", width=2, tags=tags)
    else:
        canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline="#6f7785", width=2, tags=tags)
    canvas.create_text(x, y + radius + 14, text=str(node["label"]), fill=GUI_STYLE_COLORS["text"], font=("Segoe UI", 9, "bold"), tags=tags)


def _current_graph_node_tag(canvas: Any) -> str | None:
    for tag in canvas.gettags("current"):
        if tag.startswith("graph-node-"):
            return tag
    return None


def _fallback_graph_node(path: str) -> dict[str, Any]:
    return {"path": path, "type": "page", "label": path.rsplit("/", 1)[-1], "tooltip": path, "style": {"color": "#d5dbe6", "shape": "circle"}}
