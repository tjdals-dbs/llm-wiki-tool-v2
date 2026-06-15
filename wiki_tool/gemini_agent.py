from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from .agent_output import first_code_fence_body, is_readiness_response, normalize_agent_markdown_draft
from .agent_prompts import build_concept_prompt, build_ingest_prompt, build_review_prompt
from .agent_provider import DEFAULT_GEMINI_COMMAND, AgentProviderConfig


GEMINI_AGENT_TIMEOUT_SECONDS = 120
GEMINI_HEADLESS_PROMPT = "Follow the task from stdin. Output only the requested result."


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
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def run_prompt(self, prompt: str) -> GeminiAgentResult:
        command = build_gemini_command(self.config)
        try:
            completed = (
                _run_gemini_subprocess(command, prompt, self.timeout_seconds)
                if self.runner is None
                else self.runner(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            )
        except FileNotFoundError as exc:
            return _failure("gemini_command_not_found", f"Gemini CLI command not found: {command[0]}", exc)
        except subprocess.TimeoutExpired as exc:
            return _failure(
                "gemini_timeout",
                f"Gemini CLI execution timed out after {self.timeout_seconds}s",
                None,
                raw_text=_timeout_text(exc),
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            return _failure("gemini_error", f"Gemini CLI execution failed: {message}", None, raw_text=stdout)

        raw = stdout.strip()
        if not raw:
            return _failure("gemini_empty_output", "Gemini CLI returned an empty response: 빈 응답", None, raw_text=stdout)
        return parse_gemini_output(raw)

    def run_review(self, changes_summary: str) -> GeminiAgentResult:
        return self.run_prompt(build_review_prompt(changes_summary))

    def run_ingest(self, source_text: str) -> GeminiAgentResult:
        return self.run_prompt(build_ingest_prompt(source_text))

    def run_concept(self, source_page: str) -> GeminiAgentResult:
        return self.run_prompt(build_concept_prompt(source_page))


def build_gemini_command(config: AgentProviderConfig) -> list[str]:
    command = shlex.split(config.provider_command or DEFAULT_GEMINI_COMMAND, posix=False)
    if not command:
        command = [DEFAULT_GEMINI_COMMAND]
    args = list(command)
    if "--skip-trust" not in args:
        args.append("--skip-trust")
    if "--approval-mode" not in args:
        args.extend(["--approval-mode", "plan"])
    if "--output-format" not in args and "-o" not in args:
        args.extend(["--output-format", "json"])
    if config.model:
        args.extend(["--model", config.model])
    args.extend(["-p", GEMINI_HEADLESS_PROMPT])
    return args


def _run_gemini_subprocess(command: list[str], prompt: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="llm_wiki_gemini_cli_", ignore_cleanup_errors=True) as cwd:
        return _run_gemini_subprocess_in_cwd(command, prompt, timeout_seconds, cwd)


def _run_gemini_subprocess_in_cwd(
    command: list[str],
    prompt: str,
    timeout_seconds: int,
    cwd: str,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(
            cmd=[command[0], "..."],
            timeout=timeout_seconds,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout=stdout, stderr=stderr)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.kill()


def parse_gemini_output(stdout: str) -> GeminiAgentResult:
    raw = stdout.strip()
    parsed = _extract_json_object(raw)
    if parsed is None:
        fenced_json = first_code_fence_body(raw, languages={"", "json"})
        if fenced_json:
            parsed = _extract_json_object(fenced_json)
    if parsed is not None and not _looks_like_answer_contract(parsed):
        nested_text = _extract_text_from_cli_json(parsed)
        if nested_text and nested_text.strip() != raw:
            return parse_gemini_output(nested_text)
    if parsed is None:
        if is_readiness_response(raw):
            return _failure(
                "gemini_readiness_response",
                "Gemini CLI returned an agent readiness response instead of the requested result.",
                None,
                raw_text=raw,
            )
        return GeminiAgentResult(
            ok=True,
            status="ok",
            answer=normalize_agent_markdown_draft(raw),
            used_pages=[],
            related_pages=[],
            evidence=[],
            raw_text=raw,
        )
    return GeminiAgentResult(
        ok=True,
        status=str(parsed.get("status") or "ok"),
        answer=str(parsed.get("answer") or ""),
        used_pages=_list_of_dicts(parsed.get("used_pages")),
        related_pages=_list_of_dicts(parsed.get("related_pages")),
        evidence=_list_of_dicts(parsed.get("evidence")),
        raw_text=raw,
    )


def _looks_like_answer_contract(parsed: dict[str, Any]) -> bool:
    return any(key in parsed for key in ("answer", "used_pages", "related_pages", "evidence", "status"))


def _extract_text_from_cli_json(parsed: dict[str, Any]) -> str:
    for key in ("response", "text", "content", "output", "message"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("result", "data"):
        value = parsed.get(key)
        if isinstance(value, dict):
            nested = _extract_text_from_cli_json(value)
            if nested:
                return nested
    return ""


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


def _timeout_text(exc: subprocess.TimeoutExpired) -> str:
    output = exc.output if isinstance(exc.output, str) else ""
    stderr = exc.stderr if isinstance(exc.stderr, str) else ""
    return "\n".join(part for part in [output, stderr] if part).strip()
