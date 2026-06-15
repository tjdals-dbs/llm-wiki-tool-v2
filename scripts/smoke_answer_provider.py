from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_provider import (  # noqa: E402
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    PROVIDER_RULE_BASED,
    detect_agent_providers,
    load_agent_provider_config,
)
from wiki_tool.config import load_domain_config  # noqa: E402
from wiki_tool.env_loader import load_dotenv_if_present  # noqa: E402
from wiki_tool.mcp_tools import WikiToolAdapter  # noqa: E402


ENV_NAMES = [
    "LLM_WIKI_AGENT_PROVIDER",
    "LLM_WIKI_ANSWER_PROVIDER",
    "LLM_WIKI_AGENT_MODEL",
    "LLM_WIKI_ANSWER_MODEL",
    "LLM_WIKI_CODEX_COMMAND",
    "LLM_WIKI_GEMINI_COMMAND",
]


class CliDiagnostic(NamedTuple):
    provider: str
    command: str
    installed: bool
    usable: bool
    status_message: str


class SmokeClassification(NamedTuple):
    label: str
    exit_code: int
    reason: str = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Answer provider smoke runner")
    parser.add_argument("--domain", required=True, help="domain.yml path")
    parser.add_argument("--question", required=True, help="answer smoke question")
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", PROVIDER_CODEX, PROVIDER_GEMINI, PROVIDER_RULE_BASED],
        help="force the answer provider for this smoke run",
    )
    args = parser.parse_args(argv)

    forced_provider = "" if args.provider == "auto" else args.provider
    env_load = load_environment_for_smoke()
    if forced_provider:
        os.environ["LLM_WIKI_ANSWER_PROVIDER"] = forced_provider

    env_summary = summarize_environment(os.environ, env_load)
    print("Environment")
    for line in format_environment_summary(env_summary):
        print(f"- {line}")

    diagnostics = collect_cli_diagnostics(os.environ)
    print("")
    print("CLI Diagnostics")
    for line in format_cli_diagnostics(diagnostics):
        print(f"- {line}")

    try:
        answer = run_answer_smoke(Path(args.domain), args.question, provider=forced_provider)
    except Exception as exc:
        answer = {
            "provider": "",
            "fallback": False,
            "status": "runtime_error",
            "fallback_reason": str(exc),
            "answer_preview": "",
            "used_pages_count": 0,
            "evidence_count": 0,
        }

    print("")
    print("Answer Smoke")
    for line in format_answer_smoke(answer):
        print(f"- {line}")

    classification = classify_smoke_result(answer, diagnostics, forced_provider=forced_provider)
    print("")
    print(f"SMOKE RESULT: {classification.label}")
    print(f"- Answer provider: {answer.get('provider', '')}")
    print(f"- Fallback: {str(answer.get('fallback', False)).lower()}")
    print(f"- Evidence count: {answer.get('evidence_count', 0)}")
    if classification.reason:
        print(f"- Reason: {classification.reason}")
    elif answer.get("fallback_reason"):
        print(f"- Reason: {answer.get('fallback_reason')}")
    return classification.exit_code


