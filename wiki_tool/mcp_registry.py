from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import DomainConfig
from .mcp_tools import WikiToolAdapter


MCP_TOOL_NAMES = [
    "list_wiki_pages",
    "read_wiki_page",
    "search_wiki",
    "get_wiki_graph",
    "get_related_pages",
    "ask_wiki_context",
    "answer_question",
    "scan_raw_sources",
    "summarize_new_sources",
    "organize_pending_sources",
    "analyze_answer_candidates",
    "draft_answer_concept_updates",
    "apply_answer_concept_updates",
    "draft_source_summary_with_agent",
    "draft_concept_update_with_agent",
    "review_wiki_changes_with_agent",
    "apply_wiki_update",
    "run_wiki_lint",
]


def create_tool_registry(config: DomainConfig) -> dict[str, Callable[..., Any]]:
    adapter = WikiToolAdapter(config)
    return {
        "list_wiki_pages": adapter.list_wiki_pages,
        "read_wiki_page": adapter.read_wiki_page,
        "search_wiki": adapter.search_wiki,
        "get_wiki_graph": adapter.get_wiki_graph,
        "get_related_pages": adapter.get_related_pages,
        "ask_wiki_context": adapter.ask_wiki_context,
        "answer_question": adapter.answer_question,
        "scan_raw_sources": adapter.scan_raw_sources,
        "summarize_new_sources": adapter.summarize_new_sources,
        "organize_pending_sources": adapter.organize_pending_sources,
        "analyze_answer_candidates": adapter.analyze_answer_candidates,
        "draft_answer_concept_updates": adapter.draft_answer_concept_updates,
        "apply_answer_concept_updates": adapter.apply_answer_concept_updates,
        "draft_source_summary_with_agent": adapter.draft_source_summary_with_agent,
        "draft_concept_update_with_agent": adapter.draft_concept_update_with_agent,
        "review_wiki_changes_with_agent": adapter.review_wiki_changes_with_agent,
        "apply_wiki_update": adapter.apply_wiki_update,
        "run_wiki_lint": adapter.run_wiki_lint,
    }
