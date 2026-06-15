from __future__ import annotations

from typing import Any

from .agent_hooks import AgentHookResult, review_wiki_changes_with_agent
from .agent_provider import PROVIDER_CODEX, PROVIDER_GEMINI, load_agent_provider_config
from .config import DomainConfig
from .mcp_tools import WikiToolAdapter


def run_maintenance_once(config: DomainConfig) -> dict[str, Any]:
    adapter = WikiToolAdapter(config)
    scan = adapter.scan_raw_sources()
    summarize = adapter.summarize_new_sources()
    organize = adapter.organize_pending_sources()
    answers = adapter.analyze_answer_candidates()
    answer_concept_drafts = adapter.draft_answer_concept_updates()
    answer_concept_updates = adapter.apply_answer_concept_updates(draft_result=answer_concept_drafts)
    review = _review_pipeline_if_agent_enabled(config, summarize, organize, answer_concept_updates)
    lint = adapter.run_wiki_lint()
    return {
        "scan": scan,
        "summarize": summarize,
        "organize": organize,
        "answers": answers,
        "answer_concept_drafts": answer_concept_drafts,
        "answer_concept_updates": answer_concept_updates,
        "review": review,
        "lint": lint,
    }


def _review_pipeline_if_agent_enabled(
    config: DomainConfig,
    summarize: dict[str, Any],
    organize: dict[str, Any],
    answer_concept_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_config = load_agent_provider_config("review")
    if provider_config.provider not in {PROVIDER_CODEX, PROVIDER_GEMINI}:
        return _skipped_review()

    updates = answer_concept_updates or {}
    if _maintenance_change_count(summarize, organize, updates) <= 0:
        return _skipped_review()

    summary = _review_changes_summary(provider_config.provider, summarize, organize, updates)
    try:
        review = review_wiki_changes_with_agent(summary)
    except Exception as exc:
        review = AgentHookResult(
            role="review",
            provider="rule_based",
            fallback=True,
            status="review_exception",
            draft="",
            error=str(exc),
        )
    result = review.as_dict()
    _append_review_log(config, result)
    return result


def _skipped_review() -> dict[str, Any]:
    return {"role": "review", "provider": "rule_based", "fallback": False, "status": "skipped", "draft": "", "error": ""}


def _maintenance_change_count(
    summarize: dict[str, Any],
    organize: dict[str, Any],
    answer_concept_updates: dict[str, Any],
) -> int:
    return sum(
        int(value or 0)
        for value in [
            summarize.get("summarized_count", 0),
            summarize.get("needs_review_count", 0),
            organize.get("promoted_count", 0),
            organize.get("merged_count", 0),
            answer_concept_updates.get("applied_count", 0),
        ]
    )


def _review_changes_summary(
    provider: str,
    summarize: dict[str, Any],
    organize: dict[str, Any],
    answer_concept_updates: dict[str, Any],
) -> str:
    return "\n".join(
        [
            f"{provider} review provider is checking the wiki maintenance changes.",
            f"- source summarized: {summarize.get('summarized_count', 0)}",
            f"- source needs review: {summarize.get('needs_review_count', 0)}",
            f"- source fallback: {summarize.get('fallback_count', 0)}",
            f"- concept promoted: {organize.get('promoted_count', 0)}",
            f"- concept merged: {organize.get('merged_count', 0)}",
            f"- concept fallback: {organize.get('fallback_count', 0)}",
            f"- answer concept updates applied: {answer_concept_updates.get('applied_count', 0)}",
            f"- answer concept updates skipped: {answer_concept_updates.get('skipped_count', 0)}",
        ]
    )


def _append_review_log(config: DomainConfig, review: dict[str, Any]) -> None:
    path = config.wiki_dir / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Wiki Log\n\n"
    status = review.get("status", "unknown")
    provider = review.get("provider", "rule_based")
    fallback = str(review.get("fallback", False)).lower()
    error = review.get("error", "")
    line = f"- agent review: provider={provider}, status={status}, fallback={fallback}"
    if error:
        line += f", warning={error}"
    path.write_text(existing.rstrip() + "\n\n" + line + "\n", encoding="utf-8")
