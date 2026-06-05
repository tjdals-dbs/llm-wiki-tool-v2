from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DomainConfig
from .agent_hooks import AgentHookResult, draft_source_summary_with_agent
from .agent_provider import PROVIDER_CODEX, resolve_agent_provider
from .concept_filter import clean_candidate_concept, filter_candidate_concepts, is_valid_candidate_concept
from .extractors import ExtractedSource, extract_source
from .manifest import ManifestEntry, read_manifest, write_manifest
from .quality import QualityReview, review_source_quality


METADATA_LINE_RE = re.compile(r"^(source[_ -]?path|sha256|hash|tool[_ -]?trace|extracted[_ -]?text|raw[_ -]?path|created[_ -]?at|updated[_ -]?at)\s*[:=]", re.I)
UI_CHROME_RE = re.compile(
    r"^(home|menu|login|logout|search|share|subscribe|previous|next|top|"
    r"메뉴|홈|로그인|검색|공유|이전|다음|맨 위|전체 메뉴)$",
    re.I,
)
BOILERPLATE_RE = re.compile(r"(copyright|all rights reserved|개인정보처리방침|이용약관|쿠키|cookie|footer|navigation)", re.I)


@dataclass(frozen=True)
class SourceSummaryResult:
    summarized_count: int
    needs_review_count: int
    skipped_count: int
    provider: str = "rule_based"
    codex_used_count: int = 0
    fallback_count: int = 0


@dataclass(frozen=True)
class SourceAnalysis:
    summary: str
    key_points: list[str]
    evidence: list[str]
    candidate_concept_evidence: dict[str, list[str]]


def summarize_new_sources(config: DomainConfig, limit: int | None = None) -> SourceSummaryResult:
    entries = read_manifest(config.manifest_path)
    summarized_count = 0
    needs_review_count = 0
    skipped_count = 0
    provider = resolve_agent_provider()
    codex_used_count = 0
    fallback_count = 0
    processed = 0

    for path_key, entry in sorted(entries.items()):
        if entry.status not in {"new", "failed"}:
            skipped_count += 1
            continue
        if limit is not None and processed >= limit:
            skipped_count += 1
            continue

        raw_path = _safe_raw_path(config, entry.path)
        extracted = extract_source(raw_path, entry.source_type)
        candidate_concepts = _candidate_concepts(extracted)
        quality = review_source_quality(
            text=extracted.text,
            candidate_concepts=candidate_concepts,
            warnings=extracted.warnings,
            recommended_actions=extracted.recommended_actions,
            visual_notes=extracted.visual_notes,
        )
        source_page = _source_page_path(config, entry.path)
        source_page.parent.mkdir(parents=True, exist_ok=True)
        rule_based_page = _render_source_page(entry, extracted, candidate_concepts, quality)
        source_content = rule_based_page
        hook_result: AgentHookResult | None = None
        codex_quality = ""
        if provider == PROVIDER_CODEX:
            hook_result = draft_source_summary_with_agent(extracted.text)
            validation = validate_source_page_draft(hook_result.draft)
            if hook_result.provider == "codex" and not hook_result.fallback and validation["ok"]:
                draft = _sanitize_candidate_concept_sections(hook_result.draft)
                source_content = _with_source_pipeline_metadata(
                    draft,
                    entry,
                    provider="codex",
                    codex_status=hook_result.status,
                    fallback=False,
                    fallback_reason="",
                )
                codex_quality = _quality(source_content)
                codex_used_count += 1
            else:
                fallback_count += 1
                reason = hook_result.error or validation["reason"]
                source_content = _with_source_pipeline_metadata(
                    rule_based_page,
                    entry,
                    provider="codex",
                    codex_status=hook_result.status,
                    fallback=True,
                    fallback_reason=reason,
                )
        source_page.write_text(source_content, encoding="utf-8")

        relative_source_page = source_page.relative_to(config.root).as_posix()
        final_quality = codex_quality or quality.quality
        status = "summarized" if final_quality == "usable" else "needs_review"
        if status == "summarized":
            summarized_count += 1
        else:
            needs_review_count += 1
        entries[path_key] = ManifestEntry(
            path=entry.path,
            sha256=entry.sha256,
            source_type=entry.source_type,
            status=status,
            detected_at=entry.detected_at,
            source_page=relative_source_page,
            notes="",
        )
        processed += 1

    write_manifest(config.manifest_path, entries)
    return SourceSummaryResult(
        summarized_count=summarized_count,
        needs_review_count=needs_review_count,
        skipped_count=skipped_count,
        provider=provider,
        codex_used_count=codex_used_count,
        fallback_count=fallback_count,
    )


