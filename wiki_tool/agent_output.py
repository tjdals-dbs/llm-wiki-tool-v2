from __future__ import annotations

import re


_FENCE_PATTERN = re.compile(r"```([A-Za-z0-9_-]*)\s*\n(.*?)\n```", flags=re.DOTALL)


def first_code_fence_body(text: str, *, languages: set[str] | None = None) -> str:
    """Return the first fenced block body, optionally restricted by language."""
    allowed = {language.casefold() for language in languages} if languages is not None else None
    for match in _FENCE_PATTERN.finditer(text.strip()):
        language = (match.group(1) or "").strip().casefold()
        if allowed is None or language in allowed:
            return match.group(2).strip()
    return ""


def normalize_agent_markdown_draft(text: str) -> str:
    """Remove common CLI wrappers while keeping the draft subject to validators."""
    normalized = text.strip()
    fenced = first_code_fence_body(normalized, languages={"", "markdown", "md"})
    if fenced:
        normalized = fenced.strip()
    else:
        lines = normalized.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("# "):
                normalized = "\n".join(lines[index:]).strip()
                break

    lines = [line for line in normalized.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def preview_text(text: str, *, limit: int = 800) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: max(0, limit - 3)].rstrip() + "..."
