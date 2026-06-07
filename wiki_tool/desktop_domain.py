from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import DomainConfig, load_domain_config
from .user_domain import UserDomainInitResult, create_user_domain


@dataclass(frozen=True)
class DomainCreationRequest:
    name: str
    slug: str
    description: str = ""
    disclaimer: str = ""


@dataclass(frozen=True)
class GuiDomainCreationResult:
    config: DomainConfig
    domain_file: Path
    message: str


@dataclass(frozen=True)
class RawFolderOpenResult:
    ok: bool
    message: str
    path: Path


def create_gui_user_domain(
    project_root: Path,
    request: DomainCreationRequest,
    *,
    creator: Callable[..., UserDomainInitResult] = create_user_domain,
) -> GuiDomainCreationResult:
    result = creator(
        project_root=project_root,
        slug=request.slug,
        name=request.name,
        description=request.description or None,
        disclaimer=request.disclaimer or None,
    )
    config = load_domain_config(result.domain_file)
    return GuiDomainCreationResult(
        config=config,
        domain_file=result.domain_file,
        message=f"도메인 생성 완료: {config.name} ({config.slug})",
    )


def domain_controls_enabled(*, agent_running: bool, maintenance_running: bool) -> bool:
    return not agent_running and not maintenance_running


def open_domain_raw_folder(config: DomainConfig, *, opener: Callable[[str], Any] | None = None) -> RawFolderOpenResult:
    raw_dir = Path(config.raw_dir)
    if not raw_dir.is_dir():
        return RawFolderOpenResult(ok=False, message=f"raw 폴더가 없습니다: {raw_dir}", path=raw_dir)
    open_folder = opener or getattr(os, "startfile", None)
    if open_folder is None:
        return RawFolderOpenResult(ok=False, message="이 환경에서는 raw 폴더를 열 수 없습니다.", path=raw_dir)
    open_folder(str(raw_dir))
    return RawFolderOpenResult(ok=True, message=f"raw 폴더를 열었습니다: {raw_dir}", path=raw_dir)
