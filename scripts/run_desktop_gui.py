from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.config import load_domain_config
from wiki_tool.desktop_gui import run_desktop_gui
from wiki_tool.env_loader import load_dotenv_if_present


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description="LLM Wiki 데스크톱 GUI를 실행합니다.")
    parser.add_argument("--domain", default="examples/finance/domain.yml", help="domain.yml 경로")
    args = parser.parse_args(argv)

    config = load_domain_config(Path(args.domain))
    run_desktop_gui(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
