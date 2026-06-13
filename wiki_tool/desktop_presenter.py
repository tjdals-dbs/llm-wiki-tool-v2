from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .agent_provider import (
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    PROVIDER_RULE_BASED,
    load_agent_provider_config,
)
from .config import DomainConfig
from .mcp_registry import create_tool_registry


AGENT_PROVIDER_ROLES = ("answer", "ingest", "concept", "review")
AGENT_PROVIDER_DETAIL_DEFAULT_VISIBLE = False
AGENT_PROVIDER_SUPPORTED_ROLES = {
    PROVIDER_CODEX: frozenset(AGENT_PROVIDER_ROLES),
    PROVIDER_GEMINI: frozenset(),
    PROVIDER_RULE_BASED: frozenset(AGENT_PROVIDER_ROLES),
}


@dataclass(frozen=True)
class AgentRouteResult:
    route: str
    status: str
    answer: str
    used_pages: list[dict[str, Any]]
    related_pages: list[dict[str, Any]]
    question: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    save_decision: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class AgentWorkflowResult:
    message: str
    status_message: str = ""
    refresh_pages: bool = False


@dataclass(frozen=True)
class AgentAutoSaveResult:
    status_message: str
    refresh_pages: bool = False


@dataclass(frozen=True)
class AgentProviderRoleStatus:
    role: str
    provider: str
    model: str = ""
    fallback: bool = False

    @property
    def text(self) -> str:
        provider_text = self.provider
        if self.model:
            provider_text = f"{provider_text} / {self.model}"
        if self.fallback:
            provider_text = f"{provider_text} fallback"
        return f"{self.role}: {provider_text}"


@dataclass(frozen=True)
class AgentProviderPanelStatus:
    summary: str
    detail_lines: list[str]
    tooltip: str
    roles: list[AgentProviderRoleStatus]


def build_agent_provider_panel_status(env: Mapping[str, str] | None = None) -> AgentProviderPanelStatus:
    roles = [_agent_provider_role_status(role, env=env) for role in AGENT_PROVIDER_ROLES]
    answer = roles[0]
    summary_provider = answer.provider
    summary_model = answer.model
    summary = f"agent: {summary_provider}"
    if summary_model:
        summary = f"{summary} / {summary_model}"
    if answer.fallback:
        summary = f"{summary} fallback"
    detail_lines = [role.text for role in roles]
    return AgentProviderPanelStatus(summary=summary, detail_lines=detail_lines, tooltip="\n".join(detail_lines), roles=roles)


def toggle_agent_provider_detail_visible(current_visible: bool) -> bool:
    return not current_visible


def agent_provider_detail_toggle_label(visible: bool) -> str:
    return "접기" if visible else "자세히"


def _agent_provider_role_status(role: str, *, env: Mapping[str, str] | None = None) -> AgentProviderRoleStatus:
    config = load_agent_provider_config(role, env=env)
    supported_roles = AGENT_PROVIDER_SUPPORTED_ROLES.get(config.provider, frozenset())
    if role not in supported_roles:
        return AgentProviderRoleStatus(role=role, provider=PROVIDER_RULE_BASED, fallback=True)
    return AgentProviderRoleStatus(role=role, provider=config.provider, model=config.model)


class DirectAdapterAgentFallback:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def ask(self, query: str) -> AgentRouteResult:
        answer = self.adapter.answer_question(query)
        return _route_result_from_answer(answer, route="direct fallback", question=query)


class McpCodexAgentRoute:
    """GUI-facing route that asks through the local MCP tool registry first."""

    def __init__(
        self,
        config: DomainConfig,
        *,
        registry_factory: Callable[[DomainConfig], dict[str, Callable[..., Any]]] = create_tool_registry,
        fallback: DirectAdapterAgentFallback | None = None,
    ) -> None:
        self.config = config
        self.registry_factory = registry_factory
        self.fallback = fallback

    def ask(self, query: str) -> AgentRouteResult:
        provider = load_agent_provider_config("answer").provider
        if provider == PROVIDER_CODEX:
            route = "mcp/codex"
        elif provider == PROVIDER_RULE_BASED:
            route = "mcp/rule_based"
        else:
            route = "mcp/unsupported-provider fallback"
        try:
            registry = self.registry_factory(self.config)
            answer_tool = registry["answer_question"]
            answer = answer_tool(query)
            result = _route_result_from_answer(answer, route=route, question=query)
            if result.route == route and answer.get("fallback") and provider == PROVIDER_CODEX:
                return AgentRouteResult(
                    route="mcp/codex fallback",
                    status=result.status,
                    answer=result.answer,
                    used_pages=result.used_pages,
                    related_pages=result.related_pages,
                    question=result.question,
                    evidence=result.evidence,
                    save_decision=result.save_decision,
                    error=result.error,
                    fallback_reason=result.fallback_reason,
                )
            return result
        except Exception as exc:
            if self.fallback is None:
                raise
            result = self.fallback.ask(query)
            return AgentRouteResult(
                route="direct fallback",
                status=result.status,
                answer=result.answer,
                used_pages=result.used_pages,
                related_pages=result.related_pages,
                question=result.question,
                evidence=result.evidence,
                save_decision=result.save_decision,
                error=str(exc),
                fallback_reason="MCP route 실행 실패로 direct adapter fallback 사용",
            )


