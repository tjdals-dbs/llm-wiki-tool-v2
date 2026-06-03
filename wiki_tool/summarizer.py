from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DomainConfig
from .extractors import ExtractedSource, extract_source
from .manifest import ManifestEntry, read_manifest, write_manifest
from .quality import QualityReview, review_source_quality


@dataclass(frozen=True)
class SourceSummaryResult:
    summarized_count: int
    needs_review_count: int
    skipped_count: int


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
        source_page.write_text(
            _render_source_page(entry, extracted, candidate_concepts, quality),
            encoding="utf-8",
        )

        relative_source_page = source_page.relative_to(config.root).as_posix()
        status = "summarized" if quality.quality == "usable" else "needs_review"
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
    for concept in _title_concepts(extracted.title):
        _append_concept(candidates, concept)
    for concept in _heading_concepts(extracted.text):
        _append_concept(candidates, concept)
    for token in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", extracted.text):
        _append_concept(candidates, token)
    for concept in _korean_term_candidates(extracted.text):
        _append_concept(candidates, concept)
    return candidates[:8]


def _title_concepts(title: str) -> list[str]:
    cleaned = title.strip()
    if not cleaned or _is_generic_concept(cleaned):
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
        if 2 <= len(heading) <= 48 and not _is_generic_concept(heading):
            concepts.append(heading)
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
            concept = _clean_concept(match.group(1))
            if concept and not _is_generic_concept(concept):
                concepts.append(concept)
    return concepts


def _append_concept(candidates: list[str], concept: str) -> None:
    cleaned = _clean_concept(concept)
    if not cleaned or _is_generic_concept(cleaned):
        return
    normalized = cleaned.casefold()
    if all(item.casefold() != normalized for item in candidates):
        candidates.append(cleaned)


def _clean_concept(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" -:：.,")
    if len(cleaned) < 2 or len(cleaned) > 60:
        return ""
    if re.search(r"[.!?。]", cleaned):
        return ""
    return cleaned


def _is_generic_concept(value: str) -> bool:
    return value.strip().casefold() in {
        "source",
        "untitled",
        "note",
        "notes",
        "memo",
        "문서",
        "일반 메모",
        "개요",
        "요약",
        "소개",
    }


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
        return "이 source는 자동 개념 승격에 충분하지 않아 검토가 필요합니다."
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
        lines.append(line)
    return " ".join(lines)


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
