from __future__ import annotations

from typing import Any

from .config import DomainConfig
from .mcp_tools import WikiToolAdapter


def run_maintenance_once(config: DomainConfig) -> dict[str, Any]:
    adapter = WikiToolAdapter(config)
    scan = adapter.scan_raw_sources()
    summarize = adapter.summarize_new_sources()
    organize = adapter.organize_pending_sources()
    lint = adapter.run_wiki_lint()
    return {
        "scan": scan,
        "summarize": summarize,
        "organize": organize,
        "lint": lint,
    }
