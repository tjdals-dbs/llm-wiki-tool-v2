from __future__ import annotations

from typing import Any

from .agent_hooks import review_wiki_changes_with_agent
from .config import DomainConfig
from .maintenance_review import run_maintenance_review
from .mcp_tools import WikiToolAdapter


def run_maintenance_once(config: DomainConfig) -> dict[str, Any]:
    adapter = WikiToolAdapter(config)
    scan = adapter.scan_raw_sources()
    summarize = adapter.summarize_new_sources()
    organize = adapter.organize_pending_sources()
    answers = adapter.analyze_answer_candidates()
    answer_concept_drafts = adapter.draft_answer_concept_updates()
    answer_concept_updates = adapter.apply_answer_concept_updates(draft_result=answer_concept_drafts)
    review = run_maintenance_review(
        summarize,
        organize,
        answer_concept_updates,
        review_runner=review_wiki_changes_with_agent,
    )
    if review.get("status") != "skipped":
        _append_review_log(config, review)
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
