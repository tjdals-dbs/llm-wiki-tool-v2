from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .agent_provider import PROVIDER_CODEX, PROVIDER_GEMINI, PROVIDER_RULE_BASED, load_agent_provider_config


REVIEW_AGENT_PROVIDERS = frozenset({PROVIDER_CODEX, PROVIDER_GEMINI})


def run_maintenance_review(
    summarize: Mapping[str, Any],
    organize: Mapping[str, Any],
    answer_concept_updates: Mapping[str, Any] | None = None,
    *,
    review_runner: Callable[[str], Any],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    provider_config = load_agent_provider_config("review", env=env)
    if provider_config.provider not in REVIEW_AGENT_PROVIDERS:
        return skipped_review_result()

    updates = answer_concept_updates or {}
    if maintenance_change_count(summarize, organize, updates) <= 0:
        return skipped_review_result()

    summary = build_review_changes_summary(provider_config.provider, summarize, organize, updates)
    try:
        return _coerce_review_result(review_runner(summary))
    except Exception as exc:
        return review_exception_result(exc)


def maintenance_change_count(
    summarize: Mapping[str, Any],
    organize: Mapping[str, Any],
    answer_concept_updates: Mapping[str, Any] | None = None,
) -> int:
    updates = answer_concept_updates or {}
    return sum(
        int(value or 0)
        for value in [
            summarize.get("summarized_count", 0),
            summarize.get("needs_review_count", 0),
            organize.get("promoted_count", 0),
            organize.get("merged_count", 0),
            updates.get("applied_count", 0),
        ]
    )


def build_review_changes_summary(
    provider: str,
    summarize: Mapping[str, Any],
    organize: Mapping[str, Any],
    answer_concept_updates: Mapping[str, Any] | None = None,
) -> str:
    updates = answer_concept_updates or {}
    return "\n".join(
        [
            f"{provider} review provider is checking the wiki maintenance changes.",
            f"- source summarized: {summarize.get('summarized_count', 0)}",
            f"- source needs review: {summarize.get('needs_review_count', 0)}",
            f"- source fallback: {summarize.get('fallback_count', 0)}",
            f"- concept promoted: {organize.get('promoted_count', 0)}",
            f"- concept merged: {organize.get('merged_count', 0)}",
            f"- concept fallback: {organize.get('fallback_count', 0)}",
            f"- answer concept updates applied: {updates.get('applied_count', 0)}",
            f"- answer concept updates skipped: {updates.get('skipped_count', 0)}",
        ]
    )


def skipped_review_result() -> dict[str, Any]:
    return {"role": "review", "provider": PROVIDER_RULE_BASED, "fallback": False, "status": "skipped", "draft": "", "error": ""}


def review_exception_result(exc: Exception) -> dict[str, Any]:
    return {"role": "review", "provider": PROVIDER_RULE_BASED, "fallback": True, "status": "review_exception", "draft": "", "error": str(exc)}


def _coerce_review_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "as_dict"):
        return dict(result.as_dict())
    return dict(result)
