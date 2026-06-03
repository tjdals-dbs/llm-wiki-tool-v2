from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .agent_hooks import AgentHookResult, draft_concept_update_with_agent
from .agent_provider import PROVIDER_CODEX, resolve_agent_provider
from .config import DomainConfig
from .manifest import ManifestEntry, read_manifest, write_manifest


@dataclass(frozen=True)
class OrganizeResult:
    promoted_count: int
    merged_count: int
    dropped_count: int
    skipped_count: int
    provider: str = "rule_based"
    codex_used_count: int = 0
    fallback_count: int = 0


def organize_pending_sources(config: DomainConfig, limit: int | None = None) -> OrganizeResult:
    entries = read_manifest(config.manifest_path)
    promoted_count = 0
    merged_count = 0
    dropped_count = 0
    skipped_count = 0
    provider = resolve_agent_provider()
    codex_used_count = 0
    fallback_count = 0
    processed = 0

    for key, entry in sorted(entries.items()):
        if entry.status != "summarized" or not entry.source_page:
            skipped_count += 1
            continue
        if limit is not None and processed >= limit:
            skipped_count += 1
            continue

        source_page = _safe_wiki_path(config, entry.source_page)
        source_page_content = source_page.read_text(encoding="utf-8")
        source = _parse_source_summary(source_page)
        candidate_concepts = [concept for concept in source.candidate_concepts if not _is_generic_concept(concept)]
        if source.quality != "usable" or not candidate_concepts:
            dropped_count += 1
            continue

        source_link = f"[{Path(entry.source_page).stem}](../sources/{Path(entry.source_page).name})"
        organized_any = False
        organized_targets_by_evidence: dict[str, Path] = {}
        for concept_name in candidate_concepts:
            if not _has_concept_evidence(concept_name, source):
                continue

            evidence = _evidence_for_concept(concept_name, source)
            evidence_signature = _concept_evidence_signature(concept_name, source)
            concept_path = organized_targets_by_evidence.get(evidence_signature) or _concept_page_path(config, concept_name)
            hook_result: AgentHookResult | None = None
            validation: dict[str, str | bool] = {"ok": False, "reason": "codex_not_used"}
            if provider == PROVIDER_CODEX:
                hook_result = draft_concept_update_with_agent(
                    _concept_agent_payload(concept_name, source_link, source_page_content)
                )
                validation = validate_concept_page_draft(hook_result.draft)
            if concept_path.exists():
                existing = concept_path.read_text(encoding="utf-8")
                if _can_use_codex_draft(hook_result, validation):
                    merged = _merge_codex_concept_page(existing, hook_result.draft, source_link, evidence)
                    codex_used_count += 1
                else:
                    if provider == PROVIDER_CODEX:
                        fallback_count += 1
                    merged = _merge_concept_page(existing, source_link, evidence)
                if merged != existing:
                    concept_path.write_text(merged, encoding="utf-8")
                    merged_count += 1
            else:
                concept_path.parent.mkdir(parents=True, exist_ok=True)
                if _can_use_codex_draft(hook_result, validation):
                    concept_page = _with_concept_pipeline_metadata(
                        hook_result.draft,
                        provider="codex",
                        codex_status=hook_result.status,
                        fallback=False,
                        fallback_reason="",
                    )
                    codex_used_count += 1
                else:
                    if provider == PROVIDER_CODEX:
                        fallback_count += 1
                    reason = ""
                    status = ""
                    if hook_result is not None:
                        reason = hook_result.error or str(validation["reason"])
                        status = hook_result.status
                    concept_page = _with_concept_pipeline_metadata(
                        _render_concept_page(concept_name, source, source_link),
                        provider=provider,
                        codex_status=status,
                        fallback=provider == PROVIDER_CODEX,
                        fallback_reason=reason,
                    )
                concept_path.write_text(concept_page, encoding="utf-8")
                promoted_count += 1
            organized_targets_by_evidence.setdefault(evidence_signature, concept_path)
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
        provider=provider,
        codex_used_count=codex_used_count,
        fallback_count=fallback_count,
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
    explanation = _explanation_for_concept(name, source.summary, evidence)
    key_points = _key_points_for_concept(evidence, source.key_points)
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
            explanation,
            "",
            "## Key Points",
            "",
            _bullet_list(key_points),
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


