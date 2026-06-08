from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .agent_provider import PROVIDER_CODEX, PROVIDER_RULE_BASED, load_agent_provider_config
from .codex_agent import CodexAgentBridge, CodexAgentResult


@dataclass(frozen=True)
class AgentHookResult:
    role: str
    provider: str
    fallback: bool
    status: str
    draft: str
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "fallback": self.fallback,
            "status": self.status,
            "draft": self.draft,
            "error": self.error,
        }


BridgeFactory = Callable[[Any], CodexAgentBridge]


def draft_source_summary_with_agent(
    source_text: str,
    *,
    env: Mapping[str, str] | None = None,
    bridge_factory: BridgeFactory = CodexAgentBridge,
) -> AgentHookResult:
    return _run_hook("ingest", source_text, env=env, bridge_factory=bridge_factory)


def draft_concept_update_with_agent(
    source_page: str,
    *,
    env: Mapping[str, str] | None = None,
    bridge_factory: BridgeFactory = CodexAgentBridge,
) -> AgentHookResult:
    return _run_hook("concept", source_page, env=env, bridge_factory=bridge_factory)


def review_wiki_changes_with_agent(
    changes_summary: str,
    *,
    env: Mapping[str, str] | None = None,
    bridge_factory: BridgeFactory = CodexAgentBridge,
) -> AgentHookResult:
    return _run_hook("review", changes_summary, env=env, bridge_factory=bridge_factory)


def _run_hook(
    role: str,
    payload: str,
    *,
    env: Mapping[str, str] | None,
    bridge_factory: BridgeFactory,
) -> AgentHookResult:
    config = load_agent_provider_config(role, env)
    if config.provider != PROVIDER_CODEX:
        unsupported = config.provider != PROVIDER_RULE_BASED
        return AgentHookResult(
            role=role,
            provider="rule_based",
            fallback=True,
            status="unsupported_provider_fallback" if unsupported else "rule_based_fallback",
            draft="",
            error=(
                f"{config.provider} provider는 아직 실행 adapter가 없어 rule-based fallback을 사용합니다."
                if unsupported
                else "Codex provider가 설정되지 않아 기존 rule-based pipeline을 사용합니다."
            ),
        )

    bridge = bridge_factory(config)
    result = _run_codex_role(bridge, role, payload)
    if result.ok:
        return AgentHookResult(
            role=role,
            provider="codex",
            fallback=False,
            status=result.status,
            draft=result.answer,
        )
    return AgentHookResult(
        role=role,
        provider="rule_based",
        fallback=True,
        status=result.status,
        draft="",
        error=result.error,
    )


def _run_codex_role(bridge: CodexAgentBridge, role: str, payload: str) -> CodexAgentResult:
    if role == "ingest":
        return bridge.run_ingest(payload)
    if role == "concept":
        return bridge.run_concept(payload)
    if role == "review":
        return bridge.run_review(payload)
    raise ValueError(f"지원하지 않는 agent role입니다: {role}")
