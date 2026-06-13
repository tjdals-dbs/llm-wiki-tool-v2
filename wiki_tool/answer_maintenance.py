from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import DomainConfig


def analyze_answer_candidates(config: DomainConfig) -> dict[str, Any]:
    answer_pages = _scan_answer_pages(config)
    concept_pages = _scan_concept_pages(config)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for page in answer_pages:
        item = _candidate_from_answer_page(page, concept_pages)
        if item["action"] == "candidate":
            candidates.append(item)
        else:
            skipped.append(item)

    return {
        "candidate_count": len(candidates),
        "skipped_count": len(skipped),
        "candidates": candidates,
        "skipped": skipped,
        "answers": answer_pages,
    }


def _scan_answer_pages(config: DomainConfig) -> list[dict[str, Any]]:
    answers_dir = config.wiki_dir / "answers"
    if not answers_dir.exists():
        return []
    answers_root = answers_dir.resolve()
    pages: list[dict[str, Any]] = []
    for path in sorted(answers_dir.rglob("*.md")):
        resolved = path.resolve()
        if resolved != answers_root and answers_root not in resolved.parents:
            continue
        pages.append(_parse_answer_page(config, path))
    return pages


def _parse_answer_page(config: DomainConfig, path: Path) -> dict[str, Any]:
    relative = path.relative_to(config.root).as_posix()
    base = {
        "path": relative,
        "title": path.stem,
        "question": "",
        "answer_preview": "",
        "answer": "",
        "used_pages": [],
        "related_pages": [],
        "evidence": [],
        "evidence_count": 0,
        "status": "",
        "created": "",
        "updated": "",
        "malformed": False,
        "parse_error": "",
    }
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {**base, "malformed": True, "parse_error": str(exc)}

    title = _title(content) or path.stem
    answer_section = _section_text(content, "Answer")
    maintenance = _metadata(content)
    evidence = _evidence_items(content)
    answer = answer_section or ""
    return {
        **base,
        "title": title,
        "question": maintenance.get("question", ""),
        "answer": answer,
        "answer_preview": _preview(answer),
        "used_pages": _page_paths(content, "Used Pages"),
        "related_pages": _page_paths(content, "Related Pages"),
        "evidence": evidence,
        "evidence_count": len(evidence),
        "status": maintenance.get("status", ""),
        "created": maintenance.get("created", ""),
        "updated": maintenance.get("updated", ""),
        "malformed": answer_section is None,
    }


def _candidate_from_answer_page(page: dict[str, Any], concept_pages: list[dict[str, str]]) -> dict[str, Any]:
    candidate_title = str(page.get("title") or page.get("question") or Path(str(page.get("path", "answer"))).stem)
    used_pages = list(page.get("used_pages") or [])
    evidence_count = int(page.get("evidence_count", 0) or 0)
    base = {
        "answer_path": page.get("path", ""),
        "candidate_title": candidate_title,
        "used_pages": used_pages,
        "evidence_count": evidence_count,
        "existing_concept_matches": _existing_concept_matches(page, concept_pages),
        "question": page.get("question", ""),
        "answer_preview": page.get("answer_preview", ""),
        "status": page.get("status", ""),
        "created": page.get("created", ""),
        "updated": page.get("updated", ""),
    }
    skip_reason = _skip_reason(page)
    if skip_reason:
        return {**base, "action": "skip", "candidate_reason": skip_reason}
    return {
        **base,
        "action": "candidate",
        "candidate_reason": "근거 문서가 있어 concept 반영 후보입니다.",
    }


def _skip_reason(page: dict[str, Any]) -> str:
    if page.get("malformed"):
        return "malformed answer page라 concept 반영 후보에서 제외합니다."
    status = str(page.get("status") or "").strip()
    if status == "no_evidence":
        return "status가 no_evidence라 concept 반영 후보에서 제외합니다."
    if not str(page.get("answer") or "").strip():
        return "answer 본문이 비어 있어 concept 반영 후보에서 제외합니다."
    if not page.get("used_pages") and int(page.get("evidence_count", 0) or 0) <= 0:
        return "근거 문서가 없어 concept 반영 후보에서 제외합니다."
    return ""


def _scan_concept_pages(config: DomainConfig) -> list[dict[str, str]]:
    concept_dir = config.wiki_dir / "concepts"
    if not concept_dir.exists():
        return []
    concept_root = concept_dir.resolve()
    pages: list[dict[str, str]] = []
    for path in sorted(concept_dir.rglob("*.md")):
        resolved = path.resolve()
        if resolved != concept_root and concept_root not in resolved.parents:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            content = ""
        pages.append(
            {
                "path": path.relative_to(config.root).as_posix(),
                "title": _title(content) or path.stem,
                "stem": path.stem,
            }
        )
    return pages


def _existing_concept_matches(page: dict[str, Any], concept_pages: list[dict[str, str]]) -> list[str]:
    paths: list[str] = []
    referenced = set(page.get("used_pages") or [])
    referenced.update(item.get("path", "") for item in page.get("evidence", []) if item.get("path"))
    title_key = _normalize_title(str(page.get("title") or page.get("question") or ""))
    for concept in concept_pages:
        concept_path = concept["path"]
        if concept_path in referenced or concept_path.replace("\\", "/") in referenced:
            paths.append(concept_path)
            continue
        if title_key and title_key in {
            _normalize_title(concept.get("title", "")),
            _normalize_title(concept.get("stem", "")),
        }:
            paths.append(concept_path)
    return _dedupe(paths)


def _title(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _section_text(content: str, heading: str) -> str | None:
    lines = _section_lines(content, heading)
    if lines is None:
        return None
    return "\n".join(lines).strip()


def _section_lines(content: str, heading: str) -> list[str] | None:
    marker = f"## {heading}"
    lines = content.splitlines()
    in_section = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            collected.append(line)
    return collected if in_section else None


def _metadata(content: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in _section_lines(content, "Maintenance Notes") or []:
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _page_paths(content: str, heading: str) -> list[str]:
    paths: list[str] = []
    for line in _section_lines(content, heading) or []:
        value = _bullet_value(line)
        if not value or _is_none_value(value):
            continue
        paths.append(_extract_markdown_link_target(value) or value)
    return _dedupe(paths)


def _evidence_items(content: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in _section_lines(content, "Evidence") or []:
        value = _bullet_value(line)
        if not value or _is_none_value(value):
            continue
        if ":" in value:
            path, text = value.split(":", 1)
            items.append({"path": path.strip(), "text": text.strip()})
        else:
            items.append({"path": "", "text": value.strip()})
    return items


def _bullet_value(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return ""
    return stripped[2:].strip()


def _extract_markdown_link_target(value: str) -> str:
    match = re.search(r"\[[^\]]+\]\(([^)]+)\)", value)
    return match.group(1).strip() if match else ""


def _is_none_value(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized in {"none", "없음", "?놁쓬"} or "놁쓬" in normalized


def _preview(value: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _normalize_title(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