def _safe_raw_path(config: DomainConfig, relative_path: str) -> Path:
    raw_path = (config.raw_dir / relative_path).resolve()
    if config.raw_dir == raw_path or config.raw_dir in raw_path.parents:
        return raw_path
    raise ValueError(f"raw 경로 밖의 파일은 요약할 수 없습니다: {relative_path}")


def _source_page_path(config: DomainConfig, raw_relative_path: str) -> Path:
    slug = _slug(Path(raw_relative_path).stem)
    return config.wiki_dir / "sources" / f"{slug}.md"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-").lower()
    return normalized or "source"


def _candidate_concepts(extracted: ExtractedSource) -> list[str]:
    candidates: list[str] = []
    readable_text = _readable_text(extracted.text)
    for concept in _title_concepts(extracted.title):
        _append_concept(candidates, concept)
    for concept in _heading_concepts(extracted.text):
        _append_concept(candidates, concept)
    for token in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", readable_text):
        _append_concept(candidates, token)
    for concept in _korean_term_candidates(readable_text):
        _append_concept(candidates, concept)
    return candidates[:8]


def _title_concepts(title: str) -> list[str]:
    cleaned = clean_candidate_concept(title)
    if not cleaned:
        return []
    concepts = [cleaned]
    acronym_match = re.search(r"\b[A-Z][A-Z0-9]{2,}\b", cleaned)
    if acronym_match:
        concepts.append(acronym_match.group(0))
    return concepts


def _heading_concepts(text: str) -> list[str]:
    concepts: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if not match:
            continue
        heading = match.group(1).strip()
        cleaned = clean_candidate_concept(heading)
        if cleaned:
            concepts.append(cleaned)
    return concepts


def _korean_term_candidates(text: str) -> list[str]:
    concepts: list[str] = []
    readable = _readable_text(text)
    patterns = [
        r"([가-힣A-Za-z0-9 ()·/-]{2,30})(?:은|는)\s+[^.。!?]{4,80}(?:이다|한다|연결한다|의미한다)",
        r"([가-힣A-Za-z0-9 ()·/-]{2,30})(?:이란|란)\s+[^.。!?]{4,80}",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, readable):
            concept = clean_candidate_concept(match.group(1))
            if concept:
                concepts.append(concept)
    return concepts


def _append_concept(candidates: list[str], concept: str) -> None:
    cleaned = clean_candidate_concept(concept)
    if not cleaned:
        return
    normalized = cleaned.casefold()
    if all(item.casefold() != normalized for item in candidates):
        candidates.append(cleaned)


def _clean_concept(value: str) -> str:
    return clean_candidate_concept(value)


def _is_generic_concept(value: str) -> bool:
    return not is_valid_candidate_concept(value)


def _render_source_page(
    entry: ManifestEntry,
    extracted: ExtractedSource,
    candidate_concepts: list[str],
    quality: QualityReview,
) -> str:
    analysis = _analyze_source(extracted.text, candidate_concepts, quality)
    return "\n".join(
        [
            f"# {extracted.title}",
            "",
            "## Summary",
            "",
            analysis.summary,
            "",
            "## Key Points",
            "",
            _bullet_list(analysis.key_points),
            "",
            "## Evidence",
            "",
            _bullet_list(analysis.evidence),
            "",
            "## Visual Evidence",
            "",
            _bullet_list(extracted.visual_notes),
            "",
            "## Candidate Concepts",
            "",
            _bullet_list(candidate_concepts),
            "",
            "## Candidate Concept Evidence",
            "",
            _concept_evidence_list(analysis.candidate_concept_evidence),
            "",
            "## Quality Review",
            "",
            f"- quality: {quality.quality}",
            f"- warnings: {_inline_list(quality.warnings)}",
            f"- recommended_actions: {_inline_list(quality.recommended_actions)}",
            f"- concept_count: {quality.concept_count}",
            f"- concept_evidence_count: {quality.concept_evidence_count}",
            f"- substantive_content_count: {quality.substantive_content_count}",
            f"- visual_summary_count: {quality.visual_summary_count}",
            "",
            "## Source Metadata",
            "",
            f"- Raw path: {entry.path}",
            f"- SHA256: {entry.sha256}",
            f"- Source type: {entry.source_type}",
            f"- Ingest status: {quality.quality}",
            "",
        ]
    )


