from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_provider import (  # noqa: E402
    PROVIDER_GEMINI,
    PROVIDER_RULE_BASED,
    detect_gemini_cli,
    load_agent_provider_config,
)
from wiki_tool.config import load_domain_config  # noqa: E402
from wiki_tool.env_loader import load_dotenv_if_present  # noqa: E402
from wiki_tool.mcp_tools import WikiToolAdapter  # noqa: E402
from wiki_tool.summarizer import validate_source_page_draft  # noqa: E402


ENV_NAMES = [
    "LLM_WIKI_AGENT_PROVIDER",
    "LLM_WIKI_INGEST_PROVIDER",
    "LLM_WIKI_AGENT_MODEL",
    "LLM_WIKI_INGEST_MODEL",
    "LLM_WIKI_GEMINI_COMMAND",
]

SMOKE_RAW_TEXT = """# Gemini Ingest Smoke

요구사항 분석은 사용자의 목표와 제약을 정리해 기능 범위를 명확히 하는 활동이다.
JWT는 인증 토큰 형식이며 Spring Security는 접근 제어를 구성하는 프레임워크다.
이 문서는 public-safe smoke test fixture이며 개인 자료를 포함하지 않는다.
"""


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
    parser = argparse.ArgumentParser(description="Gemini ingest provider smoke runner")
    parser.add_argument(
        "--provider",
        default=PROVIDER_GEMINI,
        choices=[PROVIDER_GEMINI],
        help="Gemini ingest provider to diagnose; kept explicit for parity with other smoke runners",
    )
    parser.add_argument(
        "--ignore-dotenv",
        action="store_true",
        help="do not load the repository .env file; OS environment variables are still respected",
    )
    args = parser.parse_args(argv)

    forced_provider = args.provider
    env_load = load_environment_for_smoke(ignore_dotenv=args.ignore_dotenv)
    previous_provider = os.environ.get("LLM_WIKI_INGEST_PROVIDER")
    os.environ["LLM_WIKI_INGEST_PROVIDER"] = PROVIDER_GEMINI

    try:
        env_summary = summarize_environment(os.environ, env_load)
        print("Environment")
        for line in format_environment_summary(env_summary):
            print(f"- {line}")

        diagnostic = collect_gemini_cli_diagnostic(os.environ)
        print("")
        print("Gemini CLI Diagnostic")
        for line in format_cli_diagnostic(diagnostic):
            print(f"- {line}")

        try:
            result = run_ingest_smoke()
        except Exception as exc:
            result = {
                "resolved_ingest_provider": env_summary.get("resolved_ingest_provider", ""),
                "resolved_ingest_model": env_summary.get("resolved_ingest_model", ""),
                "source_summary_status": "runtime_error",
                "fallback": False,
                "fallback_reason": str(exc),
                "generated_source_page_path": "",
                "raw_unchanged": False,
                "source_schema_ok": False,
                "source_quality_ok": False,
                "lint_ok": False,
                "lint_issues_count": 0,
            }

        print("")
        print("Gemini Ingest Smoke")
        for line in format_ingest_smoke(result):
            print(f"- {line}")

        classification = classify_smoke_result(result, diagnostic, forced_provider=forced_provider)
        print("")
        print(f"SMOKE RESULT: {classification.label}")
        print(f"- Resolved ingest provider: {result.get('resolved_ingest_provider', '')}")
        print(f"- Fallback: {str(result.get('fallback', False)).lower()}")
        print(f"- Raw unchanged: {str(result.get('raw_unchanged', False)).lower()}")
        print(f"- Lint ok: {str(result.get('lint_ok', False)).lower()}")
        if classification.reason:
            print(f"- Reason: {classification.reason}")
        elif result.get("fallback_reason"):
            print(f"- Reason: {result.get('fallback_reason')}")
        return classification.exit_code
    finally:
        _restore_env_value("LLM_WIKI_INGEST_PROVIDER", previous_provider)


def load_environment_for_smoke(project_root: Path | None = None, *, ignore_dotenv: bool = False) -> dict[str, Any]:
    root = project_root or PROJECT_ROOT
    env_path = root / ".env"
    loaded = {} if ignore_dotenv else load_dotenv_if_present(root)
    return {
        "exists": env_path.exists(),
        "loaded": bool(loaded),
        "loaded_keys": sorted(loaded),
        "ignored": bool(ignore_dotenv),
        "path": str(env_path),
    }


