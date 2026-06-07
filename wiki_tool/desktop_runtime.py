from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import DomainConfig
from .desktop_presenter import DesktopGuiPresenter, DirectAdapterAgentFallback, McpCodexAgentRoute, _agent_route_line
from .mcp_tools import WikiToolAdapter


PRIMARY_MAINTENANCE_TASK_KEY = "maintenance"
ADVANCED_MAINTENANCE_DEFAULT_VISIBLE = False


@dataclass(frozen=True)
class GuiTaskResult:
    kind: str
    ok: bool
    message: str
    refresh_pages: bool = False
    route_line: str | None = None
    error: str | None = None
    label: str = "작업"


@dataclass(frozen=True)
class GuiTaskSpec:
    key: str
    kind: str
    label: str
    pending_message: str
    task: Callable[[], str]
    refresh_pages: bool


@dataclass(frozen=True)
class DomainRuntime:
    config: DomainConfig
    adapter: Any
    presenter: DesktopGuiPresenter
    maintenance_task_specs: dict[str, GuiTaskSpec]


def build_maintenance_pending_message() -> str:
    return "maintenance 실행 중...\nraw scan, source summary, concept organize, lint를 순서대로 실행합니다."


def build_maintenance_task_specs(presenter: Any) -> dict[str, GuiTaskSpec]:
    return {
        "scan": GuiTaskSpec(
            key="scan",
            kind="maintenance",
            label="raw 스캔",
            pending_message="raw 스캔 실행 중...",
            task=presenter.scan_raw_sources,
            refresh_pages=True,
        ),
        "summarize": GuiTaskSpec(
            key="summarize",
            kind="maintenance",
            label="새 source 요약",
            pending_message="새 source 요약 실행 중...",
            task=presenter.summarize_new_sources,
            refresh_pages=True,
        ),
        "organize": GuiTaskSpec(
            key="organize",
            kind="maintenance",
            label="pending concept 조직",
            pending_message="pending concept 조직 실행 중... concept 후보가 많으면 오래 걸릴 수 있습니다.",
            task=presenter.organize_pending_sources,
            refresh_pages=True,
        ),
        "lint": GuiTaskSpec(
            key="lint",
            kind="maintenance",
            label="wiki lint",
            pending_message="wiki lint 실행 중...",
            task=presenter.run_wiki_lint,
            refresh_pages=False,
        ),
        "maintenance": GuiTaskSpec(
            key="maintenance",
            kind="maintenance",
            label="maintenance 실행",
            pending_message=build_maintenance_pending_message(),
            task=presenter.run_maintenance_workflow,
            refresh_pages=True,
        ),
        "status": GuiTaskSpec(
            key="status",
            kind="maintenance",
            label="상태 새로고침",
            pending_message="상태 새로고침 실행 중...",
            task=presenter.wiki_status,
            refresh_pages=False,
        ),
    }


def primary_maintenance_task_spec(task_specs: dict[str, GuiTaskSpec]) -> GuiTaskSpec:
    return task_specs[PRIMARY_MAINTENANCE_TASK_KEY]


def advanced_maintenance_default_visible() -> bool:
    return ADVANCED_MAINTENANCE_DEFAULT_VISIBLE


def toggle_advanced_maintenance_visible(current_visible: bool) -> bool:
    return not current_visible


def advanced_maintenance_toggle_label(visible: bool) -> str:
    return "고급 관리 접기" if visible else "고급 관리 펼치기"


def maintenance_controls_enabled(*, maintenance_running: bool) -> bool:
    return not maintenance_running


def summarize_maintenance_status(label: str, message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return f"{label} 완료"
    if lines[0] == "Maintenance Run Report":
        status_line = next((line for line in lines if line.startswith("상태:")), "")
        return "\n".join(line for line in [f"{label} 완료", status_line] if line)
    return "\n".join(lines[:2])


def build_domain_runtime(config: DomainConfig, *, adapter_factory: Callable[[DomainConfig], Any] = WikiToolAdapter) -> DomainRuntime:
    adapter = adapter_factory(config)
    presenter = DesktopGuiPresenter(
        adapter,
        agent_route=McpCodexAgentRoute(config, fallback=DirectAdapterAgentFallback(adapter)),
    )
    return DomainRuntime(
        config=config,
        adapter=adapter,
        presenter=presenter,
        maintenance_task_specs=build_maintenance_task_specs(presenter),
    )


def worker_success_result(kind: str, message: str, *, refresh_pages: bool, label: str = "작업") -> GuiTaskResult:
    return GuiTaskResult(kind=kind, ok=True, message=message, refresh_pages=refresh_pages, route_line=_agent_route_line(message) if kind == "agent" else None, label=label)


def worker_failure_result(kind: str, label: str, error: BaseException, *, refresh_pages: bool = False) -> GuiTaskResult:
    message = f"{label} 실패\n오류: {error}"
    route_line = "agent route: 실패" if kind == "agent" else None
    return GuiTaskResult(kind=kind, ok=False, message=message, refresh_pages=refresh_pages, route_line=route_line, error=str(error), label=label)


def create_background_task_worker_class(QObject: Any, Signal: Any) -> type[Any]:
    class BackgroundTaskWorker(QObject):
        succeeded = Signal(object)
        failed = Signal(object)

        def __init__(self, kind: str, label: str, task: Callable[[], str], *, refresh_pages: bool) -> None:
            super().__init__()
            self.kind = kind
            self.label = label
            self.task = task
            self.refresh_pages = refresh_pages

        def run(self) -> None:
            try:
                self.succeeded.emit(worker_success_result(self.kind, self.task(), refresh_pages=self.refresh_pages, label=self.label))
            except Exception as exc:
                self.failed.emit(worker_failure_result(self.kind, self.label, exc))

    return BackgroundTaskWorker
