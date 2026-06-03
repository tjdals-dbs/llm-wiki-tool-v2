from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


PROVIDER_CODEX = "codex"
PROVIDER_RULE_BASED = "rule_based"
SUPPORTED_PROVIDERS = {PROVIDER_CODEX, PROVIDER_RULE_BASED}

ROLE_MODEL_ENV = {
    "ingest": "LLM_WIKI_INGEST_MODEL",
    "concept": "LLM_WIKI_CONCEPT_MODEL",
    "answer": "LLM_WIKI_ANSWER_MODEL",
    "review": "LLM_WIKI_REVIEW_MODEL",
}

DEFAULT_CODEX_COMMAND = "codex.cmd"


@dataclass(frozen=True)
class AgentProviderConfig:
    provider: str
    model: str
    codex_command: str

    @property
    def uses_codex(self) -> bool:
        return self.provider == PROVIDER_CODEX


def resolve_agent_provider(env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ
    provider = source.get("LLM_WIKI_AGENT_PROVIDER", PROVIDER_RULE_BASED).strip().casefold()
    if provider in SUPPORTED_PROVIDERS:
        return provider
    return PROVIDER_RULE_BASED


def resolve_agent_model(role: str, env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ
    role_key = role.strip().casefold()
    role_env = ROLE_MODEL_ENV.get(role_key, "")
    if role_env:
        role_value = source.get(role_env, "").strip()
        if role_value:
            return role_value
    return source.get("LLM_WIKI_AGENT_MODEL", "").strip()


def resolve_codex_command(env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ
    return source.get("LLM_WIKI_CODEX_COMMAND", DEFAULT_CODEX_COMMAND).strip() or DEFAULT_CODEX_COMMAND


def load_agent_provider_config(role: str, env: Mapping[str, str] | None = None) -> AgentProviderConfig:
    return AgentProviderConfig(
        provider=resolve_agent_provider(env),
        model=resolve_agent_model(role, env),
        codex_command=resolve_codex_command(env),
    )
