from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.config import load_domain_config
from wiki_tool.mcp_server import create_fastmcp_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki MCP server를 실행합니다.")
    parser.add_argument("--domain", required=True, help="domain.yml 경로")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args(argv)

    config = load_domain_config(Path(args.domain))
    server = create_fastmcp_server(config)
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
