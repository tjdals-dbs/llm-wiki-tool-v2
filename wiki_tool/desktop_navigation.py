from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse


PAGE_NAVIGATION_GROUPS = [
    ("info", "Wiki Info", {"shape": "hexagon", "color": "#8b95a5"}),
    ("concept", "Concepts", {"shape": "circle", "color": "#4fb277"}),
    ("source", "Sources", {"shape": "square", "color": "#4e7fd8"}),
    ("log", "Logs", {"shape": "circle", "color": "#8b95a5"}),
]
PAGE_NAVIGATION_CHILD_INDENT = "    "


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


def build_page_navigation_items(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {group_key: [] for group_key, _title, _marker in PAGE_NAVIGATION_GROUPS}
    for page in pages:
        buckets.setdefault(_navigation_group_key(page), []).append(page)

    items: list[dict[str, Any]] = []
    for group_key, title, marker in PAGE_NAVIGATION_GROUPS:
        group_pages = _sort_navigation_group(group_key, buckets.get(group_key, []))
        if not group_pages:
            continue
        items.append({"kind": "header", "title": title, "group": group_key, "marker": marker})
        for page in group_pages:
            items.append(
                {
                    "kind": "page",
                    "title": _page_navigation_label(page),
                    "group": group_key,
                    "path": str(page.get("path", "")),
                    "tooltip": str(page.get("tooltip") or page.get("title") or page.get("path") or ""),
                }
            )
    return items


def navigation_item_flags(nav_item: dict[str, Any], item_flag: Any) -> Any:
    if nav_item.get("kind") == "header":
        return item_flag.ItemIsEnabled
    return item_flag.ItemIsEnabled | item_flag.ItemIsSelectable


def _group_pages(pages: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {group_key: [] for group_key, _title, _marker in PAGE_NAVIGATION_GROUPS}
    for page in pages:
        buckets.setdefault(_navigation_group_key(page), []).append(page)
    return [
        (title, _sort_navigation_group(group_key, buckets[group_key]))
        for group_key, title, _marker in PAGE_NAVIGATION_GROUPS
        if buckets.get(group_key)
    ]


def _navigation_group_key(page: dict[str, Any]) -> str:
    page_type = str(page.get("type", "page"))
    path = str(page.get("path", ""))
    filename = PurePosixPath(path).name.lower()
    if page_type in {"index", "overview"} or filename in {"index.md", "overview.md"}:
        return "info"
    if page_type == "concept" or path.startswith("wiki/concepts/"):
        return "concept"
    if page_type == "source" or path.startswith("wiki/sources/"):
        return "source"
    return "log"


def _sort_navigation_group(group_key: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if group_key != "info":
        return pages
    order = {"index.md": 0, "overview.md": 1}
    return sorted(pages, key=lambda page: order.get(PurePosixPath(str(page.get("path", ""))).name.lower(), 99))


def _page_navigation_label(page: dict[str, Any]) -> str:
    label = str(page.get("label") or page.get("title") or "").strip()
    if label:
        return label
    path = str(page.get("path", "")).strip()
    if not path:
        return "Untitled"
    return PurePosixPath(path).stem or path
