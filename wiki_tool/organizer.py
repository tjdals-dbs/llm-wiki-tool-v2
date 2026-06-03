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

        source_link = f"[{Path(entry.source_page).stem}](../sources/{Path(entry.source_page).name})"
        organized_any = False
        for concept_name in candidate_concepts:
            if not _has_concept_evidence(concept_name, source):
                continue

            concept_path = _concept_page_path(config, concept_name)
            evidence = _evidence_for_concept(concept_name, source)
            if concept_path.exists():
                existing = concept_path.read_text(encoding="utf-8")
                concept_path.write_text(
                    _merge_concept_page(existing, source_link, evidence),
                    encoding="utf-8",
                )
                merged_count += 1
            else:
                concept_path.parent.mkdir(parents=True, exist_ok=True)
                concept_path.write_text(
                    _render_concept_page(concept_name, source, source_link),
                    encoding="utf-8",
                )
                promoted_count += 1
            organized_any = True

        if not organized_any:
            dropped_count += 1
            continue

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
    candidate_concept_evidence: dict[str, list[str]]
    quality: str


def _parse_source_summary(path: Path) -> ParsedSourceSummary:
    content = path.read_text(encoding="utf-8")
    return ParsedSourceSummary(
        title=_title(content),
        summary=_section_text(content, "Summary"),
        key_points=_section_bullets(content, "Key Points"),
        evidence=_section_bullets(content, "Evidence"),
        candidate_concepts=_section_bullets(content, "Candidate Concepts"),
        candidate_concept_evidence=_section_concept_evidence(content, "Candidate Concept Evidence"),
        quality=_quality(content),
    )


def _render_concept_page(name: str, source: ParsedSourceSummary, source_link: str) -> str:
    evidence = _evidence_for_concept(name, source)
    definition = _definition_for_concept(name, evidence, source.summary)
    explanation = _explanation_items(evidence, source.key_points)
    related = _related_concepts(name, source.candidate_concepts)
    return "\n".join(
        [
            f"# {name}",
            "",
            "## Definition",
            "",
            definition,
            "",
            "## Explanation",
            "",
            _bullet_list(explanation),
            "",
            "## Related Concepts",
            "",
            _bullet_list(related),
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


def _section_concept_evidence(content: str, heading: str) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    for line in _section_bullets(content, heading):
        if ":" not in line:
            continue
        concept, raw_evidence = line.split(":", 1)
        items = [item.strip() for item in raw_evidence.split(" / ") if item.strip()]
        if items and items != ["근거 문장을 찾지 못했습니다."]:
            evidence[concept.strip()] = items
    return evidence


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


def _concept_page_path(config: DomainConfig, concept_name: str) -> Path:
    candidate = config.wiki_dir / "concepts" / f"{_concept_slug(concept_name)}.md"
    if candidate.exists():
        return candidate
    concept_dir = config.wiki_dir / "concepts"
    if not concept_dir.exists():
        return candidate
    incoming_aliases = _concept_aliases(concept_name)
    for path in sorted(concept_dir.glob("*.md")):
        existing_aliases = _concept_aliases(_title(path.read_text(encoding="utf-8")))
        if incoming_aliases & existing_aliases:
            return path
    return candidate


def _concept_slug(concept_name: str) -> str:
    acronym = _concept_acronym(concept_name)
    if acronym:
        return _slug(acronym)
    return _slug(concept_name)


def _concept_acronym(concept_name: str) -> str:
    parenthesized = re.search(r"\(([A-Za-z][A-Za-z0-9]{1,})\)", concept_name)
    if parenthesized:
        return parenthesized.group(1)
    standalone = re.fullmatch(r"[A-Z][A-Z0-9]{2,}", concept_name.strip())
    if standalone:
        return standalone.group(0)
    return ""


def _has_concept_evidence(name: str, source: ParsedSourceSummary) -> bool:
    if source.candidate_concept_evidence.get(name):
        return True
    normalized_name = name.casefold()
    return any(normalized_name in item.casefold() for item in source.evidence + source.key_points)


def _evidence_for_concept(name: str, source: ParsedSourceSummary) -> list[str]:
    concept_evidence = source.candidate_concept_evidence.get(name, [])
    if concept_evidence:
        return _dedupe(concept_evidence + source.evidence)[:4]
    related_evidence = [item for item in source.evidence if name.casefold() in item.casefold()]
    return _dedupe(related_evidence + source.evidence + source.key_points)[:4]


def _definition_for_concept(name: str, evidence: list[str], fallback_summary: str) -> str:
    if evidence:
        primary = evidence[0]
        if name.casefold() in primary.casefold():
            return primary
        return f"{name}은 source evidence에서 확인된 개념이며, 핵심 근거는 다음과 같습니다: {primary}"
    return fallback_summary or "source summary 근거를 바탕으로 추가 정리가 필요한 개념입니다."


def _explanation_items(evidence: list[str], key_points: list[str]) -> list[str]:
    return _dedupe(evidence + key_points)[:6]


def _related_concepts(name: str, candidate_concepts: list[str]) -> list[str]:
    normalized_name = name.casefold()
    return [
        concept
        for concept in candidate_concepts
        if concept.casefold() != normalized_name and not _is_generic_concept(concept)
    ][:6]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen or cleaned == "없음":
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "- 없음"
    return "\n".join(f"- {item}" for item in items)


def _merge_concept_page(existing: str, source_link: str, evidence: list[str]) -> str:
    lines_to_add = [source_link, *evidence]
    deduped_additions = [item for item in _dedupe(lines_to_add) if f"- {item}" not in existing]
    if not deduped_additions:
        return existing

    insertion = "".join(f"- {item}\n" for item in deduped_additions)
    marker = "## Source Evidence"
    if marker not in existing:
        return existing.rstrip() + "\n\n## Source Evidence\n\n" + insertion

    start = existing.index(marker)
    next_heading = existing.find("\n## ", start + len(marker))
    if next_heading < 0:
        return existing.rstrip() + "\n" + insertion
    return existing[:next_heading].rstrip() + "\n" + insertion + existing[next_heading:]


def _normalize_concept_name(value: str) -> str:
    normalized = re.sub(r"\([^)]*\)", " ", value)
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _concept_aliases(value: str) -> set[str]:
    aliases = {_normalize_concept_name(value)}
    for match in re.finditer(r"\(([^)]+)\)", value):
        aliases.add(_normalize_concept_name(match.group(1)))
    acronym = _concept_acronym(value)
    if acronym:
        aliases.add(_normalize_concept_name(acronym))
    return {alias for alias in aliases if alias}


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
