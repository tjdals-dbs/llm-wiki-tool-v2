from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .agent_prompts import build_answer_prompt
from .agent_provider import AgentProviderConfig, load_agent_provider_config


CLAUDE_AGENT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ClaudeAgentResult:
    ok: bool
    status: str
    answer: str
    used_pages: list[dict[str, Any]]
    related_pages: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    error: str = ""
    raw_text: str = ""

    def to_answer_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "used_pages": self.used_pages,
            "related_pages": self.related_pages,
            "evidence": self.evidence,
            "provider": "claude",
            "fallback": not self.ok,
            "error": self.error,
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


class ClaudeAgentBridge:
    def __init__(
        self,
        config: AgentProviderConfig | None = None,
        *,
        runner: Runner | None = None,
        timeout_seconds: int = CLAUDE_AGENT_TIMEOUT_SECONDS,
    ) -> None:
        self.config = config
        self.runner = runner or subprocess.run
        self.timeout_seconds = timeout_seconds

    def run_answer(
        self,
        question: str,
        *,
        wiki_context: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> ClaudeAgentResult:
        config = self.config or load_agent_provider_config("answer")
        prompt = build_answer_prompt(question, wiki_context=wiki_context, evidence=evidence)
        command = build_claude_command(config, prompt)
        try:
            completed = self.runner(
                command,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            return _failure("claude_command_not_found", f"Claude CLI command를 찾지 못했습니다: {command[0]}", exc)
        except subprocess.TimeoutExpired as exc:
            return _failure("claude_timeout", f"Claude CLI 실행 시간이 초과되었습니다: {self.timeout_seconds}s", exc)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            return _failure("claude_error", f"Claude CLI 실행 실패: {message}", None, raw_text=stdout)
        return parse_claude_output(stdout)


def build_claude_command(config: AgentProviderConfig, prompt: str) -> list[str]:
    command = shlex.split(config.provider_command or "claude", posix=False)
    if not command:
        command = ["claude"]
    args = [*command, "-p"]
    if config.model:
        args.extend(["--model", config.model])
    args.append(prompt)
    return args


def parse_claude_output(stdout: str) -> ClaudeAgentResult:
    raw = stdout.strip()
    if not raw:
        return _failure("claude_empty_output", "Claude CLI가 빈 응답을 반환했습니다.", None)
    parsed = _extract_json_object(raw)
    if parsed is None:
        return _failure("claude_invalid_json", "Claude CLI 응답에서 JSON 객체를 찾지 못했습니다.", None, raw_text=raw)
    evidence = _list_of_dicts(parsed.get("evidence"))
    used_pages = _list_of_dicts(parsed.get("used_pages")) or _used_pages_from_evidence(evidence)
    return ClaudeAgentResult(
        ok=True,
        status=str(parsed.get("status") or "ok"),
        answer=str(parsed.get("answer") or ""),
        used_pages=used_pages,
        related_pages=_list_of_dicts(parsed.get("related_pages")),
        evidence=evidence,
        raw_text=raw,
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _used_pages_from_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used_pages: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in evidence:
        path = str(item.get("path") or "").strip()
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        page = {"path": path, "title": str(item.get("title") or path)}
        if item.get("type"):
            page["type"] = item["type"]
        used_pages.append(page)
    return used_pages


def _failure(status: str, message: str, exc: BaseException | None, *, raw_text: str = "") -> ClaudeAgentResult:
    detail = message if exc is None else f"{message} ({exc})"
    return ClaudeAgentResult(
        ok=False,
        status=status,
        answer="",
        used_pages=[],
        related_pages=[],
        evidence=[],
        error=detail,
        raw_text=raw_text,
    )
