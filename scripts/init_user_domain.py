from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.user_domain import UserDomainInitError, create_user_domain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a local user domain workspace.")
    parser.add_argument("--slug", required=True, help="safe folder slug, e.g. finance-private")
    parser.add_argument("--name", required=True, help="human-readable domain name")
    parser.add_argument("--description", help="optional domain description")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        result = create_user_domain(
            project_root=Path(args.project_root),
            slug=args.slug,
            name=args.name,
            description=args.description,
        )
    except UserDomainInitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created user domain: {result.domain_dir}")
    print(f"Domain config: {result.domain_file}")
    print("Run desktop GUI:")
    print(result.gui_command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