def validate_concept_page_draft(draft: str) -> dict[str, str | bool]:
    if not draft.strip():
        return {"ok": False, "reason": "empty_draft"}
    if not _title(draft):
        return {"ok": False, "reason": "missing_title"}
    has_explanation = bool(_section_text(draft, "Definition") or _section_text(draft, "Explanation"))
    if not has_explanation:
        return {"ok": False, "reason": "missing_reader_facing_explanation"}
    source_evidence = _section_lines(draft, "Source Evidence")
    if not source_evidence or not any("[" in line or "source" in line.casefold() or "근거" in line for line in source_evidence):
        return {"ok": False, "reason": "missing_source_evidence"}
    return {"ok": True, "reason": ""}


def _can_use_codex_draft(
    hook_result: AgentHookResult | None,
    validation: dict[str, str | bool],
) -> bool:
    return bool(hook_result and hook_result.provider == "codex" and not hook_result.fallback and validation["ok"])


def _concept_agent_payload(concept_name: str, source_link: str, source_page_content: str) -> str:
    return "\n".join(
        [
            f"target concept: {concept_name}",
            f"source link: {source_link}",
            "",
            source_page_content,
        ]
    )


def _with_concept_pipeline_metadata(
    content: str,
    *,
    provider: str,
    codex_status: str,
    fallback: bool,
    fallback_reason: str,
) -> str:
    lines = [
        content.rstrip(),
        "",
        "## Agent Metadata",
        "",
        f"- provider: {provider}",
        f"- codex_status: {codex_status}",
        f"- fallback: {str(fallback).lower()}",
    ]
    if fallback_reason:
        lines.append(f"- fallback_reason: {_truncate(fallback_reason, 180)}")
    lines.append("")
    return "\n".join(lines)


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
    incoming_aliases = _concept_aliases(concept_name) | _concept_aliases(_concept_slug(concept_name))
    for path in sorted(concept_dir.glob("*.md")):
        existing_content = path.read_text(encoding="utf-8")
        existing_aliases = _concept_aliases(_title(existing_content)) | _concept_aliases(path.stem)
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


def _explanation_for_concept(name: str, summary: str, evidence: list[str]) -> str:
    if summary:
        return summary
    if evidence:
        return f"{name}은 source evidence에서 반복적으로 확인된 개념입니다."
    return "source summary 근거를 바탕으로 추가 설명이 필요한 개념입니다."


def _key_points_for_concept(evidence: list[str], key_points: list[str]) -> list[str]:
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


def _evidence_signature(evidence: list[str]) -> str:
    normalized = [re.sub(r"\s+", " ", item).strip().casefold() for item in evidence if item.strip()]
    if not normalized:
        return ""
    return " | ".join(sorted(set(normalized)))


def _concept_evidence_signature(name: str, source: ParsedSourceSummary) -> str:
    direct = source.candidate_concept_evidence.get(name)
    if not direct:
        direct = [item for item in source.evidence + source.key_points if name.casefold() in item.casefold()]
    signature = _evidence_signature(direct)
    if signature:
        return signature
    return f"concept:{_normalize_concept_name(name)}"


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


def _merge_codex_concept_page(existing: str, draft: str, source_link: str, evidence: list[str]) -> str:
    merged = _merge_concept_page(existing, source_link, evidence)
    draft_note = _draft_note_from_concept_page(draft)
    if not draft_note or draft_note in merged:
        return merged
    note_block = "\n".join(
        [
            "",
            "## Agent Draft Notes",
            "",
            f"- {draft_note}",
            "",
            "## Agent Metadata",
            "",
            "- provider: codex",
            "- fallback: false",
            "",
        ]
    )
    return merged.rstrip() + "\n" + note_block


def _draft_note_from_concept_page(draft: str) -> str:
    for heading in ["Definition", "Explanation"]:
        text = _section_text(draft, heading)
        if text:
            return _truncate(re.sub(r"\s+", " ", text), 220)
    return ""


def _truncate(value: str, limit: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


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