def load_environment_for_smoke(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or PROJECT_ROOT
    env_path = root / ".env"
    loaded = load_dotenv_if_present(root)
    return {
        "exists": env_path.exists(),
        "loaded": bool(loaded),
        "loaded_keys": sorted(loaded),
        "path": str(env_path),
    }


def summarize_environment(env: Mapping[str, str], env_load: Mapping[str, Any] | None = None) -> dict[str, Any]:
    answer_config = load_agent_provider_config("answer", env)
    return {
        "env_load": dict(env_load or {}),
        "variables": {name: bool(env.get(name, "").strip()) for name in ENV_NAMES},
        "values": {name: env.get(name, "").strip() for name in ENV_NAMES},
        "resolved_answer_provider": answer_config.provider,
        "resolved_answer_model": answer_config.model,
        "codex_command_display": _command_display(answer_config.codex_command),
        "gemini_command_display": _command_display(env.get("LLM_WIKI_GEMINI_COMMAND", "gemini")),
    }


def format_environment_summary(summary: Mapping[str, Any]) -> list[str]:
    env_load = summary.get("env_load", {})
    lines = [
        f".env exists: {_yes_no(bool(env_load.get('exists', False)))}",
        f".env loaded: {_yes_no(bool(env_load.get('loaded', False)))}",
    ]
    loaded_keys = env_load.get("loaded_keys") or []
    if loaded_keys:
        lines.append(f".env loaded keys: {', '.join(str(key) for key in loaded_keys)}")
    variables = summary.get("variables", {})
    values = summary.get("values", {})
    for name in ENV_NAMES:
        state = "set" if variables.get(name) else "empty"
        if name == "LLM_WIKI_CODEX_COMMAND" and variables.get(name):
            state += f" ({summary.get('codex_command_display', '')})"
        if name == "LLM_WIKI_GEMINI_COMMAND" and variables.get(name):
            state += f" ({summary.get('gemini_command_display', '')})"
        if name.endswith("_MODEL") and variables.get(name):
            state += f" ({values.get(name, '')})"
        lines.append(f"{name}: {state}")
    lines.append(f"resolved answer provider: {summary.get('resolved_answer_provider', '')}")
    lines.append(f"resolved answer model: {summary.get('resolved_answer_model') or '(empty)'}")
    return lines


def collect_cli_diagnostics(
    env: Mapping[str, str],
    *,
    runner: Any | None = None,
) -> dict[str, CliDiagnostic]:
    detections = detect_agent_providers(role="answer", env=env, runner=runner)
    diagnostics: dict[str, CliDiagnostic] = {}
    for detection in detections:
        if detection.provider not in {PROVIDER_CODEX, PROVIDER_GEMINI}:
            continue
        diagnostics[detection.provider] = CliDiagnostic(
            provider=detection.provider,
            command=detection.command,
            installed=bool(detection.installed),
            usable=bool(detection.usable),
            status_message=detection.status_message,
        )
    return diagnostics


def format_cli_diagnostics(diagnostics: Mapping[str, CliDiagnostic]) -> list[str]:
    lines: list[str] = []
    for provider in [PROVIDER_CODEX, PROVIDER_GEMINI]:
        diagnostic = diagnostics.get(provider) or CliDiagnostic(provider, "", False, False, "not checked")
        lines.append(
            f"{provider}: installed={str(diagnostic.installed).lower()}, "
            f"usable={str(diagnostic.usable).lower()}, command={_command_display(diagnostic.command)}, "
            f"status={diagnostic.status_message}"
        )
    return lines


def run_answer_smoke(
    domain_path: str | Path,
    question: str,
    *,
    provider: str = "",
    adapter_cls: type[Any] = WikiToolAdapter,
) -> dict[str, Any]:
    previous_provider = os.environ.get("LLM_WIKI_ANSWER_PROVIDER")
    if provider:
        os.environ["LLM_WIKI_ANSWER_PROVIDER"] = provider
    try:
        with tempfile.TemporaryDirectory(prefix="llm_wiki_answer_provider_") as tmp:
            copied_domain = copy_domain_for_answer_smoke(Path(domain_path), Path(tmp))
            config = load_domain_config(copied_domain)
            adapter = adapter_cls(config)
            return normalize_answer_result(adapter.answer_question(question))
    finally:
        if provider:
            if previous_provider is None:
                os.environ.pop("LLM_WIKI_ANSWER_PROVIDER", None)
            else:
                os.environ["LLM_WIKI_ANSWER_PROVIDER"] = previous_provider


def copy_domain_for_answer_smoke(domain_path: Path, temp_root: Path) -> Path:
    source_config = load_domain_config(domain_path)
    temp_root.mkdir(parents=True, exist_ok=True)
    copied_domain = temp_root / domain_path.name
    copied_domain.write_text(domain_path.read_text(encoding="utf-8"), encoding="utf-8")

    raw_relative = source_config.raw_dir.relative_to(source_config.root)
    (temp_root / raw_relative).mkdir(parents=True, exist_ok=True)
    manifest_relative = source_config.manifest_path.relative_to(source_config.root)
    (temp_root / manifest_relative.parent).mkdir(parents=True, exist_ok=True)

    wiki_relative = source_config.wiki_dir.relative_to(source_config.root)
    copied_wiki = temp_root / wiki_relative
    if source_config.wiki_dir.exists():
        shutil.copytree(source_config.wiki_dir, copied_wiki, dirs_exist_ok=True)
    else:
        copied_wiki.mkdir(parents=True, exist_ok=True)
    return copied_domain


def normalize_answer_result(answer: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(answer)
    normalized["fallback"] = bool(answer.get("fallback", False))
    normalized["answer_preview"] = _preview(str(answer.get("answer", "")))
    normalized["used_pages_count"] = len(answer.get("used_pages", []) or [])
    normalized["evidence_count"] = len(answer.get("evidence", []) or [])
    return normalized


def format_answer_smoke(answer: Mapping[str, Any]) -> list[str]:
    lines = [
        f"provider: {answer.get('provider', '')}",
        f"fallback: {str(answer.get('fallback', False)).lower()}",
        f"status: {answer.get('status', '')}",
    ]
    if answer.get("codex_status"):
        lines.append(f"codex_status: {answer.get('codex_status')}")
    if answer.get("gemini_status"):
        lines.append(f"gemini_status: {answer.get('gemini_status')}")
    if answer.get("fallback_reason"):
        lines.append(f"fallback_reason: {answer.get('fallback_reason')}")
    if answer.get("error"):
        lines.append(f"error: {answer.get('error')}")
    lines.extend(
        [
            f"answer preview: {answer.get('answer_preview', '')}",
            f"used_pages count: {answer.get('used_pages_count', 0)}",
            f"evidence count: {answer.get('evidence_count', 0)}",
        ]
    )
    return lines


def classify_smoke_result(
    answer: Mapping[str, Any],
    diagnostics: Mapping[str, CliDiagnostic],
    *,
    forced_provider: str = "",
) -> SmokeClassification:
    forced = (forced_provider or "").strip().casefold()
    provider = str(answer.get("provider") or "").strip().casefold()
    fallback = bool(answer.get("fallback", False))
    status = str(answer.get("status") or "")

    if forced == PROVIDER_GEMINI:
        gemini = diagnostics.get(PROVIDER_GEMINI)
        if gemini is not None and not gemini.usable:
            return SmokeClassification(
                "FAIL",
                1,
                f"forced gemini provider is not usable: {gemini.status_message}",
            )
        if fallback or provider != PROVIDER_GEMINI or status != "ok":
            return SmokeClassification(
                "FAIL",
                1,
                f"forced gemini provider fell back or failed: {answer.get('fallback_reason') or status}",
            )
        return SmokeClassification("PASS", 0)

    if forced == PROVIDER_CODEX:
        codex = diagnostics.get(PROVIDER_CODEX)
        if codex is not None and not codex.usable:
            return SmokeClassification("FAIL", 1, f"forced codex provider is not usable: {codex.status_message}")
        if fallback or provider != PROVIDER_CODEX or status != "ok":
            return SmokeClassification(
                "FAIL",
                1,
                f"forced codex provider fell back or failed: {answer.get('fallback_reason') or status}",
            )
        return SmokeClassification("PASS", 0)

    if status == "runtime_error":
        return SmokeClassification("FAIL", 1, str(answer.get("fallback_reason") or "runtime error"))
    if provider in {PROVIDER_CODEX, PROVIDER_GEMINI} and not fallback and status == "ok":
        return SmokeClassification("PASS", 0)
    if fallback:
        return SmokeClassification("FALLBACK", 0, str(answer.get("fallback_reason") or "fallback verified"))
    if provider == PROVIDER_RULE_BASED and status in {"ok", "no_evidence"}:
        return SmokeClassification("FALLBACK", 0, "rule_based answer path verified")
    return SmokeClassification("FAIL", 1, str(answer.get("fallback_reason") or status or "unknown failure"))


def _command_display(command: str) -> str:
    parts = shlex.split(command or "", posix=False)
    if not parts:
        return "(empty)"
    return Path(parts[0]).name


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    sys.exit(main())
