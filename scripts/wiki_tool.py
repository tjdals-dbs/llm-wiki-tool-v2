from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.config import load_domain_config
from wiki_tool.env_loader import load_dotenv_if_present
from wiki_tool.mcp_registry import create_tool_registry


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description="LLM Wiki Tool v2 CLI")
    parser.add_argument("--domain", required=True, help="domain.yml 경로")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scan", help="raw source scan 실행")
    subparsers.add_parser("summarize", help="new source summary 생성")
    subparsers.add_parser("organize", help="pending source concept 조직")
    subparsers.add_parser("lint", help="wiki lint 실행")
    subparsers.add_parser("pipeline", help="scan, summarize, organize, lint 순서로 실행")

    args = parser.parse_args(argv)
    config = load_domain_config(Path(args.domain))
    registry = create_tool_registry(config)

    if args.command == "pipeline":
        outputs = [
            registry["scan_raw_sources"](),
            registry["summarize_new_sources"](),
            registry["organize_pending_sources"](),
            registry["run_wiki_lint"](),
        ]
        for output in outputs:
            _print_result(output)
        return 0 if outputs[-1].get("ok", False) else 1

    command_map = {
        "scan": "scan_raw_sources",
        "summarize": "summarize_new_sources",
        "organize": "organize_pending_sources",
        "lint": "run_wiki_lint",
    }
    result = registry[command_map[args.command]]()
    _print_result(result)
    if args.command == "lint" and not result.get("ok", False):
        return 1
    return 0


def _print_result(result: dict[str, Any]) -> None:
    message = result.get("message")
    if message:
        print(message)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
