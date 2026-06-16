from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_provider import load_agent_provider_config
from wiki_tool.config import load_domain_config
from wiki_tool.env_loader import load_dotenv_if_present
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

PIPELINE_RAW_TEXT = (
    "# CAPM Note\n\n"
    "CAPM은 자산의 기대수익률을 무위험수익률, 베타, 시장위험프리미엄으로 설명하는 모형이다. "
    "베타는 시장 포트폴리오 변화에 대한 민감도를 나타낸다.\n"
)


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
    parser.add_argument("--include-pipeline", action="store_true", help="run raw->source->concept smoke in a temp domain")
    args = parser.parse_args(argv)

    load_environment_for_smoke()
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

    pipeline: dict[str, Any] | None = None
    if args.include_pipeline:
        try:
            pipeline = run_pipeline_smoke()
        except Exception as exc:
            pipeline = {"error": str(exc)}
        print_pipeline_smoke(pipeline)

    classification = classify_result(cli_check, answer, pipeline)
    print_summary(classification, cli_check, answer, pipeline)
    return classification.exit_code


def load_environment_for_smoke(project_root: Path | None = None) -> dict[str, str]:
    return load_dotenv_if_present(project_root or PROJECT_ROOT)


def summarize_environment(env: Mapping[str, str]) -> dict[str, Any]:
    answer_config = load_agent_provider_config("answer", env, auto_detect=True)
    codex_command = answer_config.provider_command or answer_config.codex_command
    role_models = {
        "answer": answer_config.model,
        "ingest": load_agent_provider_config("ingest", env, auto_detect=True).model,
        "concept": load_agent_provider_config("concept", env, auto_detect=True).model,
        "review": load_agent_provider_config("review", env, auto_detect=True).model,
    }
    return {
        "variables": {name: bool(env.get(name, "").strip()) for name in ENV_NAMES},
        "provider": answer_config.provider,
        "resolved_models": role_models,
        "codex_command": codex_command,
        "codex_command_display": _command_display(codex_command),
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
    config = load_agent_provider_config("answer", auto_detect=True)
    command = shlex.split(codex_command or config.provider_command or config.codex_command, posix=False)
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
    with tempfile.TemporaryDirectory(prefix="llm_wiki_codex_answer_") as tmp:
        copied_domain = copy_domain_for_answer_smoke(Path(domain_path), Path(tmp))
        config = load_domain_config(copied_domain)
        adapter = adapter_cls(config)
        answer = adapter.answer_question(question)
        return normalize_answer_result(answer)


def copy_domain_for_answer_smoke(domain_path: Path, temp_root: Path) -> Path:
    source_config = load_domain_config(domain_path)
    temp_root.mkdir(parents=True, exist_ok=True)
    copied_domain = temp_root / domain_path.name
    copied_domain.write_text(domain_path.read_text(encoding="utf-8"), encoding="utf-8")

    raw_relative = source_config.raw_dir.relative_to(source_config.root)
    (temp_root / raw_relative).mkdir(parents=True, exist_ok=True)
    wiki_relative = source_config.wiki_dir.relative_to(source_config.root)
    copied_wiki = temp_root / wiki_relative
    if source_config.wiki_dir.exists():
        shutil.copytree(source_config.wiki_dir, copied_wiki, dirs_exist_ok=True)
    else:
        copied_wiki.mkdir(parents=True, exist_ok=True)
    return copied_domain


def normalize_answer_result(answer: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(answer)
    normalized["fallback"] = bool(answer.get("fallback", False))
    normalized["answer_preview"] = _preview(str(answer.get("answer", "")))
    normalized["used_pages_count"] = len(answer.get("used_pages", []) or [])
    normalized["evidence_count"] = len(answer.get("evidence", []) or [])
    return normalized


def create_pipeline_smoke_domain(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    raw_dir = root / "raw"
    wiki_dir = root / "wiki"
    manifest_dir = root / "manifests"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / "capm-note.md"
    raw_path.write_text(PIPELINE_RAW_TEXT, encoding="utf-8")
    domain_path = root / "domain.yml"
    domain_path.write_text(
        "\n".join(
            [
                "name: Codex Pipeline Smoke",
                "slug: codex-pipeline-smoke",
                "description: Public-safe temporary smoke domain.",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                "language: ko",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return domain_path, raw_path


def run_pipeline_smoke(*, adapter_cls: type[Any] = WikiToolAdapter) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="llm_wiki_codex_pipeline_") as tmp:
        domain_path, raw_path = create_pipeline_smoke_domain(Path(tmp))
        before_hash = _sha256(raw_path)
        config = load_domain_config(domain_path)
        adapter = adapter_cls(config)

        scan = adapter.scan_raw_sources()
        summarize = adapter.summarize_new_sources()
        organize = adapter.organize_pending_sources()
        lint = adapter.run_wiki_lint()
        after_hash = _sha256(raw_path)

        return {
            "scan_new_count": scan.get("new_count", 0),
            "source_provider": summarize.get("provider", "rule_based"),
            "source_codex_used_count": summarize.get("codex_used_count", 0),
            "source_fallback_count": summarize.get("fallback_count", 0),
            "source_summarized_count": summarize.get("summarized_count", 0),
            "source_needs_review_count": summarize.get("needs_review_count", 0),
            "concept_provider": organize.get("provider", "rule_based"),
            "concept_codex_used_count": organize.get("codex_used_count", 0),
            "concept_fallback_count": organize.get("fallback_count", 0),
            "promoted_count": organize.get("promoted_count", 0),
            "merged_count": organize.get("merged_count", 0),
            "lint_ok": bool(lint.get("ok", False)),
            "lint_issues_count": len(lint.get("issues", []) or []),
            "lint_issues": _compact_lint_issues(lint.get("issues", []) or []),
            "generated_source_pages_count": _count_markdown_pages(config.wiki_dir / "sources"),
            "generated_concept_pages_count": _count_markdown_pages(config.wiki_dir / "concepts"),
            "raw_unchanged": before_hash == after_hash,
        }


def classify_result(
    cli_check: CodexCliCheck,
    answer: dict[str, Any],
    pipeline: dict[str, Any] | None = None,
) -> SmokeClassification:
    if not cli_check.ok:
        return SmokeClassification("FAIL", 1)
    if pipeline is not None:
        if pipeline.get("error") or not pipeline.get("raw_unchanged", True) or not pipeline.get("lint_ok", False):
            return SmokeClassification("FAIL", 1)
        if int(pipeline.get("source_fallback_count", 0)) > 0 or int(pipeline.get("concept_fallback_count", 0)) > 0:
            return SmokeClassification("FALLBACK", 0)
        if int(pipeline.get("source_codex_used_count", 0)) <= 0 or int(pipeline.get("concept_codex_used_count", 0)) <= 0:
            return SmokeClassification("FALLBACK", 0)
    if answer.get("provider") == "codex" and not answer.get("fallback") and answer.get("status") == "ok":
        return SmokeClassification("PASS", 0)
    if answer.get("fallback"):
        return SmokeClassification("FALLBACK", 0)
    return SmokeClassification("FAIL", 1)


def print_summary(
    classification: SmokeClassification,
    cli_check: CodexCliCheck,
    answer: dict[str, Any],
    pipeline: dict[str, Any] | None = None,
) -> None:
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
    if pipeline:
        print(f"- Pipeline source provider: {pipeline.get('source_provider', '')}")
        print(f"- Pipeline source Codex used: {pipeline.get('source_codex_used_count', 0)}")
        print(f"- Pipeline concept provider: {pipeline.get('concept_provider', '')}")
        print(f"- Pipeline concept Codex used: {pipeline.get('concept_codex_used_count', 0)}")
        print(f"- Lint: {'ok' if pipeline.get('lint_ok') else 'fail'}")


def print_pipeline_smoke(pipeline: dict[str, Any]) -> None:
    print("")
    print("Pipeline Smoke")
    if pipeline.get("error"):
        print(f"- error: {pipeline['error']}")
        return
    print(f"- scan new_count: {pipeline.get('scan_new_count', 0)}")
    print(f"- source provider: {pipeline.get('source_provider', '')}")
    print(f"- source codex_used_count: {pipeline.get('source_codex_used_count', 0)}")
    print(f"- source fallback_count: {pipeline.get('source_fallback_count', 0)}")
    print(f"- source summarized_count: {pipeline.get('source_summarized_count', 0)}")
    print(f"- source needs_review_count: {pipeline.get('source_needs_review_count', 0)}")
    print(f"- concept provider: {pipeline.get('concept_provider', '')}")
    print(f"- concept codex_used_count: {pipeline.get('concept_codex_used_count', 0)}")
    print(f"- concept fallback_count: {pipeline.get('concept_fallback_count', 0)}")
    print(f"- promoted_count: {pipeline.get('promoted_count', 0)}")
    print(f"- merged_count: {pipeline.get('merged_count', 0)}")
    print(f"- lint ok: {str(pipeline.get('lint_ok', False)).lower()}")
    print(f"- lint issues count: {pipeline.get('lint_issues_count', 0)}")
    for issue in pipeline.get("lint_issues", [])[:3]:
        print(f"- lint issue: {issue}")
    print(f"- generated source pages count: {pipeline.get('generated_source_pages_count', 0)}")
    print(f"- generated concept pages count: {pipeline.get('generated_concept_pages_count', 0)}")
    print(f"- raw unchanged: {str(pipeline.get('raw_unchanged', False)).lower()}")


def _command_display(command: str) -> str:
    parts = shlex.split(command, posix=False)
    if not parts:
        return "codex.cmd"
    return Path(parts[0]).name


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count_markdown_pages(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.glob("*.md") if item.is_file())


def _compact_lint_issues(issues: list[Mapping[str, Any]]) -> list[str]:
    compact: list[str] = []
    for issue in issues[:5]:
        path = str(issue.get("path", "")).strip()
        message = str(issue.get("message", "")).strip()
        if path and message:
            compact.append(f"{path}: {message}")
        elif path:
            compact.append(path)
        elif message:
            compact.append(message)
    return compact


if __name__ == "__main__":
    sys.exit(main())
