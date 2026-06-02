from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import DomainConfig
from .graph import build_wiki_graph, get_related_pages as graph_related_pages
from .lint import run_wiki_lint as core_run_wiki_lint
from .organizer import organize_pending_sources as core_organize_pending_sources
from .scanner import scan_raw_sources as core_scan_raw_sources
from .summarizer import summarize_new_sources as core_summarize_new_sources


class WikiToolAdapter:
    def __init__(self, config: DomainConfig) -> None:
        self.config = config

    def list_wiki_pages(self, page_type: str | None = None) -> list[dict[str, str]]:
        pages: list[dict[str, str]] = []
        if not self.config.wiki_dir.exists():
            return pages
        for path in sorted(self.config.wiki_dir.rglob("*.md")):
            relative = path.relative_to(self.config.root).as_posix()
            detected_type = _page_type(relative)
            if page_type is None or detected_type == page_type:
                pages.append({"path": relative, "type": detected_type, "title": _title(path)})
        return pages

    def read_wiki_page(self, path: str) -> str:
        wiki_path = self._safe_wiki_path(path)
        return wiki_path.read_text(encoding="utf-8")

    def search_wiki(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query_lower = query.lower()
        matches: list[dict[str, Any]] = []
        for page in self.list_wiki_pages():
            content = self.read_wiki_page(page["path"])
            score = content.lower().count(query_lower) + page["title"].lower().count(query_lower) * 3
            if score <= 0:
                continue
            matches.append(
                {
                    "path": page["path"],
                    "type": page["type"],
                    "title": page["title"],
                    "score": score,
                    "snippet": _snippet(content, query),
                }
            )
        return sorted(matches, key=lambda item: (-item["score"], item["path"]))[:limit]

    def get_wiki_graph(self) -> dict[str, list[dict[str, Any]]]:
        return build_wiki_graph(self.config)

    def get_related_pages(self, path: str, depth: int = 1) -> list[dict[str, Any]]:
        self._safe_wiki_path(path)
        return graph_related_pages(self.config, path, depth=depth)

    def ask_wiki_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        direct = self.search_wiki(query, limit=limit)
        seen = {item["path"] for item in direct}
        context = list(direct)
        for item in direct:
            for related in self.get_related_pages(item["path"], depth=1):
                if len(context) >= limit:
                    return context
                if related["path"] in seen:
                    continue
                seen.add(related["path"])
                content = self.read_wiki_page(related["path"])
                context.append(
                    {
                        "path": related["path"],
                        "type": related["type"],
                        "title": related["label"],
                        "score": 0,
                        "snippet": _first_nonempty_line(content),
                    }
                )
        return context[:limit]

    def scan_raw_sources(self) -> dict[str, Any]:
        result = core_scan_raw_sources(self.config)
        return {"message": "raw source scan 완료", **asdict(result)}

    def summarize_new_sources(self, limit: int | None = None) -> dict[str, Any]:
        result = core_summarize_new_sources(self.config, limit=limit)
        return {"message": "source summary 생성 완료", **asdict(result)}

    def organize_pending_sources(self, limit: int | None = None) -> dict[str, Any]:
        result = core_organize_pending_sources(self.config, limit=limit)
        build_wiki_graph(self.config)
        return {"message": "concept organization 완료", **asdict(result)}

    def apply_wiki_update(
        self,
        *,
        question: str,
        answer: str,
        used_pages: list[dict[str, Any]] | None = None,
        related_pages: list[dict[str, Any]] | None = None,
        status: str = "ok",
    ) -> dict[str, str]:
        answer_dir = self.config.wiki_dir / "answers"
        answer_dir.mkdir(parents=True, exist_ok=True)
        path = answer_dir / f"{_slug(question)}.md"
        path.write_text(
            _render_answer_page(
                question=question,
                answer=answer,
                used_pages=used_pages or [],
                related_pages=related_pages or [],
                status=status,
            ),
            encoding="utf-8",
        )
        return {"path": path.relative_to(self.config.root).as_posix(), "status": status}

    def run_wiki_lint(self) -> dict[str, Any]:
        result = core_run_wiki_lint(self.config)
        return {"ok": result.ok, "issues": [asdict(issue) for issue in result.issues]}

    def _safe_wiki_path(self, path: str) -> Path:
        candidate = (self.config.root / path).resolve()
        if not (self.config.wiki_dir == candidate or self.config.wiki_dir in candidate.parents):
            raise ValueError(f"wiki 경로 밖은 읽을 수 없습니다: {path}")
        if not candidate.exists():
            raise FileNotFoundError(path)
        return candidate


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


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _snippet(content: str, query: str) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    index = compact.lower().find(query.lower())
    if index < 0:
        return compact[:160]
    start = max(0, index - 60)
    end = min(len(compact), index + len(query) + 100)
    return compact[start:end]


def _first_nonempty_line(content: str) -> str:
    for line in content.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _render_answer_page(
    *,
    question: str,
    answer: str,
    used_pages: list[dict[str, Any]],
    related_pages: list[dict[str, Any]],
    status: str,
) -> str:
    return "\n".join(
        [
            f"# {question}",
            "",
            "## Answer",
            "",
            answer,
            "",
            "## Used Pages",
            "",
            _page_bullets(used_pages),
            "",
            "## Related Pages",
            "",
            _page_bullets(related_pages),
            "",
            "## Maintenance Notes",
            "",
            f"- status: {status}",
            "",
        ]
    )


def _page_bullets(pages: list[dict[str, Any]]) -> str:
    if not pages:
        return "- 없음"
    return "\n".join(f"- {page.get('path', '')}" for page in pages if page.get("path"))


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-").lower()
    return normalized or "answer"
