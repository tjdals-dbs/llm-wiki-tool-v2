from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import DomainConfig
from .manifest import ManifestEntry, read_manifest, write_manifest


IGNORED_RAW_FILENAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


@dataclass(frozen=True)
class RawScanResult:
    scanned_count: int
    new_count: int
    changed_count: int
    ignored_count: int


def scan_raw_sources(config: DomainConfig) -> RawScanResult:
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    previous = read_manifest(config.manifest_path)
    next_entries = dict(previous)

    scanned_count = 0
    new_count = 0
    changed_count = 0
    ignored_count = 0
    detected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for raw_path in sorted(config.raw_dir.rglob("*")):
        if raw_path.is_dir():
            continue
        relative_path = raw_path.relative_to(config.raw_dir).as_posix()
        if _is_ignored_raw_path(config.raw_dir, raw_path):
            ignored_count += 1
            next_entries.pop(relative_path, None)
            continue

        scanned_count += 1
        sha256 = _sha256(raw_path)
        source_type = _source_type(raw_path)
        old_entry = previous.get(relative_path)

        if old_entry is None:
            new_count += 1
            next_entries[relative_path] = ManifestEntry(
                path=relative_path,
                sha256=sha256,
                source_type=source_type,
                status="new",
                detected_at=detected_at,
            )
        elif old_entry.sha256 != sha256:
            changed_count += 1
            next_entries[relative_path] = ManifestEntry(
                path=relative_path,
                sha256=sha256,
                source_type=source_type,
                status="new",
                detected_at=detected_at,
                source_page=old_entry.source_page,
                notes="원본 해시가 변경되어 재처리가 필요합니다.",
            )
        else:
            next_entries[relative_path] = old_entry

    write_manifest(config.manifest_path, next_entries)
    return RawScanResult(
        scanned_count=scanned_count,
        new_count=new_count,
        changed_count=changed_count,
        ignored_count=ignored_count,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    return "text"


def _is_ignored_raw_path(raw_root: Path, path: Path) -> bool:
    parts = path.relative_to(raw_root).parts
    if not parts:
        return False
    if parts[0] == "private":
        return True
    return any(_is_hidden_or_sidecar_part(part) for part in parts)


def _is_hidden_or_sidecar_part(part: str) -> bool:
    if part in IGNORED_RAW_FILENAMES:
        return True
    if part.startswith("._"):
        return True
    return part.startswith(".")
