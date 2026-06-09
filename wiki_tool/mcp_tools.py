from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agent_hooks import (
    draft_concept_update_with_agent as hook_draft_concept_update_with_agent,
    draft_source_summary_with_agent as hook_draft_source_summary_with_agent,
    review_wiki_changes_with_agent as hook_review_wiki_changes_with_agent,
)
from .agent_provider import PROVIDER_CLAUDE, PROVIDER_CODEX, PROVIDER_RULE_BASED, load_agent_provider_config
from .claude_agent import ClaudeAgentBridge
from .codex_agent import CodexAgentBridge
from .config import DomainConfig
from .graph import build_wiki_graph, get_related_pages as graph_related_pages
from .lint import run_wiki_lint as core_run_wiki_lint
from .organizer import organize_pending_sources as core_organize_pending_sources
from .scanner import scan_raw_sources as core_scan_raw_sources
from .summarizer import summarize_new_sources as core_summarize_new_sources


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
        query_terms = _query_terms(query)
        matches: list[dict[str, Any]] = []
        for page in self.list_wiki_pages():
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
        seen = {item["path"] for item in direct}
        context = list(direct)
        for item in direct:
            for related in self.get_related_pages(item["path"], depth=1):
                if len(context) >= limit:
                    return context
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
        if provider_config.provider == PROVIDER_CODEX:
            context = self.ask_wiki_context(query, limit=5)
            evidence = self._collect_answer_evidence(query, context)
            codex_result = CodexAgentBridge(provider_config).run_answer(query, wiki_context=context, evidence=evidence)
            validation_error = _codex_answer_validation_error(codex_result, evidence)
            if codex_result.ok and not validation_error:
                payload = codex_result.to_answer_payload()
                payload["fallback"] = False
                return payload
            fallback = self._answer_question_rule_based(query, context=context, evidence=evidence)
            fallback["provider"] = "rule_based"
            fallback["fallback"] = True
            fallback["fallback_reason"] = codex_result.error or f"Codex answer draft invalid: {validation_error}"
            fallback["codex_status"] = codex_result.status if not validation_error else "codex_invalid_answer"
            return fallback
        if provider_config.provider == PROVIDER_CLAUDE:
            context = self.ask_wiki_context(query, limit=5)
            evidence = self._collect_answer_evidence(query, context)
            claude_result = ClaudeAgentBridge(provider_config).run_answer(query, wiki_context=context, evidence=evidence)
            validation_error = _codex_answer_validation_error(claude_result, evidence)
            if claude_result.ok and not validation_error:
                payload = claude_result.to_answer_payload()
                payload["fallback"] = False
                return payload
            fallback = self._answer_question_rule_based(query, context=context, evidence=evidence)
            fallback["provider"] = "rule_based"
            fallback["fallback"] = True
            fallback["fallback_reason"] = claude_result.error or f"Claude answer draft invalid: {validation_error}"
            fallback["claude_status"] = claude_result.status if not validation_error else "claude_invalid_answer"
            return fallback
        if provider_config.provider != PROVIDER_RULE_BASED:
            answer = self._answer_question_rule_based(query)
            answer["provider"] = "rule_based"
            answer["fallback"] = True
            answer["fallback_reason"] = (
                f"{provider_config.provider} provider는 아직 실행 adapter가 없어 rule-based fallback을 사용합니다."
            )
            answer["codex_status"] = "unsupported_provider_fallback"
            return answer
        answer = self._answer_question_rule_based(query)
        answer["provider"] = "rule_based"
        answer["fallback"] = False
        return answer

    def _answer_question_rule_based(
        self,
        query: str,
        *,
        context: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        context = context if context is not None else self.ask_wiki_context(query, limit=5)
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
    ) -> dict[str, str]:
        answer_dir = self.config.wiki_dir / "answers"
        answer_dir.mkdir(parents=True, exist_ok=True)
        path = answer_dir / f"{_slug(question)}.md"
        path.write_text(
            _render_answer_page(
                question=question,
                answer=answer,
                used_pages=used_pages or [],
                related_pages=related_pages or [],
                evidence=evidence or [],
                status=status,
            ),
            encoding="utf-8",
        )
        return {"path": path.relative_to(self.config.root).as_posix(), "status": status}

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
    if not str(result.answer or "").strip():
        return "missing_answer"
    if result.status == "no_evidence":
        return "" if not local_evidence else "ignored_available_evidence"
    if result.status != "ok":
        return f"unsupported_status:{result.status}"
    if not result.evidence and not result.used_pages:
        return "missing_evidence"
    return ""


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
    question: str,
    answer: str,
    used_pages: list[dict[str, Any]],
    related_pages: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    status: str,
) -> str:
    return "\n".join(
        [
            f"# {question}",
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
            f"- status: {status}",
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


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-").lower()
    return normalized or "answer"
