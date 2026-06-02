from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.config import load_domain_config
from wiki_tool.lint import run_wiki_lint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki 구조 lint를 실행합니다.")
    parser.add_argument("--domain", required=True, help="domain.yml 경로")
    args = parser.parse_args(argv)

    domain_path = Path(args.domain)
    config = load_domain_config(domain_path)
    result = run_wiki_lint(config)
    if result.ok:
        print("위키 lint 통과")
        return 0

    for issue in result.issues:
        print(f"{issue.severity}: {issue.path}: {issue.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
