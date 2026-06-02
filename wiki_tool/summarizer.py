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
    title = extracted.title.strip()
    if title and title.lower() not in {"source", "untitled"}:
        candidates.append(title)
    for token in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", extracted.text):
        if token not in candidates:
            candidates.append(token)
    return candidates[:8]


def _render_source_page(
    entry: ManifestEntry,
    extracted: ExtractedSource,
    candidate_concepts: list[str],
    quality: QualityReview,
) -> str:
    key_points = _key_points(extracted.text)
    evidence = _evidence(extracted.text)
    return "\n".join(
        [
            f"# {extracted.title}",
            "",
            "## Source Metadata",
            "",
            f"- Raw path: {entry.path}",
            f"- SHA256: {entry.sha256}",
            f"- Source type: {entry.source_type}",
            f"- Ingest status: {quality.quality}",
            "",
            "## Summary",
            "",
            _summary(extracted.text, quality),
            "",
            "## Key Points",
            "",
            _bullet_list(key_points),
            "",
            "## Evidence",
            "",
            _bullet_list(evidence),
            "",
            "## Visual Evidence",
            "",
            _bullet_list(extracted.visual_notes),
            "",
            "## Candidate Concepts",
            "",
            _bullet_list(candidate_concepts),
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
        ]
    )


def _summary(text: str, quality: QualityReview) -> str:
    if quality.quality == "weak":
        return "이 source는 자동 개념 승격에 충분하지 않아 검토가 필요합니다."
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:220] if compact else "요약할 본문을 찾지 못했습니다."


def _key_points(text: str) -> list[str]:
    points = _sentences(text)
    return points[:5]


def _evidence(text: str) -> list[str]:
    return [sentence[:180] for sentence in _sentences(text)[:3]]


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    raw_parts = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s*", compact)
    return [part.strip() for part in raw_parts if len(part.strip()) >= 8]


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "- 없음"
    return "\n".join(f"- {item}" for item in items)


def _inline_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"
