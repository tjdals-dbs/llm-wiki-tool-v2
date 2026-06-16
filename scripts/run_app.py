from __future__ import annotations

import argparse
import importlib
import os
import platform
import sys
from pathlib import Path
from typing import Callable, Mapping, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_tool.agent_provider import (
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    CliRunner,
    detect_agent_providers,
    load_agent_provider_config,
)
from wiki_tool.config import DomainConfig, load_domain_config
from wiki_tool.env_loader import load_dotenv_if_present


ROLES = ("answer", "ingest", "concept", "review")


class RunAppError(ValueError):
    pass


def resolve_domain_file(
    *,
    project_root: Path,
    cli_domain: str | None,
    env: Mapping[str, str] | None = None,
) -> Path:
    source = os.environ if env is None else env
    root = project_root.resolve()
    if cli_domain:
        return _require_domain_file(_resolve_path(cli_domain, root))

    env_domain = source.get("LLM_WIKI_DOMAIN", "").strip()
    if env_domain:
        return _require_domain_file(_resolve_path(env_domain, root))

    discovered = _discover_default_domain_files(root)
    if discovered:
        return discovered[0]

    fallback = root / "examples" / "finance" / "domain.yml"
    if fallback.is_file():
        return fallback.resolve()
    raise RunAppError(
        "No domain.yml found. Pass --domain <path>, set LLM_WIKI_DOMAIN, or create a user domain with scripts/init_user_domain.py."
    )


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    load_dotenv: bool = True,
    launch_gui: Callable[[DomainConfig], None] | None = None,
    cli_runner: CliRunner | None = None,
    pyside6_checker: Callable[[], bool] | None = None,
) -> int:
    root = project_root.resolve()
    if load_dotenv and env is None:
        load_dotenv_if_present(root)

    parser = argparse.ArgumentParser(description="Run the LLM Wiki desktop app.")
    parser.add_argument("--domain", help="Path to domain.yml")
    parser.add_argument("--check", action="store_true", help="Print environment/domain/provider diagnostics without opening the GUI")
    args = parser.parse_args(argv)

    source = os.environ if env is None else env
    try:
        domain_file = resolve_domain_file(project_root=root, cli_domain=args.domain, env=source)
        config = load_domain_config(domain_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=stderr)
        return 1

    if args.check:
        _print_check_report(
            domain_file=domain_file,
            env=source,
            stdout=stdout,
            cli_runner=cli_runner,
            pyside6_checker=pyside6_checker or _can_import_pyside6,
        )
        return 0

    gui_launcher = launch_gui or _launch_desktop_gui
    gui_launcher(config)
    return 0


def _discover_default_domain_files(project_root: Path) -> list[Path]:
    candidates = [
        *sorted((project_root / "user_domains").glob("*/domain.yml")),
        *sorted((project_root / "examples").glob("*/domain.yml")),
    ]
    valid: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        try:
            load_domain_config(resolved)
        except Exception:
            continue
        seen.add(resolved)
        valid.append(resolved)
    return valid


def _require_domain_file(path: Path) -> Path:
    if not path.is_file():
        raise RunAppError(f"Domain file not found: {path}")
    try:
        load_domain_config(path)
    except Exception as exc:
        raise RunAppError(f"Invalid domain file: {path} ({exc})") from exc
    return path.resolve()


def _resolve_path(path_text: str, project_root: Path) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _print_check_report(
    *,
    domain_file: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    cli_runner: CliRunner | None,
    pyside6_checker: Callable[[], bool],
) -> None:
    print(f"resolved domain path: {domain_file}", file=stdout)
    print(f"Python version: {platform.python_version()}", file=stdout)
    print(f"OS/platform: {platform.platform()}", file=stdout)
    print(f"PySide6 import: {'ok' if pyside6_checker() else 'unavailable'}", file=stdout)

    detections = {item.provider: item for item in detect_agent_providers(role="answer", env=env, runner=cli_runner)}
    for provider, label in ((PROVIDER_CODEX, "Codex CLI"), (PROVIDER_GEMINI, "Gemini CLI")):
        detection = detections.get(provider)
        if detection is None:
            print(f"{label}: unavailable", file=stdout)
            continue
        state = "usable" if detection.usable else "unavailable"
        detail = f" ({detection.command}: {detection.status_message})" if detection.command else f" ({detection.status_message})"
        print(f"{label}: {state}{detail}", file=stdout)

    print("selected providers:", file=stdout)
    for role in ROLES:
        config = load_agent_provider_config(role, env=env, runner=cli_runner, auto_detect=True)
        model = config.model or "default"
        command = f", command={config.provider_command}" if config.provider_command else ""
        print(f"  {role}: {config.provider} / {model}{command}", file=stdout)


def _can_import_pyside6() -> bool:
    try:
        importlib.import_module("PySide6")
    except ModuleNotFoundError:
        return False
    return True


def _launch_desktop_gui(config: DomainConfig) -> None:
    from wiki_tool.desktop_gui import run_desktop_gui

    run_desktop_gui(config)


if __name__ == "__main__":
    sys.exit(main())
