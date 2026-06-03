from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .agent_provider import AgentProviderConfig, load_agent_provider_config
from .agent_prompts import build_answer_prompt, build_concept_prompt, build_ingest_prompt, build_review_prompt


CODEX_AGENT_TIMEOUT_SECONDS = 120
ROLE_SANDBOX = {
    "answer": "read-only",
    "ingest": "workspace-write",
    "concept": "workspace-write",
    "review": "workspace-write",
}


@dataclass(frozen=True)
class CodexAgentResult:
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
            "provider": "codex",
            "fallback": not self.ok,
            "error": self.error,
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


class CodexAgentBridge:
    def __init__(
        self,
        config: AgentProviderConfig | None = None,
        *,
        runner: Runner | None = None,
        timeout_seconds: int = CODEX_AGENT_TIMEOUT_SECONDS,
    ) -> None:
        self.config = config
        self.runner = runner or subprocess.run
        self.timeout_seconds = timeout_seconds

    def run_answer(self, question: str) -> CodexAgentResult:
        return self.run_role("answer", build_answer_prompt(question))

    def run_ingest(self, source_text: str) -> CodexAgentResult:
        return self.run_role("ingest", build_ingest_prompt(source_text))

    def run_concept(self, source_page: str) -> CodexAgentResult:
        return self.run_role("concept", build_concept_prompt(source_page))

    def run_review(self, changes_summary: str) -> CodexAgentResult:
        return self.run_role("review", build_review_prompt(changes_summary))

    def run_role(self, role: str, prompt: str) -> CodexAgentResult:
        config = self.config or load_agent_provider_config(role)
        command = build_codex_command(config, role, prompt)
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
            return _failure("codex_command_not_found", f"Codex CLI command를 찾지 못했습니다: {command[0]}", exc)
        except subprocess.TimeoutExpired as exc:
            return _failure("codex_timeout", f"Codex CLI 실행 시간이 초과되었습니다: {self.timeout_seconds}s", exc)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            return _failure("codex_error", f"Codex CLI 실행 실패: {message}", None, raw_text=stdout)
        return parse_codex_output(stdout)


def build_codex_command(config: AgentProviderConfig, role: str, prompt: str) -> list[str]:
    command = shlex.split(config.codex_command, posix=False)
    if not command:
        command = ["codex.cmd"]
    args = [*command, "exec"]
    if config.model:
        args.extend(["--model", config.model])
    args.extend(["--sandbox", ROLE_SANDBOX.get(role, "workspace-write"), prompt])
    return args


def parse_codex_output(stdout: str) -> CodexAgentResult:
    raw = stdout.strip()
    if not raw:
        return _failure("codex_empty_output", "Codex CLI가 빈 응답을 반환했습니다.", None)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return CodexAgentResult(
            ok=True,
            status="ok",
            answer=raw,
            used_pages=[],
            related_pages=[],
            evidence=[],
            raw_text=raw,
        )
    return CodexAgentResult(
        ok=True,
        status=str(parsed.get("status") or "ok"),
        answer=str(parsed.get("answer") or ""),
        used_pages=_list_of_dicts(parsed.get("used_pages")),
        related_pages=_list_of_dicts(parsed.get("related_pages")),
        evidence=_list_of_dicts(parsed.get("evidence")),
        raw_text=raw,
    )


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _failure(status: str, message: str, exc: BaseException | None, *, raw_text: str = "") -> CodexAgentResult:
    detail = message if exc is None else f"{message} ({exc})"
    return CodexAgentResult(
        ok=False,
        status=status,
        answer="",
        used_pages=[],
        related_pages=[],
        evidence=[],
        error=detail,
        raw_text=raw_text,
    )
