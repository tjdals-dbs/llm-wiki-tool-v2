from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_runtime import run_maintenance_once
from wiki_tool.config import load_domain_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki agent maintenance runtime")
    parser.add_argument("--domain", required=True, help="domain.yml 경로")
    parser.add_argument("--once", action="store_true", help="한 번만 실행하고 종료")
    parser.add_argument("--interval-seconds", type=float, default=30.0, help="반복 실행 간격")
    args = parser.parse_args(argv)

    config = load_domain_config(Path(args.domain))
    while True:
        result = run_maintenance_once(config)
        print("agent maintenance 완료")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.once:
            return 0 if result["lint"].get("ok", False) else 1
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
