from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_provider import load_agent_provider_config, resolve_codex_command
from wiki_tool.config import load_domain_config
from wiki_tool.mcp_tools import WikiToolAdapter


ENV_NAMES = [
    "LLM_WIKI_AGENT_PROVIDER",
    "LLM_WIKI_AGENT_MODEL",
    "LLM_WIKI_ANSWER_MODEL",
    "LLM_WIKI_INGEST_MODEL",
    "LLM_WIKI_CONCEPT_MODEL",
    "LLM_WIKI_REVIEW_MODEL",
    "LLM_WIKI_CODEX_COMMAND",
]


class CodexCliCheck(NamedTuple):
    ok: bool
    status: str
    version: str
    reason: str


class SmokeClassification(NamedTuple):
    label: str
    exit_code: int


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex provider smoke runner")
    parser.add_argument("--domain", required=True, help="domain.yml path")
    parser.add_argument("--question", required=True, help="answer smoke question")
    args = parser.parse_args(argv)

    env_summary = summarize_environment(os.environ)
    print("Environment")
    for line in format_environment_summary(env_summary):
        print(f"- {line}")

    cli_check = check_codex_cli(env_summary["codex_command"])
    print("")
    print("Codex CLI")
    print(f"- status: {cli_check.status}")
    if cli_check.version:
        print(f"- version: {cli_check.version}")
    if cli_check.reason:
        print(f"- reason: {cli_check.reason}")

    if not cli_check.ok:
        classification = classify_result(cli_check, {})
        print_summary(classification, cli_check, {})
        return classification.exit_code

    try:
        answer = run_answer_smoke(Path(args.domain), args.question)
    except Exception as exc:
        failed = CodexCliCheck(ok=False, status="runtime_error", version=cli_check.version, reason=str(exc))
        classification = SmokeClassification("FAIL", 1)
        print_summary(classification, failed, {})
        return classification.exit_code

    print("")
    print("Answer Smoke")
    print(f"- provider: {answer.get('provider', '')}")
    print(f"- fallback: {str(answer.get('fallback', False)).lower()}")
    print(f"- status: {answer.get('status', '')}")
    if answer.get("codex_status"):
        print(f"- codex_status: {answer.get('codex_status')}")
    if answer.get("fallback_reason"):
        print(f"- fallback_reason: {answer.get('fallback_reason')}")
    print(f"- answer preview: {answer.get('answer_preview', '')}")
    print(f"- used_pages count: {answer.get('used_pages_count', 0)}")
    print(f"- evidence count: {answer.get('evidence_count', 0)}")

    classification = classify_result(cli_check, answer)
    print_summary(classification, cli_check, answer)
    return classification.exit_code


def summarize_environment(env: Mapping[str, str]) -> dict[str, Any]:
    answer_config = load_agent_provider_config("answer", env)
    role_models = {
        "answer": answer_config.model,
        "ingest": load_agent_provider_config("ingest", env).model,
        "concept": load_agent_provider_config("concept", env).model,
        "review": load_agent_provider_config("review", env).model,
    }
    return {
        "variables": {name: bool(env.get(name, "").strip()) for name in ENV_NAMES},
        "provider": answer_config.provider,
        "resolved_models": role_models,
        "codex_command": answer_config.codex_command,
        "codex_command_display": _command_display(answer_config.codex_command),
    }


def format_environment_summary(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    variables = summary["variables"]
    for name in ENV_NAMES:
        state = "set" if variables.get(name) else "empty"
        if name == "LLM_WIKI_CODEX_COMMAND" and variables.get(name):
            state += f" ({summary['codex_command_display']})"
        lines.append(f"{name}: {state}")
    lines.append(f"resolved provider: {summary['provider']}")
    for role, model in summary["resolved_models"].items():
        lines.append(f"resolved {role} model: {model or '(empty)'}")
    return lines


def check_codex_cli(
    codex_command: str | None = None,
    *,
    runner: Any = subprocess.run,
    timeout_seconds: int = 30,
) -> CodexCliCheck:
    command = shlex.split(codex_command or resolve_codex_command(), posix=False)
    if not command:
        command = ["codex.cmd"]
    command = [*command, "--version"]
    try:
        completed = runner(
            command,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return CodexCliCheck(False, "missing", "", f"Codex CLI command not found: {command[0]}")
    except subprocess.TimeoutExpired:
        return CodexCliCheck(False, "timeout", "", f"Codex CLI version check timed out after {timeout_seconds}s")
    except Exception as exc:
        return CodexCliCheck(False, "error", "", str(exc))

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return CodexCliCheck(False, "error", "", output or f"exit code {completed.returncode}")
    return CodexCliCheck(True, "ok", output.splitlines()[0] if output else "(no version output)", "")


def run_answer_smoke(
    domain_path: str | Path,
    question: str,
    *,
    adapter_cls: type[Any] = WikiToolAdapter,
) -> dict[str, Any]:
    config = load_domain_config(Path(domain_path))
    adapter = adapter_cls(config)
    answer = adapter.answer_question(question)
    return normalize_answer_result(answer)


def normalize_answer_result(answer: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(answer)
    normalized["fallback"] = bool(answer.get("fallback", False))
    normalized["answer_preview"] = _preview(str(answer.get("answer", "")))
    normalized["used_pages_count"] = len(answer.get("used_pages", []) or [])
    normalized["evidence_count"] = len(answer.get("evidence", []) or [])
    return normalized


def classify_result(cli_check: CodexCliCheck, answer: dict[str, Any]) -> SmokeClassification:
    if not cli_check.ok:
        return SmokeClassification("FAIL", 1)
    if answer.get("provider") == "codex" and not answer.get("fallback") and answer.get("status") == "ok":
        return SmokeClassification("PASS", 0)
    if answer.get("fallback"):
        return SmokeClassification("FALLBACK", 0)
    return SmokeClassification("FAIL", 1)


def print_summary(classification: SmokeClassification, cli_check: CodexCliCheck, answer: dict[str, Any]) -> None:
    print("")
    print(f"SMOKE RESULT: {classification.label}")
    print(f"- Codex CLI: {'ok' if cli_check.ok else cli_check.status}")
    if answer:
        print(f"- Answer provider: {answer.get('provider', '')}")
        print(f"- Fallback: {str(answer.get('fallback', False)).lower()}")
        print(f"- Evidence count: {answer.get('evidence_count', 0)}")
        if answer.get("codex_status"):
            print(f"- Codex status: {answer.get('codex_status')}")
        if answer.get("fallback_reason"):
            print(f"- Reason: {answer.get('fallback_reason')}")
    elif cli_check.reason:
        print(f"- Reason: {cli_check.reason}")


def _command_display(command: str) -> str:
    parts = shlex.split(command, posix=False)
    if not parts:
        return "codex.cmd"
    return Path(parts[0]).name


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


if __name__ == "__main__":
    sys.exit(main())