class DesktopGuiPresenter:
    def __init__(self, adapter: Any, *, agent_route: Any | None = None) -> None:
        self.adapter = adapter
        self.agent_route = agent_route or DirectAdapterAgentFallback(adapter)

    def scan_raw_sources(self) -> str:
        result = self.adapter.scan_raw_sources()
        return (
            "raw 스캔 완료: "
            f"새 파일 {result.get('new_count', 0)}개, "
            f"변경 {result.get('changed_count', 0)}개, "
            f"무시 {result.get('ignored_count', 0)}개"
        )

    def summarize_new_sources(self) -> str:
        result = self.adapter.summarize_new_sources()
        navigation = " navigation 갱신" if result.get("navigation_refreshed") else ""
        return (
            "source 요약 완료: "
            f"요약 {result.get('summarized_count', 0)}개, "
            f"Codex {result.get('codex_used_count', 0)}개, "
            f"fallback {result.get('fallback_count', 0)}개, "
            f"검토 필요 {result.get('needs_review_count', 0)}개"
            f"{navigation}"
        )

    def organize_pending_sources(self) -> str:
        result = self.adapter.organize_pending_sources()
        navigation = " navigation 갱신" if result.get("navigation_refreshed") else ""
        return (
            "concept 조직 완료: "
            f"승격 {result.get('promoted_count', 0)}개, "
            f"병합 {result.get('merged_count', 0)}개, "
            f"보류 {result.get('skipped_count', result.get('dropped_count', 0))}개, "
            f"fallback {result.get('fallback_count', 0)}개"
            f"{navigation}"
        )

    def run_wiki_lint(self) -> str:
        result = self.adapter.run_wiki_lint()
        if result.get("ok"):
            return "wiki lint 통과"
        issues = result.get("issues", [])
        return "wiki lint 실패:\n" + "\n".join(f"- {_short_path(str(item['path']))}: {item['message']}" for item in issues)

    def run_maintenance_workflow(self) -> str:
        raw_before = _raw_snapshot(self.adapter)
        scan = self.adapter.scan_raw_sources()
        summarize = self.adapter.summarize_new_sources()
        organize = self.adapter.organize_pending_sources()
        answers = self.adapter.analyze_answer_candidates()
        answer_concept_drafts = self.adapter.draft_answer_concept_updates()
        answer_concept_updates = self.adapter.apply_answer_concept_updates()
        graph = self.adapter.get_wiki_graph()
        lint = self.adapter.run_wiki_lint()
        raw_after = _raw_snapshot(self.adapter)
        return format_maintenance_report(
            scan,
            summarize,
            organize,
            lint,
            graph,
            answers=answers,
            answer_concept_drafts=answer_concept_drafts,
            answer_concept_updates=answer_concept_updates,
            raw_before=raw_before,
            raw_after=raw_after,
        )

    def wiki_status(self) -> str:
        sources = self.adapter.list_wiki_pages(page_type="source")
        concepts = self.adapter.list_wiki_pages(page_type="concept")
        pending_count = 0
        quality_lines: list[str] = []
        for page in sources:
            content = self.adapter.read_wiki_page(page["path"])
            quality = _quality_value(content)
            if quality in {"weak", "needs_review"}:
                pending_count += 1
            quality_lines.append(f"- {page['path']}: {quality}")
        return "\n".join(
            [
                f"pending source: {pending_count}",
                f"concept pages: {len(concepts)}",
                "source quality:",
                *(quality_lines or ["- source page 없음"]),
            ]
        )

    def ask_agent(self, query: str) -> str:
        return self.ask_agent_workflow(query).message

    def ask_agent_workflow(self, query: str) -> AgentWorkflowResult:
        if not query.strip():
            return AgentWorkflowResult("질문을 입력하세요.")
        result = self.agent_route.ask(query)
        lines = [
            result.answer,
            "",
            f"agent route: {result.route}",
            f"status: {result.status}",
        ]
        if result.error:
            lines.append(f"route error: {result.error}")
        if result.fallback_reason:
            lines.append(f"fallback reason: {result.fallback_reason}")

        lines.extend(["", "used pages:"])
        if result.used_pages:
            for item in result.used_pages:
                lines.append(f"- {item.get('path', '')}: {item.get('title', '')}")
        else:
            lines.append("- 없음")

        lines.extend(["", "related pages:"])
        if result.related_pages:
            for item in result.related_pages:
                lines.append(f"- {item.get('path', '')}: {item.get('title', '')}")
        else:
            lines.append("- 없음")
        save_result = self._auto_save_agent_answer(query, result)
        return AgentWorkflowResult(
            message="\n".join(lines),
            status_message=save_result.status_message,
            refresh_pages=save_result.refresh_pages,
        )

    def _auto_save_agent_answer(self, query: str, result: AgentRouteResult) -> AgentAutoSaveResult:
        decision = result.save_decision or {}
        if decision.get("save_action") != "save" or not bool(decision.get("save_eligible")):
            reason = str(decision.get("save_reason") or "저장 대상이 아닌 답변입니다.")
            return AgentAutoSaveResult(f"답변 저장 제외: {reason}")
        try:
            saved = self.adapter.apply_wiki_update(
                question=query,
                answer=result.answer,
                used_pages=result.used_pages,
                related_pages=result.related_pages,
                evidence=result.evidence,
                status=result.status,
                suggested_title=str(decision.get("suggested_title") or ""),
            )
        except Exception as exc:
            return AgentAutoSaveResult(f"답변 저장 실패: {exc}")
        path = str(saved.get("path") or "wiki/answers")
        if saved.get("updated") and not saved.get("created"):
            return AgentAutoSaveResult(f"기존 답변 페이지 업데이트됨: {path}", refresh_pages=True)
        return AgentAutoSaveResult(f"위키에 답변 저장됨: {path}", refresh_pages=True)


