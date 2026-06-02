from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import DomainConfig
from .mcp_registry import create_tool_registry


def register_mcp_tools(server: Any, config: DomainConfig) -> dict[str, Callable[..., Any]]:
    registry = create_tool_registry(config)
    for name, fn in registry.items():
        server.tool(name=name)(fn)
    return registry


def create_fastmcp_server(config: DomainConfig) -> Any:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(f"llm-wiki-{config.slug}")
    register_mcp_tools(server, config)
    return server
