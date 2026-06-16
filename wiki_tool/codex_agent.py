from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .agent_prompts import build_answer_prompt, build_concept_prompt, build_ingest_prompt, build_review_prompt
from .agent_provider import AgentProviderConfig, load_agent_provider_config


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

    def run_answer(
        self,
        question: str,
        *,
        wiki_context: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> CodexAgentResult:
        return self.run_role("answer", build_answer_prompt(question, wiki_context=wiki_context, evidence=evidence))

    def run_ingest(self, source_text: str) -> CodexAgentResult:
        return self.run_role("ingest", build_ingest_prompt(source_text))

    def run_concept(self, source_page: str) -> CodexAgentResult:
        return self.run_role("concept", build_concept_prompt(source_page))

    def run_review(self, changes_summary: str) -> CodexAgentResult:
        return self.run_role("review", build_review_prompt(changes_summary))

    def run_role(self, role: str, prompt: str) -> CodexAgentResult:
        config = self.config or load_agent_provider_config(role)
        output_path = _temporary_output_path()
        command = build_codex_command(
            config,
            role,
            "Read the complete task from stdin and return only the requested final output.",
            output_path=str(output_path),
        )
        try:
            completed = self.runner(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            _remove_temporary_output(output_path)
            return _failure("codex_command_not_found", f"Codex CLI command를 찾지 못했습니다: {command[0]}", exc)
        except subprocess.TimeoutExpired as exc:
            _remove_temporary_output(output_path)
            return _failure("codex_timeout", f"Codex CLI 실행 시간이 초과되었습니다: {self.timeout_seconds}s", exc)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            _remove_temporary_output(output_path)
            message = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            return _failure("codex_error", f"Codex CLI 실행 실패: {message}", None, raw_text=stdout)

        message = _read_output_message(output_path) or stdout
        _remove_temporary_output(output_path)
        return parse_codex_output(message)


def build_codex_command(
    config: AgentProviderConfig,
    role: str,
    prompt: str,
    *,
    output_path: str | None = None,
) -> list[str]:
    command_text = config.provider_command or config.codex_command
    command = shlex.split(command_text, posix=False)
    if not command:
        command = ["codex.cmd"]
    args = [*command, "exec"]
    if config.model:
        args.extend(["--model", config.model])
    args.extend(["--skip-git-repo-check", "--ephemeral"])
    if output_path:
        args.extend(["--output-last-message", output_path])
    args.extend(["--sandbox", ROLE_SANDBOX.get(role, "workspace-write"), prompt])
    return args


def parse_codex_output(stdout: str) -> CodexAgentResult:
    raw = stdout.strip()
    if not raw:
        return _failure("codex_empty_output", "Codex CLI가 빈 응답을 반환했습니다.", None)
    parsed = _extract_json_object(raw)
    if parsed is None:
        return CodexAgentResult(
            ok=True,
            status="ok",
            answer=raw,
            used_pages=[],
            related_pages=[],
            evidence=[],
            raw_text=raw,
        )
    evidence = _list_of_dicts(parsed.get("evidence"))
    used_pages = _list_of_dicts(parsed.get("used_pages")) or _used_pages_from_evidence(evidence)
    return CodexAgentResult(
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


def _temporary_output_path() -> Path:
    handle, name = tempfile.mkstemp(prefix="llm_wiki_codex_", suffix=".txt")
    os.close(handle)
    return Path(name)


def _read_output_message(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def _remove_temporary_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
