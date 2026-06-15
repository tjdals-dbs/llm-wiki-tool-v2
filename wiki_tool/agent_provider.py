from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


PROVIDER_CODEX = "codex"
PROVIDER_GEMINI = "gemini"
PROVIDER_RULE_BASED = "rule_based"
SUPPORTED_PROVIDERS = {PROVIDER_CODEX, PROVIDER_GEMINI, PROVIDER_RULE_BASED}
AUTO_DETECT_PROVIDERS = (PROVIDER_CODEX, PROVIDER_GEMINI)

ROLE_MODEL_ENV = {
    "ingest": "LLM_WIKI_INGEST_MODEL",
    "concept": "LLM_WIKI_CONCEPT_MODEL",
    "answer": "LLM_WIKI_ANSWER_MODEL",
    "review": "LLM_WIKI_REVIEW_MODEL",
}

ROLE_PROVIDER_ENV = {
    "ingest": "LLM_WIKI_INGEST_PROVIDER",
    "concept": "LLM_WIKI_CONCEPT_PROVIDER",
    "answer": "LLM_WIKI_ANSWER_PROVIDER",
    "review": "LLM_WIKI_REVIEW_PROVIDER",
}

DEFAULT_CODEX_COMMAND = "codex.cmd"
DEFAULT_GEMINI_COMMAND = "gemini"
DEFAULT_CODEX_MODEL = ""
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

PROVIDER_COMMAND_ENV = {
    PROVIDER_CODEX: "LLM_WIKI_CODEX_COMMAND",
    PROVIDER_GEMINI: "LLM_WIKI_GEMINI_COMMAND",
}

DEFAULT_PROVIDER_COMMAND = {
    PROVIDER_CODEX: DEFAULT_CODEX_COMMAND,
    PROVIDER_GEMINI: DEFAULT_GEMINI_COMMAND,
}

DEFAULT_PROVIDER_COMMAND_CANDIDATES = {
    PROVIDER_CODEX: ("codex.cmd", "codex"),
    PROVIDER_GEMINI: ("gemini.cmd", "gemini"),
}

DEFAULT_PROVIDER_MODEL = {
    PROVIDER_CODEX: DEFAULT_CODEX_MODEL,
    PROVIDER_GEMINI: DEFAULT_GEMINI_MODEL,
    PROVIDER_RULE_BASED: "",
}

VERSION_ARGS = {
    PROVIDER_CODEX: ("--version",),
    PROVIDER_GEMINI: ("--version",),
}

USABILITY_ARGS = {
    PROVIDER_CODEX: ("exec", "--help"),
    PROVIDER_GEMINI: ("--help",),
}

CliRunner = Callable[[Sequence[str]], object]


@dataclass(frozen=True)
class CliProbeFailure:
    returncode: int = 1
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class AgentProviderConfig:
    provider: str
    model: str
    codex_command: str
    provider_command: str = ""
    status_message: str = ""
    selection_reason: str = "legacy"

    @property
    def uses_codex(self) -> bool:
        return self.provider == PROVIDER_CODEX


@dataclass(frozen=True)
class AgentProviderDetection:
    provider: str
    command: str
    installed: bool
    authenticated: bool
    usable: bool
    model: str
    status_message: str
    selection_reason: str


def resolve_agent_provider(env: Mapping[str, str] | None = None, role: str | None = None) -> str:
    source = os.environ if env is None else env
    provider = ""
    role_key = (role or "").strip().casefold()
    role_env = ROLE_PROVIDER_ENV.get(role_key, "")
    if role_env:
        provider = source.get(role_env, "").strip().casefold()
    if not provider:
        provider = source.get("LLM_WIKI_AGENT_PROVIDER", PROVIDER_RULE_BASED).strip().casefold()
    if provider in SUPPORTED_PROVIDERS:
        return provider
    return PROVIDER_RULE_BASED


