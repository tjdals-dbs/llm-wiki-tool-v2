from __future__ import annotations

from typing import Any

from .agent_hooks import AgentHookResult, review_wiki_changes_with_agent
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
    review = _review_pipeline_if_codex_used(config, summarize, organize)
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


def _review_pipeline_if_codex_used(
    config: DomainConfig,
    summarize: dict[str, Any],
    organize: dict[str, Any],
) -> dict[str, Any]:
    codex_used = int(summarize.get("codex_used_count", 0)) + int(organize.get("codex_used_count", 0))
    if codex_used <= 0:
        return {"role": "review", "provider": "rule_based", "fallback": False, "status": "skipped", "draft": "", "error": ""}
    summary = "\n".join(
        [
            "Codex provider가 raw->wiki pipeline에서 사용되었습니다.",
            f"- source codex used: {summarize.get('codex_used_count', 0)}",
            f"- source fallback: {summarize.get('fallback_count', 0)}",
            f"- concept codex used: {organize.get('codex_used_count', 0)}",
            f"- concept fallback: {organize.get('fallback_count', 0)}",
        ]
    )
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