def validate_source_page_draft(draft: str) -> dict[str, str | bool]:
    if not draft.strip():
        return {"ok": False, "reason": "empty_draft"}
    if not _title_from_content(draft):
        return {"ok": False, "reason": "missing_title"}
    required = ["Summary", "Key Points", "Evidence", "Candidate Concepts"]
    missing = [heading for heading in required if f"## {heading}" not in draft]
    if missing:
        return {"ok": False, "reason": "missing_sections:" + ",".join(missing)}
    return {"ok": True, "reason": ""}


def _sanitize_candidate_concept_sections(content: str) -> str:
    candidates = filter_candidate_concepts(_section_bullets(content, "Candidate Concepts"))
    sanitized = _replace_bullet_section(content, "Candidate Concepts", candidates)
    if "## Candidate Concept Evidence" in sanitized:
        evidence = _filtered_concept_evidence_lines(
            _section_bullets(sanitized, "Candidate Concept Evidence"),
            candidates,
        )
        sanitized = _replace_bullet_section(sanitized, "Candidate Concept Evidence", evidence)
    return sanitized


def _filtered_concept_evidence_lines(lines: list[str], candidates: list[str]) -> list[str]:
    allowed = {candidate.casefold(): candidate for candidate in candidates}
    filtered: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if ":" not in line:
            continue
        raw_concept, raw_evidence = line.split(":", 1)
        concept = clean_candidate_concept(raw_concept)
        evidence = raw_evidence.strip()
        if not concept or not evidence:
            continue
        canonical = allowed.get(concept.casefold())
        if not canonical:
            continue
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(f"{canonical}: {evidence}")
    return filtered


def _section_bullets(content: str, heading: str) -> list[str]:
    items: list[str] = []
    for line in _section_lines(content, heading):
        if line.startswith("- "):
            value = line[2:].strip()
            if value and value != "없음":
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


def _replace_bullet_section(content: str, heading: str, items: list[str]) -> str:
    lines = content.splitlines()
    marker = f"## {heading}"
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == marker)
    except StopIteration:
        return content

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    section = [marker, "", _bullet_list(items)]
    return "\n".join(lines[:start] + section + [""] + lines[end:]).rstrip() + "\n"


def _with_source_pipeline_metadata(
    content: str,
    entry: ManifestEntry,
    *,
    provider: str,
    codex_status: str,
    fallback: bool,
    fallback_reason: str,
) -> str:
    lines = [content.rstrip()]
    if "## Source Metadata" not in content:
        lines.extend(
            [
                "",
                "## Source Metadata",
                "",
                f"- Raw path: {entry.path}",
                f"- SHA256: {entry.sha256}",
                f"- Source type: {entry.source_type}",
            ]
        )
    lines.extend(
        [
            "",
            "## Agent Metadata",
            "",
            f"- provider: {provider}",
            f"- codex_status: {codex_status}",
            f"- fallback: {str(fallback).lower()}",
        ]
    )
    if fallback_reason:
        lines.append(f"- fallback_reason: {_truncate(fallback_reason, 180)}")
    lines.append("")
    return "\n".join(lines)


