from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainConfig:
    name: str
    slug: str
    description: str
    disclaimer: str
    language: str
    root: Path
    raw_dir: Path
    wiki_dir: Path
    manifest_path: Path


def load_domain_config(path: str | Path, *, root: str | Path | None = None) -> DomainConfig:
    domain_path = Path(path).resolve()
    workspace_root = Path(root).resolve() if root is not None else domain_path.parent.resolve()
    values = _parse_simple_yaml(domain_path)

    required = ["name", "slug", "description", "raw_dir", "wiki_dir", "manifest"]
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"domain.yml 필수 값이 없습니다: {', '.join(missing)}")

    language = values.get("language", "ko")
    return DomainConfig(
        name=values["name"],
        slug=values["slug"],
        description=values["description"],
        disclaimer=values.get("disclaimer", ""),
        language=language,
        root=workspace_root,
        raw_dir=_resolve_inside(workspace_root, values["raw_dir"]),
        wiki_dir=_resolve_inside(workspace_root, values["wiki_dir"]),
        manifest_path=_resolve_inside(workspace_root, values["manifest"]),
    )


def _parse_simple_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"지원하지 않는 domain.yml 줄입니다: {raw_line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _resolve_inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    raise ValueError(f"작업공간 밖의 경로는 사용할 수 없습니다: {relative_path}")
