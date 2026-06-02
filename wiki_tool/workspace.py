from __future__ import annotations

from .config import DomainConfig


def ensure_workspace_structure(config: DomainConfig) -> None:
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    for dirname in ["sources", "concepts", "answers", "graph"]:
        (config.wiki_dir / dirname).mkdir(parents=True, exist_ok=True)
