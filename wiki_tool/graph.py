from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

from .config import DomainConfig


def build_wiki_graph(config: DomainConfig) -> dict[str, list[dict[str, Any]]]:
    pages = _wiki_pages(config)
    nodes = [
        {"id": page, "path": page, "label": _page_title(config.root / page), "type": _page_type(page)}
        for page in pages
    ]
    edges: list[dict[str, Any]] = []
    for page in pages:
        source = config.root / page
        for target in _markdown_links(source, config.root):
            if target in pages:
                edges.append({"from": page, "to": target, "type": _edge_type(page, target)})

    graph = {"nodes": nodes, "edges": edges}
    graph_path = config.wiki_dir / "graph" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


def get_related_pages(config: DomainConfig, path: str, depth: int = 1) -> list[dict[str, Any]]:
    graph = build_wiki_graph(config)
    neighbors: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        neighbors.setdefault(edge["from"], set()).add(edge["to"])
        neighbors.setdefault(edge["to"], set()).add(edge["from"])

    seen = {path}
    queue: deque[tuple[str, int]] = deque([(path, 0)])
    related_paths: list[str] = []
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor in sorted(neighbors.get(current, set())):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            related_paths.append(neighbor)
            queue.append((neighbor, current_depth + 1))

    node_by_path = {node["path"]: node for node in graph["nodes"]}
    return [node_by_path[item] for item in related_paths if item in node_by_path]


def _wiki_pages(config: DomainConfig) -> list[str]:
    if not config.wiki_dir.exists():
        return []
    pages: list[str] = []
    for path in config.wiki_dir.rglob("*.md"):
        pages.append(path.relative_to(config.root).as_posix())
    return sorted(pages)


def _page_type(path: str) -> str:
    if "/sources/" in path:
        return "source"
    if "/concepts/" in path:
        return "concept"
    if "/answers/" in path:
        return "answer"
    if path.endswith("index.md"):
        return "index"
    if path.endswith("overview.md"):
        return "overview"
    return "page"


def _page_title(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _markdown_links(source: Path, root: Path) -> list[str]:
    content = source.read_text(encoding="utf-8")
    targets: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", content):
        href = match.group(1)
        if href.startswith(("http://", "https://", "#")):
            continue
        target = (source.parent / href).resolve()
        if root == target or root in target.parents:
            targets.append(target.relative_to(root).as_posix())
    return targets


def _edge_type(source: str, target: str) -> str:
    if "/concepts/" in source and "/sources/" in target:
        return "derived_from"
    return "mentions"
