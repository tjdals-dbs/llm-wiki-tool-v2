from __future__ import annotations

from typing import Any


WIKI_TOOL_NAMES = ["ask_wiki_context", "search_wiki", "read_wiki_page", "get_related_pages"]


def build_answer_prompt(
    question: str,
    *,
    wiki_context: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> str:
    return "\n".join(
        [
            "You are the Codex answer provider for LLM Wiki Tool v2.",
            "답변은 한국어로 작성하세요.",
            "Answer in Korean using only the supplied wiki evidence.",
            "Use wiki MCP tools when useful: " + ", ".join(WIKI_TOOL_NAMES),
            "If evidence is insufficient, set status to no_evidence.",
            "Return exactly one JSON object. Do not use markdown fences or commentary.",
            'Required JSON fields: "status", "answer", "used_pages", "related_pages", "evidence".',
            'Use status "ok" or "no_evidence".',
            "",
            "wiki context:",
            _context_lines(wiki_context or []),
            "",
            "wiki evidence:",
            _evidence_lines(evidence or []),
            "",
            f"question: {question}",
        ]
    )


def build_gemini_answer_prompt(
    question: str,
    *,
    wiki_context: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> str:
    return "\n".join(
        [
            "Transform only the supplied wiki context into an answer.",
            "Do not inspect files, do not describe your plan, and do not ask for another task.",
            "Answer in Korean using only the supplied wiki context and evidence.",
            "Return exactly one JSON object and nothing else. No markdown fences.",
            'Required JSON fields: "status", "answer", "used_pages", "related_pages", "evidence".',
            'Schema: {"status":"ok","answer":"...","used_pages":[],"related_pages":[],"evidence":[]}',
            'Use status "no_evidence" if the supplied evidence is insufficient.',
            "",
            "context:",
            _context_lines(wiki_context or [], limit=3, text_limit=260),
            "",
            "evidence:",
            _evidence_lines(evidence or [], limit=2, text_limit=420),
            "",
            f"question: {_truncate(str(question), 300)}",
        ]
    )


def build_ingest_prompt(source_text: str = "") -> str:
    return "\n".join(
        [
            "Transform only the supplied raw text into one source summary page.",
            "Do not inspect files, do not examine the project, do not describe your plan.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "Never edit, move, delete, or rewrite raw files.",
            "Use only the extracted source text below.",
            "Return exactly one Markdown source page draft. No code fences. No preface.",
            "첫 줄은 반드시 '# <짧은 source 제목>' 형식이어야 합니다.",
            "The first line must be '# <short source title>'.",
            "Use this exact section skeleton and keep every heading:",
            "",
            "# <short source title>",
            "",
            "## Summary",
            "",
            "<2-4 source-grounded sentences. If weak, explain needs_review here.>",
            "",
            "## Key Points",
            "",
            "- <source-grounded point>",
            "",
            "## Evidence",
            "",
            "- <short quote or faithful paraphrase from the source>",
            "",
            "## Candidate Concepts",
            "",
            "- <short concept name or noun phrase>",
            "",
            "## Candidate Concept Evidence",
            "",
            "- <concept name>: <source-grounded evidence sentence>",
            "",
            "Do not invent candidate concepts without source evidence.",
            "Candidate concepts must be short nouns, noun phrases, acronyms, or technical terms.",
            "If the source is too weak, still return the skeleton and state needs_review in Summary/Evidence.",
            "",
            "extracted source text:",
            _truncate(source_text, 12000),
        ]
    )


def build_concept_prompt(source_page: str = "") -> str:
    return "\n".join(
        [
            "Transform only the supplied source page into one concept page draft.",
            "Do not inspect files, do not examine the project, do not describe your plan.",
            "You are the LLM Wiki Tool v2 Concept Agent.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "Never edit raw files. Preserve existing human-written concept content.",
            "Use only the source page context below.",
            "Return exactly one Markdown concept page draft. No code fences. No preface.",
            "The first line must be '# <concept name>'.",
            "Use this exact section skeleton and keep every heading:",
            "",
            "# <concept name>",
            "",
            "## Definition",
            "",
            "<one concise reader-facing definition grounded in the source>",
            "",
            "## Explanation",
            "",
            "<plain-language explanation for a wiki reader>",
            "",
            "## Key Points",
            "",
            "- <source-grounded point>",
            "",
            "## Related Concepts",
            "",
            "- <related concept name, or none>",
            "",
            "## Source Evidence",
            "",
            "- <source page link or source-grounded evidence sentence>",
            "",
            "## Maintenance Notes",
            "",
            "- Generated from source summary evidence.",
            "",
            "Definition or Explanation must be present and useful to a reader.",
            "Source Evidence must include a source link or source evidence sentence.",
            "",
            "source page:",
            _truncate(source_page, 12000),
        ]
    )


def build_review_prompt(changes_summary: str = "") -> str:
    return "\n".join(
        [
            "You are the LLM Wiki Tool v2 review agent.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "Never edit, move, delete, or rewrite raw files.",
            "Review the generated wiki change summary briefly.",
            "Check for metadata leaks, weak evidence, duplicate concepts, broken links, and private/raw exposure.",
            "Return only a concise Korean Markdown bullet list. No preface.",
            "",
            "changes summary:",
            changes_summary,
        ]
    )


def _context_lines(items: list[dict[str, Any]], *, limit: int = 5, text_limit: int = 800) -> str:
    if not items:
        return "- none"
    lines: list[str] = []
    for item in items[:limit]:
        lines.append(
            f"- path: {item.get('path', '')}; type: {item.get('type', '')}; "
            f"title: {_truncate(str(item.get('title', '')), 120)}; "
            f"snippet: {_truncate(str(item.get('snippet', '')), text_limit)}"
        )
    return "\n".join(lines)


def _evidence_lines(items: list[dict[str, Any]], *, limit: int = 3, text_limit: int = 900) -> str:
    if not items:
        return "- none"
    lines: list[str] = []
    for item in items[:limit]:
        lines.append(
            f"- path: {item.get('path', '')}; type: {item.get('type', '')}; "
            f"title: {_truncate(str(item.get('title', '')), 120)}; "
            f"text: {_truncate(str(item.get('text', '')), text_limit)}"
        )
    return "\n".join(lines)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."