def _route_result_from_answer(answer: dict[str, Any], *, route: str, question: str = "") -> AgentRouteResult:
    fallback = bool(answer.get("fallback"))
    status = str(answer.get("status") or ("fallback" if fallback else "ok"))
    if fallback and answer.get("codex_status"):
        status = str(answer["codex_status"])
    return AgentRouteResult(
        route=route,
        status=status,
        answer=str(answer.get("answer") or ""),
        used_pages=list(answer.get("used_pages") or []),
        related_pages=list(answer.get("related_pages") or []),
        question=question,
        evidence=list(answer.get("evidence") or []),
        save_decision=dict(answer.get("save_decision") or {}),
        fallback_reason=str(answer["fallback_reason"]) if answer.get("fallback_reason") else None,
        error=str(answer["error"]) if answer.get("error") else None,
    )


def _agent_route_line(message: str) -> str:
    for line in message.splitlines():
        if line.startswith("agent route:"):
            return line
    return "agent route: 알 수 없음"


def _quality_value(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("- quality:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def format_maintenance_report(
    scan: dict[str, Any],
    summarize: dict[str, Any],
    organize: dict[str, Any],
    lint: dict[str, Any],
    graph: dict[str, Any],
    *,
    answers: dict[str, Any] | None = None,
    answer_concept_drafts: dict[str, Any] | None = None,
    answer_concept_updates: dict[str, Any] | None = None,
    raw_before: dict[str, str] | None = None,
    raw_after: dict[str, str] | None = None,
) -> str:
    lint_issues = lint.get("issues", []) or []
    source_fallback = int(summarize.get("fallback_count", 0) or 0)
    concept_fallback = int(organize.get("fallback_count", 0) or 0)
    fallback_count = source_fallback + concept_fallback
    raw_integrity = _raw_integrity_status(raw_before, raw_after)
    lint_ok = bool(lint.get("ok"))

    if raw_integrity == "raw 변경 감지" or not lint_ok:
        status = "실패"
    elif fallback_count > 0:
        status = "fallback 포함 성공"
    else:
        status = "성공"

    scanned_count = int(scan.get("scanned_count", 0) or 0)
    new_count = int(scan.get("new_count", 0) or 0)
    changed_count = int(scan.get("changed_count", 0) or 0)
    ignored_count = int(scan.get("ignored_count", 0) or 0)
    unchanged_count = max(scanned_count - new_count - changed_count, 0)
    lint_status = "통과" if lint_ok else "실패"
    fallback_status = "fallback 발생" if fallback_count else "fallback 없음"
    navigation_refreshed = bool(
        summarize.get("navigation_refreshed")
        or organize.get("navigation_refreshed")
        or (answer_concept_updates or {}).get("navigation_refreshed")
    )
    answer_candidate_count = int((answers or {}).get("candidate_count", 0) or 0)
    answer_skipped_count = int((answers or {}).get("skipped_count", 0) or 0)
    answer_draft_count = int((answer_concept_drafts or {}).get("draft_count", 0) or 0)
    answer_draft_skipped_count = int((answer_concept_drafts or {}).get("skipped_count", 0) or 0)
    answer_update_count = int((answer_concept_updates or {}).get("applied_count", 0) or 0)
    answer_update_skipped_count = int((answer_concept_updates or {}).get("skipped_count", 0) or 0)
    navigation_status = "갱신" if navigation_refreshed else "실행 안 함"

    lines = [
        "Maintenance Run Report",
        "전체 동기화 완료",
        f"상태: {status}",
        f"raw scan: 신규 {new_count}개, 변경 {changed_count}개, 유지 {unchanged_count}개, 제외 {ignored_count}개",
        (
            "source summary: "
            f"provider {summarize.get('provider', 'rule_based')}, "
            f"요약 {summarize.get('summarized_count', 0)}개, "
            f"Codex {summarize.get('codex_used_count', 0)}개, "
            f"fallback {source_fallback}개, "
            f"검토 필요 {summarize.get('needs_review_count', 0)}개"
        ),
        (
            "concept organize: "
            f"provider {organize.get('provider', 'rule_based')}, "
            f"승격 {organize.get('promoted_count', 0)}개, "
            f"병합 {organize.get('merged_count', 0)}개, "
            f"건너뜀 {organize.get('skipped_count', 0)}개, "
            f"Codex {organize.get('codex_used_count', 0)}개, "
            f"fallback {concept_fallback}개"
        ),
        f"lint: {lint_status}, issue {len(lint_issues)}개",
        f"answer candidates: {answer_candidate_count}개, skipped {answer_skipped_count}개",
        f"answer concept drafts: {answer_draft_count}개, skipped {answer_draft_skipped_count}개",
        f"answer concept updates: applied {answer_update_count}개, skipped {answer_update_skipped_count}개",
        f"navigation: {navigation_status}",
        f"안전성: {raw_integrity}, lint {lint_status}, {fallback_status}",
        (
            "산출물: "
            f"source {int(summarize.get('summarized_count', 0) or 0) + int(summarize.get('needs_review_count', 0) or 0)}개, "
            f"concept 변경 {int(organize.get('promoted_count', 0) or 0) + int(organize.get('merged_count', 0) or 0)}개, "
            f"graph node {len(graph.get('nodes', []) or [])}개, "
            f"edge {len(graph.get('edges', []) or [])}개"
        ),
    ]

    causes = _maintenance_fallback_reasons(source_fallback, concept_fallback)
    if raw_integrity == "raw 변경 감지":
        causes.append("raw 파일 해시가 동기화 실행 전후로 달라졌습니다.")
    if causes:
        lines.extend(["", "원인:", *(f"- {cause}" for cause in causes)])

    if lint_issues:
        lines.extend(["", "문제:", *(_format_lint_issue(issue) for issue in lint_issues[:5])])

    return "\n".join(lines)


def _maintenance_fallback_reasons(source_fallback: int, concept_fallback: int) -> list[str]:
    reasons: list[str] = []
    if source_fallback:
        reasons.append(f"source summary fallback {source_fallback}개: Codex draft 검증 실패 또는 실행 오류로 rule-based 요약 사용")
    if concept_fallback:
        reasons.append(f"concept organize fallback {concept_fallback}개: Codex draft 검증 실패 또는 실행 오류로 rule-based 조직 사용")
    return reasons


def _format_lint_issue(issue: dict[str, Any]) -> str:
    path = _short_path(str(issue.get("path", "")))
    message = str(issue.get("message", "")).strip()
    if path and message:
        return f"- {path}: {message}"
    if path:
        return f"- {path}"
    return f"- {message or '메시지 없는 lint issue'}"


def _short_path(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _raw_integrity_status(raw_before: dict[str, str] | None, raw_after: dict[str, str] | None) -> str:
    if raw_before is None or raw_after is None:
        return "raw 불변성 확인 불가"
    return "raw 변경 없음" if raw_before == raw_after else "raw 변경 감지"


def _raw_snapshot(adapter: Any) -> dict[str, str] | None:
    raw_dir = getattr(getattr(adapter, "config", None), "raw_dir", None)
    if not raw_dir:
        return None
    root = Path(raw_dir)
    if not root.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = _sha256(path)
    return snapshot


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
