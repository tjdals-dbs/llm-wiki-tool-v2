from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


MANIFEST_FIELDS = ["path", "sha256", "source_type", "status", "detected_at", "source_page", "notes"]


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    source_type: str
    status: str
    detected_at: str
    source_page: str = ""
    notes: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "source_type": self.source_type,
            "status": self.status,
            "detected_at": self.detected_at,
            "source_page": self.source_page,
            "notes": self.notes,
        }


def read_manifest(path: Path) -> dict[str, ManifestEntry]:
    if not path.exists():
        return {}

    entries: dict[str, ManifestEntry] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = {field: row.get(field, "") for field in MANIFEST_FIELDS}
            entries[normalized["path"]] = ManifestEntry(**normalized)
    return entries


def write_manifest(path: Path, entries: dict[str, ManifestEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for entry in sorted(entries.values(), key=lambda item: item.path):
            writer.writerow(entry.to_row())