def resolve_agent_model(role: str, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    role_key = role.strip().casefold()
    role_env = ROLE_MODEL_ENV.get(role_key, "")
    if role_env:
        role_value = source.get(role_env, "").strip()
        if role_value:
            return role_value
    return source.get("LLM_WIKI_AGENT_MODEL", "").strip()


def resolve_provider_model(provider: str, role: str, env: Mapping[str, str] | None = None) -> str:
    explicit_model = resolve_agent_model(role, env)
    if explicit_model:
        return explicit_model
    return DEFAULT_PROVIDER_MODEL.get(provider.strip().casefold(), "")


def resolve_codex_command(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get("LLM_WIKI_CODEX_COMMAND", DEFAULT_CODEX_COMMAND).strip() or DEFAULT_CODEX_COMMAND


def resolve_agent_command(provider: str, env: Mapping[str, str] | None = None) -> str:
    provider_key = provider.strip().casefold()
    source = os.environ if env is None else env
    env_key = PROVIDER_COMMAND_ENV.get(provider_key, "")
    default_command = DEFAULT_PROVIDER_COMMAND.get(provider_key, provider_key)
    if not env_key:
        return default_command
    return source.get(env_key, default_command).strip() or default_command


def resolve_agent_command_candidates(provider: str, env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    provider_key = provider.strip().casefold()
    source = os.environ if env is None else env
    env_key = PROVIDER_COMMAND_ENV.get(provider_key, "")
    if env_key:
        explicit_command = source.get(env_key, "").strip()
        if explicit_command:
            return (explicit_command,)
    candidates = DEFAULT_PROVIDER_COMMAND_CANDIDATES.get(provider_key)
    if candidates:
        return candidates
    return (resolve_agent_command(provider_key, source),)


def load_agent_provider_config(
    role: str,
    env: Mapping[str, str] | None = None,
    *,
    runner: CliRunner | None = None,
    auto_detect: bool | None = None,
) -> AgentProviderConfig:
    source = os.environ if env is None else env
    explicit_provider = _explicit_agent_provider(source, role)
    if explicit_provider:
        command = "" if explicit_provider == PROVIDER_RULE_BASED else resolve_agent_command(explicit_provider, source)
        status_message = f"{explicit_provider} selected from environment"
        if explicit_provider != PROVIDER_RULE_BASED and (runner is not None or env is None or auto_detect):
            detection = _detect_cli_provider(explicit_provider, role, source, runner or _run_cli_probe)
            command = detection.command
            status_message = detection.status_message
        return AgentProviderConfig(
            provider=explicit_provider,
            model=resolve_provider_model(explicit_provider, role, source),
            codex_command=resolve_codex_command(source),
            provider_command=command,
            status_message=status_message,
            selection_reason="explicit_env",
        )
    should_auto_detect = runner is not None or (auto_detect if auto_detect is not None else env is None)
    if should_auto_detect:
        selected = select_agent_provider(role=role, env=source, runner=runner)
        return AgentProviderConfig(
            provider=selected.provider,
            model=resolve_provider_model(selected.provider, role, source),
            codex_command=resolve_codex_command(source),
            provider_command=selected.command,
            status_message=selected.status_message,
            selection_reason=selected.selection_reason,
        )
    return AgentProviderConfig(
        provider=PROVIDER_RULE_BASED,
        model=resolve_provider_model(PROVIDER_RULE_BASED, role, source),
        codex_command=resolve_codex_command(source),
        provider_command="",
        status_message="rule_based fallback selected",
        selection_reason="fallback",
    )


def detect_agent_providers(
    role: str = "answer",
    env: Mapping[str, str] | None = None,
    runner: CliRunner | None = None,
) -> list[AgentProviderDetection]:
    source = os.environ if env is None else env
    probe = runner or _run_cli_probe
    detections = [_detect_cli_provider(provider, role, source, probe) for provider in AUTO_DETECT_PROVIDERS]
    detections.append(
        AgentProviderDetection(
            provider=PROVIDER_RULE_BASED,
            command="",
            installed=True,
            authenticated=True,
            usable=True,
            model="",
            status_message="rule_based fallback is always available",
            selection_reason="fallback",
        )
    )
    return detections


def detect_gemini_cli(
    role: str = "answer",
    env: Mapping[str, str] | None = None,
    runner: CliRunner | None = None,
) -> AgentProviderDetection:
    source = os.environ if env is None else env
    probe = runner or _run_cli_probe
    return _detect_cli_provider(PROVIDER_GEMINI, role, source, probe)


def select_agent_provider(
    role: str = "answer",
    env: Mapping[str, str] | None = None,
    runner: CliRunner | None = None,
) -> AgentProviderDetection:
    source = os.environ if env is None else env
    explicit_provider = _explicit_agent_provider(source, role)
    probe = runner or _run_cli_probe
    if explicit_provider:
        if explicit_provider == PROVIDER_RULE_BASED:
            return AgentProviderDetection(
                provider=PROVIDER_RULE_BASED,
                command="",
                installed=True,
                authenticated=True,
                usable=True,
                model=resolve_provider_model(PROVIDER_RULE_BASED, role, source),
                status_message="rule_based selected from environment",
                selection_reason="explicit_env",
            )
        detection = _detect_cli_provider(explicit_provider, role, source, probe)
        return AgentProviderDetection(
            provider=detection.provider,
            command=detection.command,
            installed=detection.installed,
            authenticated=detection.authenticated,
            usable=detection.usable,
            model=detection.model,
            status_message=detection.status_message,
            selection_reason="explicit_env",
        )
    for detection in detect_agent_providers(role=role, env=source, runner=probe):
        if detection.usable and detection.provider != PROVIDER_RULE_BASED:
            return AgentProviderDetection(
                provider=detection.provider,
                command=detection.command,
                installed=detection.installed,
                authenticated=detection.authenticated,
                usable=detection.usable,
                model=detection.model,
                status_message=detection.status_message,
                selection_reason="auto_detected",
            )
    return AgentProviderDetection(
        provider=PROVIDER_RULE_BASED,
        command="",
        installed=True,
        authenticated=True,
        usable=True,
        model=resolve_provider_model(PROVIDER_RULE_BASED, role, source),
        status_message="no CLI agent provider was usable; using rule_based fallback",
        selection_reason="fallback",
    )


def _explicit_agent_provider(source: Mapping[str, str], role: str) -> str:
    role_key = role.strip().casefold()
    role_env = ROLE_PROVIDER_ENV.get(role_key, "")
    provider = source.get(role_env, "").strip().casefold() if role_env else ""
    if not provider:
        provider = source.get("LLM_WIKI_AGENT_PROVIDER", "").strip().casefold()
    if provider in SUPPORTED_PROVIDERS:
        return provider
    return ""


def _detect_cli_provider(
    provider: str,
    role: str,
    env: Mapping[str, str],
    runner: CliRunner,
) -> AgentProviderDetection:
    first_failure: AgentProviderDetection | None = None
    for command in resolve_agent_command_candidates(provider, env):
        version_result = _safe_run_probe(runner, [command, *VERSION_ARGS[provider]])
        installed = _probe_succeeded(version_result)
        if not installed:
            failure = AgentProviderDetection(
                provider=provider,
                command=command,
                installed=False,
                authenticated=False,
                usable=False,
                model=resolve_provider_model(provider, role, env),
                status_message=f"version command failed: {_probe_error(version_result)}",
                selection_reason="not_usable",
            )
            first_failure = first_failure or failure
            continue
        usability_result = _safe_run_probe(runner, [command, *USABILITY_ARGS[provider]])
        authenticated = _probe_succeeded(usability_result)
        detection = AgentProviderDetection(
            provider=provider,
            command=command,
            installed=True,
            authenticated=authenticated,
            usable=authenticated,
            model=resolve_provider_model(provider, role, env),
            status_message="usable" if authenticated else f"usable command failed: {_probe_error(usability_result)}",
            selection_reason="detected" if authenticated else "not_usable",
        )
        if detection.usable:
            return detection
        first_failure = first_failure or detection
    return first_failure or AgentProviderDetection(
        provider=provider,
        command=resolve_agent_command(provider, env),
        installed=False,
        authenticated=False,
        usable=False,
        model=resolve_provider_model(provider, role, env),
        status_message="version command failed: command returned non-zero exit code",
        selection_reason="not_usable",
    )


def _run_cli_probe(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _safe_run_probe(runner: CliRunner, command: Sequence[str]) -> object:
    try:
        return runner(command)
    except FileNotFoundError as exc:
        return CliProbeFailure(stderr=f"command not found: {exc.filename or command[0]}")
    except subprocess.TimeoutExpired:
        return CliProbeFailure(stderr="command timed out")
    except Exception as exc:
        return CliProbeFailure(stderr=str(exc) or exc.__class__.__name__)


def _probe_succeeded(result: object) -> bool:
    return int(getattr(result, "returncode", 1)) == 0


def _probe_error(result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    return stderr or stdout or "command returned non-zero exit code"