def summarize_environment(env: Mapping[str, str], env_load: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ingest_config = load_agent_provider_config("ingest", env)
    return {
        "env_load": dict(env_load or {}),
        "variables": {name: bool(env.get(name, "").strip()) for name in ENV_NAMES},
        "values": {name: env.get(name, "").strip() for name in ENV_NAMES},
        "resolved_ingest_provider": ingest_config.provider,
        "resolved_ingest_model": ingest_config.model,
        "gemini_command_display": _command_display(env.get("LLM_WIKI_GEMINI_COMMAND", "gemini")),
    }


def format_environment_summary(summary: Mapping[str, Any]) -> list[str]:
    env_load = summary.get("env_load", {})
    loaded_text = (
        "no (--ignore-dotenv)"
        if bool(env_load.get("ignored", False))
        else _yes_no(bool(env_load.get("loaded", False)))
    )
    lines = [
        f".env exists: {_yes_no(bool(env_load.get('exists', False)))}",
        f".env loaded: {loaded_text}",
    ]
    loaded_keys = env_load.get("loaded_keys") or []
    if loaded_keys:
        lines.append(f".env loaded keys: {', '.join(str(key) for key in loaded_keys)}")
    variables = summary.get("variables", {})
    values = summary.get("values", {})
    for name in ENV_NAMES:
        state = "set" if variables.get(name) else "empty"
        if name == "LLM_WIKI_GEMINI_COMMAND" and variables.get(name):
            state += f" ({summary.get('gemini_command_display', '')})"
        if name.endswith("_MODEL") and variables.get(name):
            state += f" ({values.get(name, '')})"
        lines.append(f"{name}: {state}")
    lines.append(f"resolved ingest provider: {summary.get('resolved_ingest_provider', '')}")
    lines.append(f"resolved ingest model: {summary.get('resolved_ingest_model') or '(empty)'}")
    return lines


def collect_gemini_cli_diagnostic(
    env: Mapping[str, str],
    *,
    runner: Any | None = None,
) -> CliDiagnostic:
    detection = detect_gemini_cli(role="ingest", env=env, runner=runner)
    return CliDiagnostic(
        provider=detection.provider,
        command=detection.command,
        installed=bool(detection.installed),
        usable=bool(detection.usable),
        status_message=detection.status_message,
    )


def format_cli_diagnostic(diagnostic: CliDiagnostic) -> list[str]:
    return [
        (
            f"gemini: installed={str(diagnostic.installed).lower()}, "
            f"usable={str(diagnostic.usable).lower()}, command={_command_display(diagnostic.command)}, "
            f"status={diagnostic.status_message}"
        )
    ]


def run_ingest_smoke(
    *,
    adapter_cls: type[Any] = WikiToolAdapter,
) -> dict[str, Any]:
    previous_provider = os.environ.get("LLM_WIKI_INGEST_PROVIDER")
    os.environ["LLM_WIKI_INGEST_PROVIDER"] = PROVIDER_GEMINI
    try:
        with tempfile.TemporaryDirectory(prefix="llm_wiki_gemini_ingest_") as tmp:
            domain_path, raw_path = create_ingest_smoke_domain(Path(tmp))
            before_hash = _sha256(raw_path)
            config = load_domain_config(domain_path)
            provider_config = load_agent_provider_config("ingest")
            adapter = adapter_cls(config)

            scan = adapter.scan_raw_sources()
            summary = adapter.summarize_new_sources()
            lint = adapter.run_wiki_lint()
            after_hash = _sha256(raw_path)

            source_pages = sorted((config.wiki_dir / "sources").glob("*.md"))
            source_page = source_pages[0] if source_pages else None
            source_text = source_page.read_text(encoding="utf-8") if source_page else ""
            validation = validate_source_page_draft(source_text) if source_text else {}
            schema_ok = bool(validation.get("ok", False))
            quality_ok = _source_quality_ok(source_text)
            fallback_reason = _metadata_value(source_text, "fallback_reason")
            gemini_status = _metadata_value(source_text, "codex_status") if "provider: gemini" in source_text else ""

            lint_issues = lint.get("issues", []) if isinstance(lint, Mapping) else []
            return {
                "resolved_ingest_provider": provider_config.provider,
                "resolved_ingest_model": provider_config.model,
                "scan_new_count": _count(scan, "new_count"),
                "source_summary_status": _summary_status(summary, schema_ok, quality_ok),
                "fallback": bool(_count(summary, "fallback_count")),
                "fallback_reason": fallback_reason,
                "gemini_status": gemini_status,
                "summarized_count": _count(summary, "summarized_count"),
                "needs_review_count": _count(summary, "needs_review_count"),
                "gemini_used_count": _count(summary, "gemini_used_count"),
                "fallback_count": _count(summary, "fallback_count"),
                "generated_source_page_path": _relative_to_domain(source_page, config.root) if source_page else "",
                "generated_source_pages_count": len(source_pages),
                "raw_unchanged": before_hash == after_hash,
                "source_schema_ok": schema_ok,
                "source_quality_ok": quality_ok,
                "lint_ok": bool(lint.get("ok", False)) if isinstance(lint, Mapping) else False,
                "lint_issues_count": len(lint_issues),
            }
    finally:
        _restore_env_value("LLM_WIKI_INGEST_PROVIDER", previous_provider)


def create_ingest_smoke_domain(root: Path) -> tuple[Path, Path]:
    domain_path = root / "domain.yml"
    raw_dir = root / "raw"
    wiki_dir = root / "wiki"
    manifests_dir = root / "manifests"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "gemini-ingest-smoke.md"
    raw_path.write_text(SMOKE_RAW_TEXT, encoding="utf-8")
    domain_path.write_text(
        "\n".join(
            [
                "name: Gemini Ingest Smoke",
                "slug: gemini-ingest-smoke",
                "description: Temporary public-safe Gemini ingest smoke domain.",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                "language: ko",
            ]
        ),
        encoding="utf-8",
    )
    return domain_path, raw_path


def format_ingest_smoke(result: Mapping[str, Any]) -> list[str]:
    lines = [
        f"resolved ingest provider: {result.get('resolved_ingest_provider', '')}",
        f"resolved ingest model: {result.get('resolved_ingest_model') or '(empty)'}",
        f"source summary status: {result.get('source_summary_status', '')}",
        f"fallback: {str(result.get('fallback', False)).lower()}",
    ]
    if result.get("gemini_status"):
        lines.append(f"gemini_status: {result.get('gemini_status')}")
    if result.get("fallback_reason"):
        lines.append(f"fallback_reason: {result.get('fallback_reason')}")
    lines.extend(
        [
            f"scan new_count: {result.get('scan_new_count', 0)}",
            f"summarized_count: {result.get('summarized_count', 0)}",
            f"gemini_used_count: {result.get('gemini_used_count', 0)}",
            f"fallback_count: {result.get('fallback_count', 0)}",
            f"generated source page path: {result.get('generated_source_page_path', '')}",
            f"generated source pages count: {result.get('generated_source_pages_count', 0)}",
            f"source schema ok: {str(result.get('source_schema_ok', False)).lower()}",
            f"source quality ok: {str(result.get('source_quality_ok', False)).lower()}",
            f"raw unchanged: {str(result.get('raw_unchanged', False)).lower()}",
            f"lint ok: {str(result.get('lint_ok', False)).lower()}",
            f"lint issues count: {result.get('lint_issues_count', 0)}",
        ]
    )
    return lines


def classify_smoke_result(
    result: Mapping[str, Any],
    diagnostic: CliDiagnostic,
    *,
    forced_provider: str = "",
) -> SmokeClassification:
    forced = (forced_provider or "").strip().casefold()
    provider = str(result.get("resolved_ingest_provider") or "").strip().casefold()
    status = str(result.get("source_summary_status") or "")
    fallback = bool(result.get("fallback", False))

    if forced == PROVIDER_GEMINI:
        if not diagnostic.usable:
            return SmokeClassification("FAIL", 1, f"forced gemini provider is not usable: {diagnostic.status_message}")
        if provider != PROVIDER_GEMINI or fallback or status != "ok":
            return SmokeClassification(
                "FAIL",
                1,
                f"forced gemini ingest provider fell back or failed: {result.get('fallback_reason') or status}",
            )

    if status == "runtime_error":
        return SmokeClassification("FAIL", 1, str(result.get("fallback_reason") or "runtime error"))
    if not bool(result.get("raw_unchanged", False)):
        return SmokeClassification("FAIL", 1, "raw file was modified during ingest smoke")
    if not bool(result.get("source_schema_ok", False)):
        return SmokeClassification("FAIL", 1, "generated source page did not satisfy the minimum schema")
    if not bool(result.get("source_quality_ok", False)):
        return SmokeClassification("FAIL", 1, "generated source page did not include quality metadata")
    if not bool(result.get("lint_ok", False)):
        return SmokeClassification("FAIL", 1, "wiki lint failed in temporary smoke domain")
    if provider in {PROVIDER_GEMINI, PROVIDER_RULE_BASED} and status == "ok":
        return SmokeClassification("PASS", 0)
    return SmokeClassification("FAIL", 1, str(result.get("fallback_reason") or status or "unknown failure"))


def _restore_env_value(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _summary_status(summary: Mapping[str, Any], schema_ok: bool, quality_ok: bool) -> str:
    if _count(summary, "summarized_count") <= 0 and _count(summary, "needs_review_count") <= 0:
        return "failed"
    if not schema_ok or not quality_ok:
        return "failed"
    if _count(summary, "fallback_count"):
        return "fallback"
    return "ok"


def _source_quality_ok(source_text: str) -> bool:
    return "## Quality Review" in source_text and "- quality:" in source_text


def _metadata_value(source_text: str, key: str) -> str:
    for line in source_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {key}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _count(payload: Mapping[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _relative_to_domain(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _command_display(command: str) -> str:
    command = (command or "").strip()
    if not command:
        return "(empty)"
    return shlex.quote(command)


if __name__ == "__main__":
    raise SystemExit(main())
