from __future__ import annotations

import math
from typing import Any

from .desktop_styles import GUI_GRAPH_TYPE_LABELS


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
