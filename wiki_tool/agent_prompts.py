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
            "당신은 LLM Wiki Tool v2의 Codex Answer Agent입니다.",
            "사용자의 질문에 답하기 위해 wiki evidence만 사용하세요.",
            "가능한 경우 wiki MCP tools를 사용하세요: " + ", ".join(WIKI_TOOL_NAMES),
            "아래에 제공된 wiki context와 evidence가 있으면 그것을 우선 근거로 사용하세요.",
            "근거가 부족하면 추측하지 말고 status를 no_evidence로 반환하세요.",
            "답변은 자연스러운 한국어로 작성하세요.",
            "최종 출력은 JSON 객체 하나만 반환하세요. Markdown, code fence, 인사말, 설명문을 출력하지 마세요.",
            '필수 JSON 필드: "status", "answer", "used_pages", "related_pages", "evidence"',
            'status는 "ok" 또는 "no_evidence" 중 하나를 사용하세요.',
            "",
            "wiki context:",
            _context_lines(wiki_context or []),
            "",
            "wiki evidence:",
            _evidence_lines(evidence or []),
            "",
            f"질문: {question}",
        ]
    )


def build_ingest_prompt(source_text: str = "") -> str:
    return "\n".join(
        [
            "당신은 LLM Wiki Tool v2의 Ingest Agent입니다.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "제공된 extracted source text만 바탕으로 한국어 source page draft를 작성하세요.",
            "최종 출력은 Markdown 문서 하나만 반환하세요. 인사말, 작업 설명, code fence를 출력하지 마세요.",
            "첫 줄은 반드시 '# <짧은 source 제목>' 형식이어야 합니다.",
            "필수 섹션을 정확한 heading으로 모두 포함하세요:",
            "## Summary",
            "## Key Points",
            "## Evidence",
            "## Candidate Concepts",
            "## Candidate Concept Evidence",
            "약한 source는 억지로 요약하지 말고 Summary와 Evidence에 needs_review 이유를 명확히 적으세요.",
            "",
            "extracted source text:",
            source_text,
        ]
    )


def build_concept_prompt(source_page: str = "") -> str:
    return "\n".join(
        [
            "당신은 LLM Wiki Tool v2의 Concept Agent입니다.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "source page를 바탕으로 concept page draft 또는 기존 concept 병합 초안을 작성하세요.",
            "기존 사람이 작성한 본문을 덮어쓰라는 제안을 하지 마세요.",
            "최종 출력은 Markdown 문서 하나만 반환하세요. 인사말, 작업 설명, code fence를 출력하지 마세요.",
            "첫 줄은 반드시 '# <핵심 개념명>' 형식이어야 합니다.",
            "독자용 설명이 먼저 오도록 다음 섹션을 우선 사용하세요:",
            "## Definition",
            "## Explanation",
            "## Key Points",
            "## Related Concepts",
            "## Source Evidence",
            "## Maintenance Notes",
            "Source Evidence에는 source link 또는 source evidence 문장을 반드시 포함하세요.",
            "",
            "source page:",
            source_page,
        ]
    )


def build_review_prompt(changes_summary: str = "") -> str:
    return "\n".join(
        [
            "당신은 LLM Wiki Tool v2의 Review Agent입니다.",
            "raw 파일은 절대 수정, 이동, 삭제하지 마세요.",
            "생성된 wiki 변경사항을 짧게 검토하세요.",
            "metadata 과다 노출, 근거 부족, 중복 concept, 깨진 링크, private/raw 자료 노출 위험만 확인하세요.",
            "최종 출력은 짧은 한국어 Markdown bullet 목록만 반환하세요. 인사말과 긴 설명은 쓰지 마세요.",
            "",
            "changes summary:",
            changes_summary,
        ]
    )


def _context_lines(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- 없음"
    lines: list[str] = []
    for item in items[:5]:
        lines.append(
            f"- path: {item.get('path', '')}; type: {item.get('type', '')}; "
            f"title: {item.get('title', '')}; snippet: {item.get('snippet', '')}"
        )
    return "\n".join(lines)


def _evidence_lines(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- 없음"
    lines: list[str] = []
    for item in items[:3]:
        lines.append(
            f"- path: {item.get('path', '')}; type: {item.get('type', '')}; "
            f"title: {item.get('title', '')}; text: {item.get('text', '')}"
        )
    return "\n".join(lines)
