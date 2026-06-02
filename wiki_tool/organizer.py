from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DomainConfig
from .manifest import ManifestEntry, read_manifest, write_manifest


@dataclass(frozen=True)
class OrganizeResult:
    promoted_count: int
    merged_count: int
    dropped_count: int
    skipped_count: int


def organize_pending_sources(config: DomainConfig, limit: int | None = None) -> OrganizeResult:
    entries = read_manifest(config.manifest_path)
    promoted_count = 0
    merged_count = 0
    dropped_count = 0
    skipped_count = 0
    processed = 0

    for key, entry in sorted(entries.items()):
        if entry.status != "summarized" or not entry.source_page:
            skipped_count += 1
            continue
        if limit is not None and processed >= limit:
            skipped_count += 1
            continue

        source_page = _safe_wiki_path(config, entry.source_page)
        source = _parse_source_summary(source_page)
        candidate_concepts = [concept for concept in source.candidate_concepts if not _is_generic_concept(concept)]
        if source.quality != "usable" or not candidate_concepts:
            dropped_count += 1
            continue

        concept_name = candidate_concepts[0]
        concept_path = config.wiki_dir / "concepts" / f"{_slug(concept_name)}.md"
        source_link = f"[{Path(entry.source_page).stem}](../sources/{Path(entry.source_page).name})"
        if concept_path.exists():
            existing = concept_path.read_text(encoding="utf-8")
            if source_link not in existing:
                concept_path.write_text(existing.rstrip() + f"\n- {source_link}\n", encoding="utf-8")
            merged_count += 1
        else:
            concept_path.parent.mkdir(parents=True, exist_ok=True)
            concept_path.write_text(
                _render_concept_page(concept_name, source, source_link),
                encoding="utf-8",
            )
            promoted_count += 1

        entries[key] = ManifestEntry(
            path=entry.path,
            sha256=entry.sha256,
            source_type=entry.source_type,
            status="organized",
            detected_at=entry.detected_at,
            source_page=entry.source_page,
            notes=entry.notes,
        )
        processed += 1

    write_manifest(config.manifest_path, entries)
    return OrganizeResult(
        promoted_count=promoted_count,
        merged_count=merged_count,
        dropped_count=dropped_count,
        skipped_count=skipped_count,
    )


@dataclass(frozen=True)
class ParsedSourceSummary:
    title: str
    summary: str
    key_points: list[str]
    evidence: list[str]
    candidate_concepts: list[str]
    quality: str


def _parse_source_summary(path: Path) -> ParsedSourceSummary:
    content = path.read_text(encoding="utf-8")
    return ParsedSourceSummary(
        title=_title(content),
        summary=_section_text(content, "Summary"),
        key_points=_section_bullets(content, "Key Points"),
        evidence=_section_bullets(content, "Evidence"),
        candidate_concepts=_section_bullets(content, "Candidate Concepts"),
        quality=_quality(content),
    )


def _render_concept_page(name: str, source: ParsedSourceSummary, source_link: str) -> str:
    explanation = source.summary if source.summary else "소스 요약을 바탕으로 정리한 개념입니다."
    evidence = source.evidence[:3] or source.key_points[:3]
    return "\n".join(
        [
            f"# {name}",
            "",
            "## Definition",
            "",
            explanation,
            "",
            "## Explanation",
            "",
            "\n".join(f"- {item}" for item in source.key_points) if source.key_points else "- 추가 설명이 필요합니다.",
            "",
            "## Related Concepts",
            "",
            "- 없음",
            "",
            "## Source Evidence",
            "",
            f"- {source_link}",
            *(f"- {item}" for item in evidence),
            "",
            "## Maintenance Notes",
            "",
            "- source summary 근거를 바탕으로 생성되었습니다.",
            "",
        ]
    )


def _safe_wiki_path(config: DomainConfig, relative_path: str) -> Path:
    candidate = (config.root / relative_path).resolve()
    if config.wiki_dir == candidate or config.wiki_dir in candidate.parents:
        return candidate
    raise ValueError(f"wiki 경로 밖의 파일은 조직할 수 없습니다: {relative_path}")


def _title(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def _section_text(content: str, heading: str) -> str:
    return "\n".join(_section_lines(content, heading)).strip()


def _section_bullets(content: str, heading: str) -> list[str]:
    items: list[str] = []
    for line in _section_lines(content, heading):
        if line.startswith("- "):
            value = line[2:].strip()
            if value != "없음":
                items.append(value)
    return items


def _section_lines(content: str, heading: str) -> list[str]:
    lines = content.splitlines()
    marker = f"## {heading}"
    collected: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip():
            collected.append(line.strip())
    return collected


def _quality(content: str) -> str:
    match = re.search(r"^- quality:\s*(\w+)", content, flags=re.MULTILINE)
    return match.group(1) if match else "weak"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-").lower()
    return normalized or "concept"


def _is_generic_concept(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "note",
        "notes",
        "memo",
        "메모",
        "일반 메모",
        "untitled",
        "source",
        "document",
        "문서",
        "이 문서",
        "이 자료",
        "자료",
    }
