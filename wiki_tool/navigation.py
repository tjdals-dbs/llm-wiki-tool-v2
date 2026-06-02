from __future__ import annotations

from datetime import datetime, timezone

from .config import DomainConfig
from .mcp_tools import WikiToolAdapter


def refresh_navigation_pages(config: DomainConfig) -> None:
    adapter = WikiToolAdapter(config)
    pages = adapter.list_wiki_pages()
    source_pages = [page for page in pages if page["type"] == "source"]
    concept_pages = [page for page in pages if page["type"] == "concept"]
    answer_pages = [page for page in pages if page["type"] == "answer"]

    config.wiki_dir.mkdir(parents=True, exist_ok=True)
    (config.wiki_dir / "index.md").write_text(
        _render_index(source_pages, concept_pages, answer_pages),
        encoding="utf-8",
    )
    (config.wiki_dir / "overview.md").write_text(
        _render_overview(config, source_pages, concept_pages, answer_pages),
        encoding="utf-8",
    )
    _append_log(config)


def _render_index(
    source_pages: list[dict[str, str]],
    concept_pages: list[dict[str, str]],
    answer_pages: list[dict[str, str]],
) -> str:
    return "\n".join(
        [
            "# Wiki Index",
            "",
            "## Sources",
            "",
            _links(source_pages),
            "",
            "## Concepts",
            "",
            _links(concept_pages),
            "",
            "## Answers",
            "",
            _links(answer_pages),
            "",
        ]
    )


def _render_overview(
    config: DomainConfig,
    source_pages: list[dict[str, str]],
    concept_pages: list[dict[str, str]],
    answer_pages: list[dict[str, str]],
) -> str:
    return "\n".join(
        [
            "# Wiki Overview",
            "",
            "현재 wiki 상태를 요약합니다.",
            "",
            f"- domain: {config.name}",
            f"- language: {config.language}",
            f"- source pages: {len(source_pages)}",
            f"- concept pages: {len(concept_pages)}",
            f"- answer pages: {len(answer_pages)}",
            "",
        ]
    )


def _append_log(config: DomainConfig) -> None:
    path = config.wiki_dir / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Wiki Log\n\n"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(existing.rstrip() + f"\n\n- maintenance run: {timestamp}\n", encoding="utf-8")


def _links(pages: list[dict[str, str]]) -> str:
    if not pages:
        return "- 없음"
    lines = []
    for page in pages:
        href = page["path"].replace("wiki/", "", 1)
        lines.append(f"- [{page['title']}]({href})")
    return "\n".join(lines)
