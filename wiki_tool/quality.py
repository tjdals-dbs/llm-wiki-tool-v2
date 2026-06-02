from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityReview:
    quality: str
    warnings: list[str]
    recommended_actions: list[str]
    concept_count: int
    concept_evidence_count: int
    substantive_content_count: int
    visual_summary_count: int


def review_source_quality(
    *,
    text: str,
    candidate_concepts: list[str],
    warnings: list[str],
    recommended_actions: list[str],
    visual_notes: list[str],
) -> QualityReview:
    substantive_count = _substantive_sentence_count(text)
    concept_evidence_count = len(candidate_concepts) if substantive_count else 0
    merged_warnings = list(warnings)
    merged_actions = list(recommended_actions)

    if substantive_count == 0:
        merged_warnings.append("실질적인 본문 내용을 찾지 못했습니다.")
        if "manual_review" not in merged_actions:
            merged_actions.append("manual_review")
    if not candidate_concepts:
        merged_warnings.append("개념 후보가 없습니다.")

    quality = "usable"
    if substantive_count == 0 or not candidate_concepts or recommended_actions:
        quality = "weak"

    return QualityReview(
        quality=quality,
        warnings=merged_warnings,
        recommended_actions=merged_actions,
        concept_count=len(candidate_concepts),
        concept_evidence_count=concept_evidence_count,
        substantive_content_count=substantive_count,
        visual_summary_count=len(visual_notes),
    )


def _substantive_sentence_count(text: str) -> int:
    sentences = [part.strip() for part in text.replace("\n", " ").split(".")]
    return sum(1 for sentence in sentences if len(sentence) >= 10)
