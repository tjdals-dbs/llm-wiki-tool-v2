from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
USER_DOMAIN_DIRS = [
    "raw",
    "manifests",
    "wiki",
    "wiki/sources",
    "wiki/concepts",
    "wiki/answers",
    "wiki/graph",
]


class UserDomainInitError(ValueError):
    pass


@dataclass(frozen=True)
class UserDomainInitResult:
    domain_dir: Path
    domain_file: Path
    gui_command: str


def create_user_domain(
    *,
    project_root: Path,
    slug: str,
    name: str,
    description: str | None = None,
    language: str = "ko",
) -> UserDomainInitResult:
    clean_slug = slug.strip()
    clean_name = name.strip()
    if not _is_valid_slug(clean_slug):
        raise UserDomainInitError(
            "Invalid slug. Use lowercase letters, numbers, hyphen, or underscore only; path separators and spaces are not allowed."
        )
    if not clean_name:
        raise UserDomainInitError("Domain name is required.")

    root = project_root.resolve()
    user_domains_dir = (root / "user_domains").resolve()
    domain_dir = (user_domains_dir / clean_slug).resolve()
    if domain_dir == user_domains_dir or user_domains_dir not in domain_dir.parents:
        raise UserDomainInitError("Invalid slug. Domain path must stay inside user_domains.")
    if domain_dir.exists():
        raise UserDomainInitError(f"User domain already exists: {domain_dir}")

    user_domains_dir.mkdir(parents=True, exist_ok=True)
    domain_dir.mkdir()
    for relative_dir in USER_DOMAIN_DIRS:
        (domain_dir / relative_dir).mkdir(parents=True, exist_ok=True)

    domain_file = domain_dir / "domain.yml"
    domain_description = description.strip() if description and description.strip() else f"Local user domain for {clean_name}."
    domain_file.write_text(
        "\n".join(
            [
                f"name: {clean_name}",
                f"slug: {clean_slug}",
                f"description: {domain_description}",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                f"language: {language}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    gui_command = f"python scripts\\run_desktop_gui.py --domain user_domains\\{clean_slug}\\domain.yml"
    return UserDomainInitResult(domain_dir=domain_dir, domain_file=domain_file, gui_command=gui_command)


def _is_valid_slug(slug: str) -> bool:
    if not SLUG_PATTERN.fullmatch(slug):
        return False
    return "/" not in slug and "\\" not in slug and ".." not in slug
