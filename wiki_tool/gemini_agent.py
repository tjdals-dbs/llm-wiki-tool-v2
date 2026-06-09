from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .agent_provider import AgentProviderConfig, DEFAULT_GEMINI_COMMAND


GEMINI_AGENT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class GeminiAgentResult:
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
            "provider": "gemini",
            "fallback": not self.ok,
            "error": self.error,
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


class GeminiAgentBridge:
    def __init__(
        self,
        config: AgentProviderConfig,
        *,
        runner: Runner | None = None,
        timeout_seconds: int = GEMINI_AGENT_TIMEOUT_SECONDS,
    ) -> None:
        self.config = config
        self.runner = runner or subprocess.run
        self.timeout_seconds = timeout_seconds

    def run_prompt(self, prompt: str) -> GeminiAgentResult:
        command = build_gemini_command(self.config, prompt)
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
            return _failure("gemini_command_not_found", f"Gemini CLI command를 찾지 못했습니다: {command[0]}", exc)
        except subprocess.TimeoutExpired as exc:
            return _failure("gemini_timeout", f"Gemini CLI 실행 시간이 초과되었습니다: {self.timeout_seconds}s", exc)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            return _failure("gemini_error", f"Gemini CLI 실행 실패: {message}", None, raw_text=stdout)

        answer = stdout.strip()
        if not answer:
            return _failure("gemini_empty_output", "Gemini CLI가 빈 응답을 반환했습니다.", None, raw_text=stdout)
        return GeminiAgentResult(
            ok=True,
            status="ok",
            answer=answer,
            used_pages=[],
            related_pages=[],
            evidence=[],
            raw_text=stdout,
        )


def build_gemini_command(config: AgentProviderConfig, prompt: str) -> list[str]:
    command = shlex.split(config.provider_command or DEFAULT_GEMINI_COMMAND, posix=False)
    if not command:
        command = [DEFAULT_GEMINI_COMMAND]
    args = list(command)
    if config.model:
        args.extend(["--model", config.model])
    args.extend(["-p", prompt])
    return args


def _failure(status: str, message: str, exc: BaseException | None, *, raw_text: str = "") -> GeminiAgentResult:
    detail = message if exc is None else f"{message} ({exc})"
    return GeminiAgentResult(
        ok=False,
        status=status,
        answer="",
        used_pages=[],
        related_pages=[],
        evidence=[],
        error=detail,
        raw_text=raw_text,
    )