def _title_from_content(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _quality(content: str) -> str:
    match = re.search(r"^- quality:\s*(\w+)", content, flags=re.MULTILINE)
    if not match:
        return "usable"
    value = match.group(1).strip()
    if value in {"weak", "needs_review"}:
        return "weak"
    return "usable"


def _analyze_source(
    text: str,
    candidate_concepts: list[str],
    quality: QualityReview,
) -> SourceAnalysis:
    readable_text = _readable_text(text)
    sentences = _sentences(readable_text)
    evidence = _evidence(sentences, candidate_concepts)
    key_points = _key_points(sentences, candidate_concepts)
    return SourceAnalysis(
        summary=_summary(sentences, quality),
        key_points=key_points,
        evidence=evidence,
        candidate_concept_evidence=_candidate_concept_evidence(candidate_concepts, evidence + key_points),
    )


def _summary(sentences: list[str], quality: QualityReview) -> str:
    if quality.quality == "weak":
        return (
            "이 source는 자동 개념 승격에 충분하지 않아 검토가 필요합니다. "
            "텍스트 레이어, OCR/vision 결과, 또는 수동 요약을 보완한 뒤 다시 summarize 하세요."
        )
    if not sentences:
        return "요약할 본문을 찾지 못했습니다."
    selected = _ranked_sentences(sentences, [])[:2]
    ordered = sorted(selected, key=lambda item: sentences.index(item))
    summary = " ".join(ordered)
    return _truncate(summary, 360)


def _key_points(sentences: list[str], candidate_concepts: list[str]) -> list[str]:
    return [_truncate(sentence, 220) for sentence in _ranked_sentences(sentences, candidate_concepts)[:5]]


def _evidence(sentences: list[str], candidate_concepts: list[str]) -> list[str]:
    evidence_sentences = [
        sentence
        for sentence in _ranked_sentences(sentences, candidate_concepts)
        if _contains_any_concept(sentence, candidate_concepts)
    ]
    if not evidence_sentences:
        evidence_sentences = _ranked_sentences(sentences, candidate_concepts)
    return [_truncate(sentence, 220) for sentence in evidence_sentences[:4]]


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    raw_parts = re.split(r"(?<=[.!?。])\s+|(?<=다)\s+|(?<=요)\s+", normalized)
    return [_clean_sentence(part) for part in raw_parts if len(_clean_sentence(part)) >= 8]


def _readable_text(text: str) -> str:
    lines: list[str] = []
    seen_lines: set[str] = set()
    in_code_block = False
    in_frontmatter = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if in_frontmatter:
            if line == "---":
                in_frontmatter = False
            continue
        if not lines and line == "---":
            in_frontmatter = True
            continue
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            continue
        if line == "---":
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        if _is_noise_line(line):
            continue
        line_key = line.casefold()
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        lines.append(line)
    return " ".join(lines)


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) <= 2:
        return True
    if METADATA_LINE_RE.search(stripped):
        return True
    if UI_CHROME_RE.search(stripped):
        return True
    if BOILERPLATE_RE.search(stripped):
        return True
    if re.fullmatch(r"https?://\S+|www\.\S+", stripped, flags=re.I):
        return True
    if re.fullmatch(r"[\W_0-9]+", stripped):
        return True
    return False


def _ranked_sentences(sentences: list[str], candidate_concepts: list[str]) -> list[str]:
    indexed = list(enumerate(_dedupe_sentences(sentences)))
    ranked = sorted(indexed, key=lambda item: (-_sentence_score(item[1], candidate_concepts), item[0]))
    return [sentence for _, sentence in ranked]


def _sentence_score(sentence: str, candidate_concepts: list[str]) -> int:
    score = 0
    if _contains_any_concept(sentence, candidate_concepts):
        score += 6
    if 35 <= len(sentence) <= 180:
        score += 3
    if re.search(r"(정의|의미|역할|관계|효과|위험|수익|근거|결론|요약|비교|가정)", sentence):
        score += 2
    if re.search(r"\b[A-Z][A-Z0-9]{2,}\b", sentence):
        score += 1
    if len(sentence) > 260:
        score -= 2
    return score


def _candidate_concept_evidence(
    candidate_concepts: list[str],
    evidence_candidates: list[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for concept in candidate_concepts:
        matches = [item for item in evidence_candidates if _contains_concept(item, concept)]
        result[concept] = matches[:2]
    return result


def _concept_evidence_list(concept_evidence: dict[str, list[str]]) -> str:
    if not concept_evidence:
        return "- 없음"
    lines: list[str] = []
    for concept, evidence_items in concept_evidence.items():
        if evidence_items:
            lines.append(f"- {concept}: " + " / ".join(evidence_items))
        else:
            lines.append(f"- {concept}: 근거 문장을 찾지 못했습니다.")
    return "\n".join(lines)


def _contains_any_concept(sentence: str, candidate_concepts: list[str]) -> bool:
    return any(_contains_concept(sentence, concept) for concept in candidate_concepts)


def _contains_concept(sentence: str, concept: str) -> bool:
    normalized_sentence = sentence.casefold()
    normalized_concept = concept.casefold().strip()
    return bool(normalized_concept and normalized_concept in normalized_sentence)


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for sentence in sentences:
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sentence)
    return deduped


def _clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -")


def _truncate(value: str, limit: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "- 없음"
    return "\n".join(f"- {item}" for item in items)


def _inline_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"
