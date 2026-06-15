from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(1, str(SCRIPT_DIR))

import smoke_answer_provider  # noqa: E402
import smoke_gemini_concept  # noqa: E402
import smoke_gemini_ingest  # noqa: E402
from wiki_tool.agent_provider import DEFAULT_GEMINI_MODEL, PROVIDER_GEMINI  # noqa: E402
from wiki_tool.env_loader import load_dotenv_if_present  # noqa: E402


DEFAULT_MODEL_CANDIDATES = (
    DEFAULT_GEMINI_MODEL,
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
)
ROLE_CHOICES = ("ingest", "concept", "answer")
ROLE_PROVIDER_ENV = {
    "ingest": "LLM_WIKI_INGEST_PROVIDER",
    "concept": "LLM_WIKI_CONCEPT_PROVIDER",
    "answer": "LLM_WIKI_ANSWER_PROVIDER",
}
ROLE_MODEL_ENV = {
    "ingest": "LLM_WIKI_INGEST_MODEL",
    "concept": "LLM_WIKI_CONCEPT_MODEL",
    "answer": "LLM_WIKI_ANSWER_MODEL",
}


class MatrixRow(NamedTuple):
    model: str
    role: str
    result: str
    provider: str
    fallback: bool
    status: str
    reason: str
    details: Mapping[str, Any]


RoleRunner = Callable[[str, str, Path, str], MatrixRow]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gemini model candidates across LLM Wiki smoke roles")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Gemini model id candidate to test; repeat to compare multiple ids",
    )
    parser.add_argument(
        "--role",
        action="append",
        dest="roles",
        choices=[*ROLE_CHOICES, "all"],
        help="role to test; repeat for multiple roles (default: all)",
    )
    parser.add_argument(
        "--domain",
        default=str(PROJECT_ROOT / "examples" / "finance" / "domain.yml"),
        help="domain.yml used for answer smoke",
    )
    parser.add_argument(
        "--question",
        default="CAPM은 무엇인가?",
        help="question used for answer smoke",
    )
    parser.add_argument(
        "--ignore-dotenv",
        action="store_true",
        help="do not load the repository .env file; OS environment variables are still respected",
    )
    args = parser.parse_args(argv)

    models = normalize_models(args.models)
    roles = normalize_roles(args.roles)
    env_load = load_environment_for_matrix(ignore_dotenv=args.ignore_dotenv)

    print("Environment")
    for line in format_environment_summary(env_load):
        print(f"- {line}")

    print("")
    print("Gemini Model Matrix")
    print("- note: Gemini CLI did not expose a local model-list command in this environment.")
    print("- note: candidate ids are smoke-tested empirically; invalid ids are reported per row.")

    rows = run_model_matrix(
        models=models,
        roles=roles,
        domain_path=Path(args.domain),
        question=args.question,
    )
    print(format_matrix_report(rows, roles))

    exit_code = matrix_exit_code(rows, roles)
    print("")
    print(f"SMOKE RESULT: {'PASS' if exit_code == 0 else 'FAIL'}")
    return exit_code


def normalize_models(models: Iterable[str] | None) -> list[str]:
    values = [model.strip() for model in (models or []) if model and model.strip()]
    if not values:
        values = list(DEFAULT_MODEL_CANDIDATES)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def normalize_roles(roles: Iterable[str] | None) -> list[str]:
    values = [role for role in (roles or []) if role]
    if not values or "all" in values:
        return list(ROLE_CHOICES)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def load_environment_for_matrix(project_root: Path | None = None, *, ignore_dotenv: bool = False) -> dict[str, Any]:
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


def format_environment_summary(env_load: Mapping[str, Any]) -> list[str]:
    loaded_text = "no (--ignore-dotenv)" if env_load.get("ignored") else _yes_no(bool(env_load.get("loaded")))
    lines = [
        f".env exists: {_yes_no(bool(env_load.get('exists')))}",
        f".env loaded: {loaded_text}",
    ]
    loaded_keys = env_load.get("loaded_keys") or []
    if loaded_keys:
        lines.append(f".env loaded keys: {', '.join(str(key) for key in loaded_keys)}")
    return lines


def run_model_matrix(
    *,
    models: list[str],
    roles: list[str],
    domain_path: Path,
    question: str,
    role_runner: RoleRunner | None = None,
) -> list[MatrixRow]:
    runner = role_runner or run_role_smoke
    rows: list[MatrixRow] = []
    for model in models:
        for role in roles:
            with role_model_environment(role, model):
                try:
                    rows.append(runner(role, model, domain_path, question))
                except Exception as exc:
                    rows.append(
                        MatrixRow(
                            model=model,
                            role=role,
                            result="FAIL",
                            provider=PROVIDER_GEMINI,
                            fallback=False,
                            status="runtime_error",
                            reason=str(exc),
                            details={},
                        )
                    )
    return rows


