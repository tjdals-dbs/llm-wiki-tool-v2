from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DomainConfig


@dataclass(frozen=True)
class LintIssue:
    path: str
    severity: str
    message: str


@dataclass(frozen=True)
class LintResult:
    ok: bool
    issues: list[LintIssue]


def run_wiki_lint(config: DomainConfig) -> LintResult:
    issues: list[LintIssue] = []
    issues.extend(_concept_evidence_issues(config))
    issues.extend(_broken_link_issues(config))
    return LintResult(ok=not issues, issues=issues)


def _concept_evidence_issues(config: DomainConfig) -> list[LintIssue]:
    concept_dir = config.wiki_dir / "concepts"
    if not concept_dir.exists():
        return []
    issues: list[LintIssue] = []
    for path in sorted(concept_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(config.root).as_posix()
        if "## Source Evidence" not in content:
            issues.append(LintIssue(relative, "error", "Concept page에 Source Evidence 섹션이 없습니다."))
            continue
        section = content.split("## Source Evidence", 1)[1]
        if "../sources/" not in section and "wiki/sources/" not in section:
            issues.append(LintIssue(relative, "error", "Concept page의 Source Evidence가 source page를 링크하지 않습니다."))
    return issues


def _broken_link_issues(config: DomainConfig) -> list[LintIssue]:
    if not config.wiki_dir.exists():
        return []
    issues: list[LintIssue] = []
    for path in sorted(config.wiki_dir.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(config.root).as_posix()
        for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if href.startswith(("http://", "https://", "#")):
                continue
            target = (path.parent / href).resolve()
            if not (config.root == target or config.root in target.parents) or not target.exists():
                issues.append(LintIssue(relative, "error", f"깨진 링크입니다: {href}"))
    return issues
