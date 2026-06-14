from __future__ import annotations

import re
import posixpath
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


def draft_answer_concept_updates(config: DomainConfig) -> dict[str, Any]:
    analysis = analyze_answer_candidates(config)
    answer_by_path = {page["path"]: page for page in analysis.get("answers", [])}
    drafts: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in [*analysis.get("candidates", []), *analysis.get("skipped", [])]:
        page = answer_by_path.get(str(candidate.get("answer_path", "")), {})
        draft = _draft_from_candidate(candidate, page)
        if draft["draft_action"] == "skip":
            skipped.append(draft)
        else:
            drafts.append(draft)

    return {
        "draft_count": len(drafts),
        "skipped_count": len(skipped),
        "drafts": drafts,
        "skipped": skipped,
        "candidate_count": analysis.get("candidate_count", 0),
    }


def apply_answer_concept_updates(
    config: DomainConfig,
    draft_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = draft_result if draft_result is not None else draft_answer_concept_updates(config)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for draft in result.get("drafts", []):
        application = _apply_answer_concept_draft(config, draft)
        if application["status"] == "applied":
            applied.append(application)
        else:
            skipped.append(application)

    for draft in result.get("skipped", []):
        skipped.append(
            {
                "status": "skipped",
                "answer_path": draft.get("answer_path", ""),
                "target_concept_path": draft.get("target_concept_path", ""),
                "reason": draft.get("reason", "draft skipped"),
            }
        )

    graph_refreshed = False
    navigation_refreshed = False
    if applied:
        from .graph import build_wiki_graph
        from .navigation import refresh_navigation_pages

        build_wiki_graph(config)
        refresh_navigation_pages(config)
        graph_refreshed = True
        navigation_refreshed = True

    if applied or skipped:
        _append_answer_concept_update_log(config, applied, skipped)

    return {
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "navigation_refreshed": navigation_refreshed,
        "graph_refreshed": graph_refreshed,
    }


def _apply_answer_concept_draft(config: DomainConfig, draft: dict[str, Any]) -> dict[str, Any]:
    answer_path = str(draft.get("answer_path") or "")
    target_concept_path = str(draft.get("target_concept_path") or "")
    base = {
        "answer_path": answer_path,
        "target_concept_path": target_concept_path,
    }
    if draft.get("draft_action") != "update_existing_concept":
        return {
            **base,
            "status": "skipped",
            "reason": "new concept candidates require review before concept page creation.",
        }
    if not _draft_has_source_evidence(draft):
        return {**base, "status": "skipped", "reason": "source evidence is required before concept update."}
    concept_path = _safe_wiki_file(config, target_concept_path, required_part="/concepts/")
    if concept_path is None or not concept_path.exists():
        return {**base, "status": "skipped", "reason": "target concept page was not found."}
    summary = str(draft.get("draft_summary") or "").strip()
    if not summary:
        return {**base, "status": "skipped", "reason": "draft summary is empty."}

    marker = _answer_update_marker(answer_path)
    content = concept_path.read_text(encoding="utf-8")
    if marker in content:
        return {**base, "status": "skipped", "reason": "already applied to target concept."}

    note = _render_answer_update_note(config, target_concept_path, draft, marker)
    updated = _append_agent_update_section(content, note)
    concept_path.write_text(updated, encoding="utf-8")
    return {**base, "status": "applied", "reason": "answer-derived note appended to concept page."}


def _draft_has_source_evidence(draft: dict[str, Any]) -> bool:
    paths: list[str] = []
    paths.extend(str(item.get("path") or "") for item in draft.get("evidence", []) or [])
    paths.extend(str(path or "") for path in draft.get("used_pages", []) or [])
    return any(_is_source_page_path(path) for path in paths)


def _safe_wiki_file(config: DomainConfig, relative_path: str, *, required_part: str = "") -> Path | None:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    if not normalized.startswith("wiki/") or ".." in Path(normalized).parts:
        return None
    if required_part and required_part not in f"/{normalized}":
        return None
    path = (config.root / normalized).resolve()
    wiki_root = config.wiki_dir.resolve()
    if path != wiki_root and wiki_root not in path.parents:
        return None
    return path


def _answer_update_marker(answer_path: str) -> str:
    return f"<!-- answer-derived: {answer_path} -->"


def _render_answer_update_note(
    config: DomainConfig,
    target_concept_path: str,
    draft: dict[str, Any],
    marker: str,
) -> str:
    answer_path = str(draft.get("answer_path") or "")
    answer_link = _wiki_relative_link(target_concept_path, answer_path)
    source_links = _source_evidence_links(config, target_concept_path, draft)
    source_text = ", ".join(source_links) if source_links else "source evidence recorded in answer page"
    summary = _single_line(str(draft.get("draft_summary") or ""))
    return "\n".join(
        [
            marker,
            f"- From [{Path(answer_path).stem}]({answer_link}): {summary}",
            f"  - source evidence: {source_text}",
        ]
    )


def _source_evidence_links(config: DomainConfig, target_concept_path: str, draft: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in draft.get("evidence", []) or []:
        path = str(item.get("path") or "")
        if _is_source_page_path(path):
            paths.append(path)
    for path in draft.get("used_pages", []) or []:
        if _is_source_page_path(str(path or "")):
            paths.append(str(path))
    links: list[str] = []
    for path in _dedupe(paths):
        normalized = _normalize_wiki_source_path(path)
        if not normalized:
            continue
        target = _safe_wiki_file(config, normalized)
        if target is not None and target.exists():
            links.append(f"[{Path(normalized).stem}]({_wiki_relative_link(target_concept_path, normalized)})")
        else:
            links.append(normalized)
    return links


def _normalize_wiki_source_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    normalized = normalized.split("#", 1)[0].split("?", 1)[0].lstrip("./")
    if normalized.startswith("wiki/sources/"):
        return normalized
    if normalized.startswith("sources/"):
        return f"wiki/{normalized}"
    return ""


def _wiki_relative_link(from_path: str, target_path: str) -> str:
    if not target_path:
        return ""
    source_parent = posixpath.dirname(from_path.replace("\\", "/")) or "."
    normalized_target = target_path.replace("\\", "/")
    return posixpath.relpath(normalized_target, start=source_parent)


def _append_agent_update_section(content: str, note: str) -> str:
    section = "## Answer-Derived Notes"
    stripped = content.rstrip()
    if section not in content:
        return f"{stripped}\n\n{section}\n\n{note}\n"
    before, after = content.split(section, 1)
    return f"{before}{section}{after.rstrip()}\n\n{note}\n"


def _append_answer_concept_update_log(
    config: DomainConfig,
    applied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    config.wiki_dir.mkdir(parents=True, exist_ok=True)
    path = config.wiki_dir / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Wiki Log\n\n"
    lines: list[str] = []
    for item in applied:
        lines.append(
            f"- answer concept update applied: {item.get('answer_path', '')} -> {item.get('target_concept_path', '')}"
        )
    for item in skipped:
        lines.append(
            f"- answer concept update skipped: {item.get('answer_path', '')}, reason={item.get('reason', '')}"
        )
    if not lines:
        return
    path.write_text(existing.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


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
        "evidence": list(page.get("evidence") or []),
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


def _draft_from_candidate(candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    answer_path = str(candidate.get("answer_path") or "")
    evidence = list(page.get("evidence") or candidate.get("evidence") or [])
    used_pages = list(candidate.get("used_pages") or [])
    candidate_title = str(candidate.get("candidate_title") or "").strip()
    existing_matches = list(candidate.get("existing_concept_matches") or [])
    base = {
        "answer_path": answer_path,
        "target_concept_path": existing_matches[0] if existing_matches else "",
        "candidate_title": candidate_title,
        "draft_summary": _draft_summary(str(page.get("answer") or candidate.get("answer_preview") or "")),
        "evidence": evidence,
        "used_pages": used_pages,
        "reason": "",
    }
    skip_reason = _draft_skip_reason(candidate, page, evidence, candidate_title)
    if skip_reason:
        return {**base, "draft_action": "skip", "reason": skip_reason}
    if existing_matches:
        return {
            **base,
            "draft_action": "update_existing_concept",
            "reason": "existing concept match가 있어 기존 concept 반영 초안으로 분류했습니다.",
        }
    return {
        **base,
        "draft_action": "new_concept_candidate",
        "reason": "기존 concept match가 없어 새 concept 후보 초안으로 분류했습니다.",
    }


def _draft_skip_reason(
    candidate: dict[str, Any],
    page: dict[str, Any],
    evidence: list[dict[str, str]],
    candidate_title: str,
) -> str:
    if candidate.get("action") == "skip":
        return str(candidate.get("candidate_reason") or "answer candidate가 skip 상태입니다.")
    if str(candidate.get("status") or page.get("status") or "") != "ok":
        return "status가 ok가 아니라 concept draft 대상에서 제외합니다."
    if not str(page.get("answer") or candidate.get("answer_preview") or "").strip():
        return "answer 본문이 비어 있어 concept draft 대상에서 제외합니다."
    if not _has_source_evidence(candidate, page, evidence):
        return "source evidence가 없어 concept draft 대상에서 제외합니다."
    if _is_generic_candidate_title(candidate_title):
        return "candidate title이 비어 있거나 너무 일반적이라 concept draft 대상에서 제외합니다."
    return ""


def _has_source_evidence(
    candidate: dict[str, Any],
    page: dict[str, Any],
    evidence: list[dict[str, str]],
) -> bool:
    paths: list[str] = []
    paths.extend(str(item.get("path") or "") for item in evidence)
    paths.extend(str(path or "") for path in candidate.get("used_pages", []) or [])
    paths.extend(str(path or "") for path in page.get("used_pages", []) or [])
    return any(_is_source_page_path(path) for path in paths)


def _is_source_page_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip()
    normalized = normalized.split("#", 1)[0].split("?", 1)[0].lstrip("./")
    return normalized.startswith("wiki/sources/") or normalized.startswith("sources/")


def _draft_summary(answer: str) -> str:
    return _preview(answer, limit=240)


def _is_generic_candidate_title(value: str) -> bool:
    normalized = _normalize_title(value)
    if len(normalized) < 2:
        return True
    return normalized in {"answer", "answers", "question", "questions", "page", "concept", "답변", "질문", "문서", "개념"}


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


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
