from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .answer_maintenance import (
    analyze_answer_candidates,
    apply_answer_concept_updates,
    draft_answer_concept_updates,
)
from .answer_save_decision import decide_answer_save
from .agent_hooks import (
    draft_concept_update_with_agent as hook_draft_concept_update_with_agent,
    draft_source_summary_with_agent as hook_draft_source_summary_with_agent,
    review_wiki_changes_with_agent as hook_review_wiki_changes_with_agent,
)
from .agent_output import is_readiness_response
from .agent_provider import PROVIDER_CODEX, PROVIDER_GEMINI, PROVIDER_RULE_BASED, load_agent_provider_config
from .agent_prompts import build_gemini_answer_prompt
from .codex_agent import CodexAgentBridge
from .config import DomainConfig
from .gemini_agent import GeminiAgentBridge
from .graph import build_wiki_graph, get_related_pages as graph_related_pages
from .lint import run_wiki_lint as core_run_wiki_lint
from .organizer import organize_pending_sources as core_organize_pending_sources
from .scanner import scan_raw_sources as core_scan_raw_sources
from .summarizer import summarize_new_sources as core_summarize_new_sources


ANSWER_CONTEXT_PAGE_TYPES = {"source", "concept"}


class WikiToolAdapter:
    def __init__(self, config: DomainConfig) -> None:
        self.config = config

    def list_wiki_pages(self, page_type: str | None = None) -> list[dict[str, str]]:
        pages: list[dict[str, str]] = []
        if not self.config.wiki_dir.exists():
            return pages
        for path in sorted(self.config.wiki_dir.rglob("*.md")):
            relative = path.relative_to(self.config.root).as_posix()
            detected_type = _page_type(relative)
            if page_type is None or detected_type == page_type:
                pages.append({"path": relative, "type": detected_type, "title": _title(path)})
        return pages

    def read_wiki_page(self, path: str) -> str:
        wiki_path = self._safe_wiki_path(path)
        return wiki_path.read_text(encoding="utf-8")

    def search_wiki(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._search_wiki_pages(query, limit=limit)

    def _search_wiki_pages(
        self,
        query: str,
        *,
        limit: int = 10,
        page_types: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_terms = _query_terms(query)
        matches: list[dict[str, Any]] = []
        for page in self.list_wiki_pages():
            if page_types is not None and page["type"] not in page_types:
                continue
            content = self.read_wiki_page(page["path"])
            content_lower = content.lower()
            title_lower = page["title"].lower()
            score = sum(content_lower.count(term) + title_lower.count(term) * 3 for term in query_terms)
            if score <= 0:
                continue
            matches.append(
                {
                    "path": page["path"],
                    "type": page["type"],
                    "title": page["title"],
                    "score": score,
                    "snippet": _snippet(content, query_terms[0] if query_terms else query),
                }
            )
        return sorted(matches, key=lambda item: (-item["score"], item["path"]))[:limit]

    def get_wiki_graph(self) -> dict[str, list[dict[str, Any]]]:
        return build_wiki_graph(self.config)

    def get_related_pages(self, path: str, depth: int = 1) -> list[dict[str, Any]]:
        self._safe_wiki_path(path)
        return graph_related_pages(self.config, path, depth=depth)

    def ask_wiki_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        direct = self.search_wiki(query, limit=limit)
        return self._expand_context_with_related_pages(direct, limit=limit)

    def _ask_answer_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        direct = self._search_wiki_pages(query, limit=limit, page_types=ANSWER_CONTEXT_PAGE_TYPES)
        return self._expand_context_with_related_pages(direct, limit=limit, page_types=ANSWER_CONTEXT_PAGE_TYPES)

    def _expand_context_with_related_pages(
        self,
        direct: list[dict[str, Any]],
        *,
        limit: int,
        page_types: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        seen = {item["path"] for item in direct}
        context = list(direct)
        for item in direct:
            for related in self.get_related_pages(item["path"], depth=1):
                if len(context) >= limit:
                    return context
                if page_types is not None and related["type"] not in page_types:
                    continue
                if related["path"] in seen:
                    continue
                seen.add(related["path"])
                content = self.read_wiki_page(related["path"])
                context.append(
                    {
                        "path": related["path"],
                        "type": related["type"],
                        "title": related["label"],
                        "score": 0,
                        "snippet": _first_nonempty_line(content),
                    }
                )
        return context[:limit]

    def answer_question(self, query: str) -> dict[str, Any]:
        provider_config = load_agent_provider_config("answer")
        context = self._ask_answer_context(query, limit=5)
        saved_context = self._saved_answer_reuse_context(query)
        context = _merge_context_pages(saved_context.get("used_pages", []), context, limit=5)
        evidence = self._collect_answer_evidence(query, context)
        evidence = _dedupe_evidence([*saved_context.get("evidence", []), *evidence])[:3]
        if provider_config.provider == PROVIDER_CODEX:
            codex_result = CodexAgentBridge(provider_config).run_answer(query, wiki_context=context, evidence=evidence)
            validation_error = _codex_answer_validation_error(codex_result, evidence)
            if codex_result.ok and not validation_error:
                payload = codex_result.to_answer_payload()
                payload["fallback"] = False
                return _answer_with_save_decision(query, payload)
            if _can_try_answer_provider_failover(provider_config.provider):
                gemini_config = _answer_failover_provider_config(PROVIDER_GEMINI)
                gemini_payload, gemini_error, gemini_status = self._run_gemini_answer_provider(
                    gemini_config,
                    query,
                    context,
                    evidence,
                )
                if gemini_payload is not None:
                    gemini_payload["codex_status"] = codex_result.status if not validation_error else "codex_invalid_answer"
                    return _answer_with_save_decision(query, gemini_payload)
            fallback = self._answer_question_rule_based(query, context=context, evidence=evidence)
            fallback["provider"] = "rule_based"
            fallback["fallback"] = True
            fallback["fallback_reason"] = codex_result.error or f"Codex answer draft invalid: {validation_error}"
            fallback["codex_status"] = codex_result.status if not validation_error else "codex_invalid_answer"
            if _can_try_answer_provider_failover(provider_config.provider):
                fallback["fallback_reason"] = _combine_fallback_reasons(
                    fallback["fallback_reason"],
                    gemini_error,
                    provider="Gemini",
                )
                fallback["gemini_status"] = gemini_status
            return _answer_with_save_decision(query, fallback)
        if provider_config.provider == PROVIDER_GEMINI:
            gemini_payload, gemini_error, gemini_status = self._run_gemini_answer_provider(
                provider_config,
                query,
                context,
                evidence,
            )
            if gemini_payload is not None:
                return _answer_with_save_decision(query, gemini_payload)
            if _can_try_answer_provider_failover(provider_config.provider):
                codex_config = _answer_failover_provider_config(PROVIDER_CODEX)
                codex_result = CodexAgentBridge(codex_config).run_answer(query, wiki_context=context, evidence=evidence)
                validation_error = _codex_answer_validation_error(codex_result, evidence)
                if codex_result.ok and not validation_error:
                    payload = codex_result.to_answer_payload()
                    payload["fallback"] = False
                    payload["gemini_status"] = gemini_status
                    return _answer_with_save_decision(query, payload)
            fallback = self._answer_question_rule_based(query, context=context, evidence=evidence)
            fallback["provider"] = "rule_based"
            fallback["fallback"] = True
            fallback["fallback_reason"] = gemini_error
            fallback["gemini_status"] = gemini_status
            if _can_try_answer_provider_failover(provider_config.provider):
                fallback["fallback_reason"] = _combine_fallback_reasons(
                    fallback["fallback_reason"],
                    codex_result.error or f"Codex answer draft invalid: {validation_error}",
                    provider="Codex",
                )
                fallback["codex_status"] = codex_result.status if not validation_error else "codex_invalid_answer"
            return _answer_with_save_decision(query, fallback)
        if provider_config.provider != PROVIDER_RULE_BASED:
            answer = self._answer_question_rule_based(query, context=context, evidence=evidence)
            answer["provider"] = "rule_based"
            answer["fallback"] = True
            answer["fallback_reason"] = (
                f"{provider_config.provider} provider는 아직 실행 adapter가 없어 rule-based fallback을 사용합니다."
            )
            answer["codex_status"] = "unsupported_provider_fallback"
            return _answer_with_save_decision(query, answer)
        answer = self._answer_question_rule_based(query, context=context, evidence=evidence)
        answer["provider"] = "rule_based"
        answer["fallback"] = False
        return _answer_with_save_decision(query, answer)

    def _run_gemini_answer_provider(
        self,
        provider_config: Any,
        query: str,
        context: list[dict[str, Any]],
        evidence: list[dict[str, str]],
    ) -> tuple[dict[str, Any] | None, str, str]:
        prompt = build_gemini_answer_prompt(query, wiki_context=context, evidence=evidence)
        gemini_result = GeminiAgentBridge(provider_config).run_prompt(prompt)
        payload = _gemini_payload_with_local_evidence(gemini_result.to_answer_payload(), context, evidence)
        validation_error = _agent_answer_validation_error(payload, evidence) if gemini_result.ok else ""
        if gemini_result.ok and not validation_error:
            payload["fallback"] = False
            return payload, "", gemini_result.status
        reason = gemini_result.error or f"Gemini answer draft invalid: {validation_error}"
        status = gemini_result.status if not validation_error else "gemini_invalid_answer"
        return None, reason, status

    def _answer_question_rule_based(
        self,
        query: str,
        *,
        context: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        context = context if context is not None else self._ask_answer_context(query, limit=5)
        evidence = evidence if evidence is not None else self._collect_answer_evidence(query, context)
        if not evidence:
            return {
                "status": "no_evidence",
                "answer": "근거가 부족합니다. 현재 wiki에서 질문에 답할 수 있는 source evidence를 찾지 못했습니다.",
                "used_pages": [],
                "related_pages": [],
                "evidence": [],
            }

        used_paths = {evidence[0]["path"]}
        used_pages = [item for item in context if item["path"] in used_paths]
        related_pages = [item for item in context if item["path"] not in used_paths]
        answer = _compose_evidence_answer(query, evidence)
        return {
            "status": "ok",
            "answer": answer,
            "used_pages": used_pages,
            "related_pages": related_pages,
            "evidence": evidence,
        }

    def _collect_answer_evidence(self, query: str, context: list[dict[str, Any]]) -> list[dict[str, str]]:
        query_terms = _query_terms(query)
        collected: list[dict[str, str]] = []
        for page in context:
            if page["type"] not in ANSWER_CONTEXT_PAGE_TYPES:
                continue
            content = self.read_wiki_page(page["path"])
            for evidence_text in _extract_page_evidence(content, page["type"], query_terms):
                collected.append(
                    {
                        "path": page["path"],
                        "type": page["type"],
                        "title": page["title"],
                        "text": evidence_text,
                    }
                )
        return _dedupe_evidence(collected)[:3]

    def _saved_answer_reuse_context(self, query: str) -> dict[str, list[dict[str, Any]]]:
        answer_page = self._find_reusable_answer_page(query)
        if not answer_page:
            return {"used_pages": [], "evidence": []}
        pages_by_path = {page["path"]: page for page in self.list_wiki_pages()}
        used_pages: list[dict[str, Any]] = []
        for path in answer_page.get("used_paths", []):
            page = pages_by_path.get(path)
            if page and page.get("type") in ANSWER_CONTEXT_PAGE_TYPES:
                used_pages.append(
                    {
                        "path": page["path"],
                        "type": page["type"],
                        "title": page["title"],
                        "score": 0,
                        "snippet": _first_nonempty_line(self.read_wiki_page(page["path"])),
                    }
                )
        evidence: list[dict[str, Any]] = []
        for item in answer_page.get("evidence", []):
            path = str(item.get("path") or "")
            page = pages_by_path.get(path, {})
            page_type = str(page.get("type") or _page_type(path))
            if page_type not in ANSWER_CONTEXT_PAGE_TYPES:
                continue
            evidence.append(
                {
                    "path": path,
                    "type": page_type,
                    "title": str(page.get("title") or Path(path).stem),
                    "text": str(item.get("text") or "").strip(),
                }
            )
        return {"used_pages": used_pages, "evidence": _dedupe_evidence(evidence)}

    def _find_reusable_answer_page(self, query: str) -> dict[str, Any] | None:
        answers_dir = self.config.wiki_dir / "answers"
        if not answers_dir.exists():
            return None
        answers_root = answers_dir.resolve()
        candidates: list[dict[str, Any]] = []
        for path in sorted(answers_dir.rglob("*.md")):
            resolved = path.resolve()
            if resolved != answers_root and answers_root not in resolved.parents:
                continue
            page = _parse_saved_answer_page(self.config, path)
            if page.get("status") != "ok" or not page.get("evidence"):
                continue
            if _similar_question(query, str(page.get("question") or page.get("title") or "")) or _answer_page_matches_query(
                query,
                page,
            ):
                candidates.append(page)
        return candidates[0] if candidates else None

    def scan_raw_sources(self) -> dict[str, Any]:
        result = core_scan_raw_sources(self.config)
        return {"message": "raw source scan 완료", **asdict(result)}

    def summarize_new_sources(self, limit: int | None = None) -> dict[str, Any]:
        result = core_summarize_new_sources(self.config, limit=limit)
        refreshed = False
        if int(result.summarized_count or 0) + int(result.needs_review_count or 0) > 0:
            self.refresh_navigation_pages()
            refreshed = True
        return {"message": "source summary 생성 완료", **asdict(result), "navigation_refreshed": refreshed}

    def organize_pending_sources(self, limit: int | None = None) -> dict[str, Any]:
        result = core_organize_pending_sources(self.config, limit=limit)
        build_wiki_graph(self.config)
        self.refresh_navigation_pages()
        return {"message": "concept organization 완료", **asdict(result), "navigation_refreshed": True}

    def refresh_navigation_pages(self) -> dict[str, Any]:
        from .navigation import refresh_navigation_pages

        refresh_navigation_pages(self.config)
        return {"message": "navigation pages 갱신 완료", "navigation_refreshed": True}

    def analyze_answer_candidates(self) -> dict[str, Any]:
        return analyze_answer_candidates(self.config)

    def draft_answer_concept_updates(self) -> dict[str, Any]:
        return draft_answer_concept_updates(self.config)

    def apply_answer_concept_updates(self, draft_result: dict[str, Any] | None = None) -> dict[str, Any]:
        return apply_answer_concept_updates(self.config, draft_result=draft_result)

    def draft_source_summary_with_agent(self, source_text: str) -> dict[str, Any]:
        return hook_draft_source_summary_with_agent(source_text).as_dict()

    def draft_concept_update_with_agent(self, source_page: str) -> dict[str, Any]:
        return hook_draft_concept_update_with_agent(source_page).as_dict()

    def review_wiki_changes_with_agent(self, changes_summary: str) -> dict[str, Any]:
        return hook_review_wiki_changes_with_agent(changes_summary).as_dict()

    def apply_wiki_update(
        self,
        *,
        question: str,
        answer: str,
        used_pages: list[dict[str, Any]] | None = None,
        related_pages: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        status: str = "ok",
        suggested_title: str | None = None,
    ) -> dict[str, Any]:
        answer_dir = self.config.wiki_dir / "answers"
        answer_dir.mkdir(parents=True, exist_ok=True)
        title = (suggested_title or question).strip() or question
        path = self._answer_update_path(answer_dir, title=title, question=question, answer=answer)
        existed = path.exists()
        existing_created = _answer_metadata_value(path, "created") if existed else ""
        if existed:
            existing = _parse_saved_answer_page(self.config, path)
            if _similar_question(question, str(existing.get("question") or existing.get("title") or "")) and _similar_answer(
                answer,
                str(existing.get("answer") or ""),
            ):
                relative_path = path.relative_to(self.config.root).as_posix()
                return {
                    "path": relative_path,
                    "status": status,
                    "created": False,
                    "updated": False,
                    "unchanged": True,
                    "navigation_refreshed": False,
                    "graph_refreshed": False,
                }
        now = _utc_timestamp()
        created_at = existing_created or now
        updated_at = now
        path.write_text(
            _render_answer_page(
                title=title,
                question=question,
                answer=answer,
                used_pages=used_pages or [],
                related_pages=related_pages or [],
                evidence=evidence or [],
                status=status,
                created=created_at,
                updated=updated_at,
            ),
            encoding="utf-8",
        )
        self.refresh_navigation_pages()
        build_wiki_graph(self.config)
        relative_path = path.relative_to(self.config.root).as_posix()
        _append_answer_log(self.config.wiki_dir / "log.md", relative_path, updated=existed)
        return {
            "path": relative_path,
            "status": status,
            "created": not existed,
            "updated": existed,
            "unchanged": False,
            "navigation_refreshed": True,
            "graph_refreshed": True,
        }

    def _answer_update_path(self, answer_dir: Path, *, title: str, question: str, answer: str) -> Path:
        default_path = answer_dir / f"{_slug(title)}.md"
        if default_path.exists():
            return default_path
        answers_root = answer_dir.resolve()
        for path in sorted(answer_dir.rglob("*.md")):
            resolved = path.resolve()
            if resolved != answers_root and answers_root not in resolved.parents:
                continue
            existing = _parse_saved_answer_page(self.config, path)
            if _similar_question(question, str(existing.get("question") or existing.get("title") or "")):
                return path
            if _similar_answer(answer, str(existing.get("answer") or "")):
                return path
        return default_path

    def run_wiki_lint(self) -> dict[str, Any]:
        result = core_run_wiki_lint(self.config)
        return {"ok": result.ok, "issues": [asdict(issue) for issue in result.issues]}

    def _safe_wiki_path(self, path: str) -> Path:
        candidate = (self.config.root / path).resolve()
        if not (self.config.wiki_dir == candidate or self.config.wiki_dir in candidate.parents):
            raise ValueError(f"wiki 경로 밖은 읽을 수 없습니다: {path}")
        if not candidate.exists():
            raise FileNotFoundError(path)
        return candidate


def _page_type(path: str) -> str:
    if "/sources/" in path:
        return "source"
    if "/concepts/" in path:
        return "concept"
    if "/answers/" in path:
        return "answer"
    if path.endswith("index.md"):
        return "index"
    if path.endswith("overview.md"):
        return "overview"
    return "page"


def _answer_with_save_decision(question: str, answer: dict[str, Any]) -> dict[str, Any]:
    answer["save_decision"] = decide_answer_save(question, answer).as_dict()
    return answer


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _snippet(content: str, query: str) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    index = compact.lower().find(query.lower())
    if index < 0:
        return compact[:160]
    start = max(0, index - 60)
    end = min(len(compact), index + len(query) + 100)
    return compact[start:end]


def _extract_page_evidence(content: str, page_type: str, query_terms: list[str]) -> list[str]:
    section_order = ["Source Evidence", "Evidence", "Definition", "Summary"]
    candidates: list[str] = []
    for heading in section_order:
        candidates.extend(_section_values(content, heading))
    if not candidates and page_type in {"concept", "source"}:
        candidates.append(_first_nonempty_line(content))

    ranked = sorted(
        _dedupe_text(candidates),
        key=lambda item: (-_evidence_score(item, query_terms), len(item)),
    )
    return [_clean_evidence(item) for item in ranked if _evidence_score(item, query_terms) > 0][:3]


def _section_values(content: str, heading: str) -> list[str]:
    values: list[str] = []
    for line in _section_lines(content, heading):
        if line.startswith("- "):
            value = line[2:].strip()
            if value != "없음" and not value.startswith("[") and not _is_operational_evidence(value):
                values.append(value)
        elif line.strip() and not line.startswith("## ") and not _is_operational_evidence(line):
            values.append(line.strip())
    return values


def _section_lines(content: str, heading: str) -> list[str]:
    marker = f"## {heading}"
    lines = content.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip():
            collected.append(line.strip())
    return collected


def _section_text(content: str, heading: str) -> str:
    return "\n".join(_section_lines(content, heading)).strip()


def _metadata_value(content: str, key: str) -> str:
    prefix = f"- {key}:"
    for line in _section_lines(content, "Maintenance Notes"):
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_saved_answer_page(config: DomainConfig, path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return {"path": path.relative_to(config.root).as_posix(), "status": "", "evidence": []}
    return {
        "path": path.relative_to(config.root).as_posix(),
        "title": _title_from_content(content) or path.stem,
        "question": _metadata_value(content, "question"),
        "answer": _section_text(content, "Answer"),
        "used_paths": _answer_page_paths(content, "Used Pages"),
        "related_paths": _answer_page_paths(content, "Related Pages"),
        "evidence": _answer_page_evidence(content),
        "status": _metadata_value(content, "status"),
        "created": _metadata_value(content, "created"),
        "updated": _metadata_value(content, "updated"),
    }


def _title_from_content(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _answer_page_paths(content: str, heading: str) -> list[str]:
    paths: list[str] = []
    for line in _section_lines(content, heading):
        value = _answer_bullet_value(line)
        if not value or _answer_none_value(value):
            continue
        paths.append(value)
    return _dedupe_text(paths)


def _answer_page_evidence(content: str) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for line in _section_lines(content, "Evidence"):
        value = _answer_bullet_value(line)
        if not value or _answer_none_value(value) or ":" not in value:
            continue
        path, text = value.split(":", 1)
        normalized_path = path.strip()
        page_type = _page_type(normalized_path)
        if page_type not in ANSWER_CONTEXT_PAGE_TYPES:
            continue
        cleaned_text = text.strip()
        if cleaned_text:
            evidence.append({"path": normalized_path, "text": cleaned_text})
    return evidence


def _answer_bullet_value(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return ""
    return stripped[2:].strip()


def _answer_none_value(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized in {"none", "없음", "?놁쓬", ""}


def _merge_context_pages(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in [*primary, *extra]:
        path = str(item.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _similar_question(left: str, right: str) -> bool:
    left_tokens = _semantic_tokens(left)
    right_tokens = _semantic_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    if overlap and len(overlap) / max(1, min(len(left_tokens), len(right_tokens))) >= 0.5:
        return True
    return SequenceMatcher(None, _normalize_similarity_text(left), _normalize_similarity_text(right)).ratio() >= 0.72


def _similar_answer(left: str, right: str) -> bool:
    left_norm = _normalize_similarity_text(left)
    right_norm = _normalize_similarity_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.88


def _answer_page_matches_query(query: str, page: dict[str, Any]) -> bool:
    query_tokens = _semantic_tokens(query)
    if not query_tokens:
        return False
    parts = [
        str(page.get("title") or ""),
        str(page.get("question") or ""),
        str(page.get("answer") or ""),
        " ".join(str(item.get("text") or "") for item in page.get("evidence", []) or []),
    ]
    page_tokens = _semantic_tokens(" ".join(parts))
    return bool(query_tokens & page_tokens)


def _semantic_tokens(value: str) -> set[str]:
    stopwords = {
        "뭐야",
        "무엇인가",
        "설명해줘",
        "설명",
        "대해",
        "대한",
        "알려줘",
        "정의",
        "개념",
    }
    tokens: set[str] = set()
    for token in re.findall(r"[0-9A-Za-z가-힣]+", value.casefold()):
        stripped = _strip_common_korean_suffix(token)
        if len(stripped) >= 2 and stripped not in stopwords:
            tokens.add(stripped)
    return tokens


def _strip_common_korean_suffix(token: str) -> str:
    suffixes = ("으로", "에서", "에게", "에", "은", "는", "이", "가", "을", "를", "와", "과", "도")
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def _normalize_similarity_text(value: str) -> str:
    return "".join(sorted(_semantic_tokens(value))) or re.sub(r"\s+", "", value.casefold())


def _evidence_score(value: str, query_terms: list[str]) -> int:
    normalized = value.casefold()
    score = sum(4 for term in query_terms if term.casefold() in normalized)
    if "source evidence" in normalized:
        score -= 1
    if len(value) >= 12:
        score += 1
    return score


def _is_operational_evidence(value: str) -> bool:
    normalized = value.strip().casefold()
    if not normalized or normalized in {"---", "```"}:
        return True
    operational_prefixes = (
        "raw path:",
        "sha256:",
        "source type:",
        "ingest status:",
        "quality:",
        "warnings:",
        "recommended_actions:",
        "concept_count:",
        "concept_evidence_count:",
        "substantive_content_count:",
        "visual_summary_count:",
        "source_path:",
        "tool_trace:",
    )
    if normalized.startswith(operational_prefixes):
        return True
    return "raw extraction" in normalized or "extracted text" in normalized


def _clean_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = _clean_evidence(item)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _dedupe_evidence(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = (item["path"], item["text"].casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _codex_answer_validation_error(result: Any, local_evidence: list[dict[str, Any]]) -> str:
    if not result.ok:
        return ""
    return _agent_answer_validation_error(result.to_answer_payload(), local_evidence)


def _can_try_answer_provider_failover(primary_provider: str) -> bool:
    if primary_provider not in {PROVIDER_CODEX, PROVIDER_GEMINI}:
        return False
    strict_provider = os.environ.get("LLM_WIKI_ANSWER_PROVIDER", "").strip().casefold()
    return strict_provider not in {PROVIDER_CODEX, PROVIDER_GEMINI, PROVIDER_RULE_BASED}


def _answer_failover_provider_config(provider: str) -> Any:
    env = dict(os.environ)
    env["LLM_WIKI_ANSWER_PROVIDER"] = provider
    return load_agent_provider_config("answer", env=env, auto_detect=True)


def _combine_fallback_reasons(primary_reason: str, secondary_reason: str, *, provider: str) -> str:
    if not secondary_reason:
        return primary_reason
    if not primary_reason:
        return f"{provider}: {secondary_reason}"
    return f"{primary_reason}; {provider}: {secondary_reason}"


def _agent_answer_validation_error(payload: dict[str, Any], local_evidence: list[dict[str, Any]]) -> str:
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return "missing_answer"
    if is_readiness_response(answer):
        return "readiness_response"
    status = str(payload.get("status") or "")
    if status == "no_evidence":
        return "" if not local_evidence else "ignored_available_evidence"
    if status != "ok":
        return f"unsupported_status:{status}"
    if not payload.get("evidence") and not payload.get("used_pages"):
        return "missing_evidence"
    return ""


def _gemini_payload_with_local_evidence(
    payload: dict[str, Any],
    context: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(payload)
    if not result.get("evidence"):
        result["evidence"] = evidence
    if not result.get("used_pages"):
        evidence_paths = {str(item.get("path") or "") for item in result.get("evidence", []) if item.get("path")}
        result["used_pages"] = [item for item in context if item.get("path") in evidence_paths]
    if not result.get("related_pages"):
        used_paths = {str(item.get("path") or "") for item in result.get("used_pages", []) if item.get("path")}
        result["related_pages"] = [item for item in context if item.get("path") not in used_paths]
    result["provider"] = PROVIDER_GEMINI
    return result


def _compose_evidence_answer(query: str, evidence: list[dict[str, str]]) -> str:
    primary = evidence[0]["text"]
    secondary = evidence[1]["text"] if len(evidence) > 1 else ""
    question_type = _question_type(query)
    if question_type == "definition":
        return _join_answer_parts(
            [
                f"wiki 근거상 정의하면, {primary}",
                f"보조 근거로는 {secondary}" if secondary else "",
            ]
        )
    if question_type == "reason":
        return _join_answer_parts(
            [
                f"wiki 근거를 보면 핵심 이유는 {primary}",
                f"관련 메커니즘은 {secondary}" if secondary else "",
            ]
        )
    if question_type == "comparison":
        return _join_answer_parts(
            [
                f"wiki 근거상 비교의 기준은 {primary}",
                f"비교할 때 함께 볼 근거는 {secondary}" if secondary else "",
            ]
        )
    if question_type == "how":
        return _join_answer_parts(
            [
                f"wiki 근거상 활용 방법은 {primary}",
                f"실행하거나 해석할 때는 {secondary}" if secondary else "",
            ]
        )
    if len(evidence) == 1:
        return f"wiki 근거를 기준으로 답하면, {primary}"
    secondary = evidence[1]["text"]
    return f"wiki 근거를 기준으로 답하면, {primary} 추가 근거로 {secondary}"


def _question_type(query: str) -> str:
    normalized = query.casefold()
    if re.search(r"(차이|비교|다른|vs|versus)", normalized):
        return "comparison"
    if re.search(r"(어떻게|방법|절차|활용|사용|적용)", normalized):
        return "how"
    if re.search(r"(왜|이유|원인|메커니즘|기전)", normalized):
        return "reason"
    if re.search(r"(무엇|뭐|정의|이란|란\?)", normalized):
        return "definition"
    return "general"


def _join_answer_parts(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part.strip())


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw_term in re.findall(r"[0-9A-Za-z가-힣]+", query.lower()):
        stripped = _strip_korean_particle(raw_term)
        for candidate in [raw_term, stripped]:
            if candidate and len(candidate) >= 2 and candidate not in terms:
                terms.append(candidate)
    return terms or [query.lower()]


def _strip_korean_particle(term: str) -> str:
    particles = ["으로", "에서", "에게", "은", "는", "이", "가", "을", "를", "과", "와", "의"]
    for particle in particles:
        if term.endswith(particle) and len(term) > len(particle):
            return term[: -len(particle)]
    return term


def _first_nonempty_line(content: str) -> str:
    for line in content.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _render_answer_page(
    *,
    title: str,
    question: str,
    answer: str,
    used_pages: list[dict[str, Any]],
    related_pages: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    status: str,
    created: str,
    updated: str,
) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            "## Answer",
            "",
            answer,
            "",
            "## Used Pages",
            "",
            _page_bullets(used_pages),
            "",
            "## Evidence",
            "",
            _evidence_bullets(evidence),
            "",
            "## Related Pages",
            "",
            _page_bullets(related_pages),
            "",
            "## Maintenance Notes",
            "",
            f"- created: {created}",
            f"- updated: {updated}",
            f"- status: {status}",
            f"- question: {question}",
            "",
        ]
    )


def _page_bullets(pages: list[dict[str, Any]]) -> str:
    if not pages:
        return "- 없음"
    return "\n".join(f"- {page.get('path', '')}" for page in pages if page.get("path"))


def _evidence_bullets(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "- 없음"
    return "\n".join(
        f"- {item.get('path', '')}: {item.get('text', '')}"
        for item in evidence
        if item.get("path") and item.get("text")
    )


def _answer_metadata_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    prefix = f"- {key}:"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _append_answer_log(log_path: Path, answer_path: str, *, updated: bool) -> None:
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Wiki Log\n\n"
    action = "updated" if updated else "saved"
    line = f"- answer {action}: {answer_path}"
    log_path.write_text(existing.rstrip() + f"\n\n{line}\n", encoding="utf-8")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-").lower()
    return normalized or "answer"