@contextmanager
def role_model_environment(role: str, model: str):
    provider_env = ROLE_PROVIDER_ENV[role]
    model_env = ROLE_MODEL_ENV[role]
    previous_provider = os.environ.get(provider_env)
    previous_model = os.environ.get(model_env)
    os.environ[provider_env] = PROVIDER_GEMINI
    os.environ[model_env] = model
    try:
        yield
    finally:
        _restore_env_value(provider_env, previous_provider)
        _restore_env_value(model_env, previous_model)


def run_role_smoke(role: str, model: str, domain_path: Path, question: str) -> MatrixRow:
    if role == "ingest":
        diagnostic = smoke_gemini_ingest.collect_gemini_cli_diagnostic(os.environ)
        result = smoke_gemini_ingest.run_ingest_smoke()
        classification = smoke_gemini_ingest.classify_smoke_result(result, diagnostic, forced_provider=PROVIDER_GEMINI)
        return row_from_result(
            model=model,
            role=role,
            result=result,
            classification_label=classification.label,
            status_key="source_summary_status",
            provider_key="resolved_ingest_provider",
        )
    if role == "concept":
        diagnostic = smoke_gemini_concept.collect_gemini_cli_diagnostic(os.environ)
        result = smoke_gemini_concept.run_concept_smoke()
        classification = smoke_gemini_concept.classify_smoke_result(result, diagnostic, forced_provider=PROVIDER_GEMINI)
        return row_from_result(
            model=model,
            role=role,
            result=result,
            classification_label=classification.label,
            status_key="concept_summary_status",
            provider_key="resolved_concept_provider",
        )
    if role == "answer":
        diagnostics = smoke_answer_provider.collect_cli_diagnostics(os.environ)
        result = smoke_answer_provider.run_answer_smoke(domain_path, question, provider=PROVIDER_GEMINI)
        classification = smoke_answer_provider.classify_smoke_result(
            result,
            diagnostics,
            forced_provider=PROVIDER_GEMINI,
            question=question,
        )
        return row_from_result(
            model=model,
            role=role,
            result=result,
            classification_label=classification.label,
            status_key="status",
            provider_key="provider",
        )
    raise ValueError(f"unsupported role: {role}")


def row_from_result(
    *,
    model: str,
    role: str,
    result: Mapping[str, Any],
    classification_label: str,
    status_key: str,
    provider_key: str,
) -> MatrixRow:
    return MatrixRow(
        model=model,
        role=role,
        result=classification_label,
        provider=str(result.get(provider_key, "")),
        fallback=bool(result.get("fallback", False)),
        status=str(result.get(status_key, "")),
        reason=_row_reason(result),
        details=dict(result),
    )


def matrix_exit_code(rows: list[MatrixRow], roles: list[str]) -> int:
    for role in roles:
        if not any(row.role == role and row.result == "PASS" for row in rows):
            return 1
    return 0


def format_matrix_report(rows: list[MatrixRow], roles: list[str]) -> str:
    headers = ["role", "model", "result", "provider", "fallback", "status", "reason"]
    values = [
        [
            row.role,
            row.model,
            row.result,
            row.provider or "-",
            str(row.fallback).lower(),
            row.status or "-",
            _truncate(row.reason or "-", 54),
        ]
        for row in rows
    ]
    widths = [len(header) for header in headers]
    for value_row in values:
        for index, value in enumerate(value_row):
            widths[index] = max(widths[index], min(len(value), 54))

    def fmt(parts: list[str]) -> str:
        return "  ".join(part.ljust(widths[index]) for index, part in enumerate(parts))

    lines = [fmt(headers), fmt(["-" * width for width in widths])]
    lines.extend(fmt(row) for row in values)
    lines.append("")
    lines.append("Recommendations")
    lines.extend(f"- {line}" for line in format_recommendations(rows, roles).splitlines())
    return "\n".join(lines)


def format_recommendations(rows: list[MatrixRow], roles: list[str]) -> str:
    lines: list[str] = []
    for role in roles:
        passing = next((row for row in rows if row.role == role and row.result == "PASS"), None)
        if passing:
            lines.append(f"{role}: {passing.model}")
        else:
            lines.append(f"{role}: no passing model")
    return "\n".join(lines)


def _row_reason(result: Mapping[str, Any]) -> str:
    for key in [
        "validation_error",
        "fallback_reason",
        "gemini_status",
        "source_summary_status",
        "concept_summary_status",
        "status",
    ]:
        value = result.get(key)
        if value:
            return str(value)
    return ""


def _restore_env_value(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
