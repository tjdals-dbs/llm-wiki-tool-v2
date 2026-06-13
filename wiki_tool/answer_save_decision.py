from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SAVE_ACTION_SAVE = "save"
SAVE_ACTION_SKIP = "skip"
DECISION_MADE_BY = "agent_policy"
SUGGESTED_PAGE_TYPE = "answer"
TITLE_MAX_LENGTH = 40
PREVIEW_MAX_LENGTH = 240


@dataclass(frozen=True)
class AnswerSaveDecision:
    save_action: str
    save_eligible: bool
    save_reason: str
    suggested_title: str
    suggested_page_type: str
    decision_made_by: str
    question: str
    answer_preview: str
    used_pages: list[dict[str, Any]]
    related_pages: list[dict[str, Any]]
    evidence: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "save_action": self.save_action,
            "save_eligible": self.save_eligible,
            "save_reason": self.save_reason,
            "suggested_title": self.suggested_title,
            "suggested_page_type": self.suggested_page_type,
            "decision_made_by": self.decision_made_by,
            "question": self.question,
            "answer_preview": self.answer_preview,
            "used_pages": self.used_pages,
            "related_pages": self.related_pages,
            "evidence": self.evidence,
        }


def decide_answer_save(question: str, answer_payload: dict[str, Any]) -> AnswerSaveDecision:
    status = str(answer_payload.get("status") or "").strip()
    fallback = bool(answer_payload.get("fallback"))
    answer = _single_line(str(answer_payload.get("answer") or ""))
    used_pages = _list_of_dicts(answer_payload.get("used_pages"))
    related_pages = _list_of_dicts(answer_payload.get("related_pages"))
    evidence = _list_of_dicts(answer_payload.get("evidence"))

    action, reason = _save_action_and_reason(
        status=status,
        fallback=fallback,
        answer=answer,
        used_pages=used_pages,
        evidence=evidence,
    )
    return AnswerSaveDecision(
        save_action=action,
        save_eligible=action == SAVE_ACTION_SAVE,
        save_reason=reason,
        suggested_title=suggested_answer_title(question),
        suggested_page_type=SUGGESTED_PAGE_TYPE,
        decision_made_by=DECISION_MADE_BY,
        question=question,
        answer_preview=_truncate(answer, PREVIEW_MAX_LENGTH),
        used_pages=used_pages,
        related_pages=related_pages,
        evidence=evidence,
    )


def suggested_answer_title(question: str) -> str:
    title = _single_line(question)
    title = re.sub(r"[?？!！。.\s]+$", "", title).strip()
    return _truncate(title or "질문 답변", TITLE_MAX_LENGTH)


def _save_action_and_reason(
    *,
    status: str,
    fallback: bool,
    answer: str,
    used_pages: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[str, str]:
    if status == "no_evidence":
        return SAVE_ACTION_SKIP, "근거가 부족해 위키에 저장하지 않습니다."
    if fallback:
        return SAVE_ACTION_SKIP, "fallback 답변은 위키 저장 대상이 아닙니다."
    if not answer:
        return SAVE_ACTION_SKIP, "답변 본문이 비어 있어 위키에 저장하지 않습니다."
    if status != "ok":
        return SAVE_ACTION_SKIP, "답변 상태가 ok가 아니어서 위키에 저장하지 않습니다."
    if not evidence and not used_pages:
        return SAVE_ACTION_SKIP, "근거 문서가 없어 위키에 저장하지 않습니다."
    return SAVE_ACTION_SAVE, "근거 문서가 있어 위키 저장 대상으로 판단했습니다."


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ").replace("\t", " ")).strip()


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - 3)].rstrip() + "..."


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
