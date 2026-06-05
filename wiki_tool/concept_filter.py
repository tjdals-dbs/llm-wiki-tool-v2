from __future__ import annotations

import re


GENERIC_CONCEPTS = {
    "source",
    "untitled",
    "note",
    "notes",
    "memo",
    "document",
    "home",
    "menu",
    "login",
    "search",
    "문서",
    "자료",
    "메모",
    "일반 메모",
    "개요",
    "요약",
    "소개",
}

ALLOWED_PUNCTUATION = set("()/-+&._ ·")
SENTENCE_ENDINGS = (
    "입니다",
    "합니다",
    "됩니다",
    "아닙니다",
    "않습니다",
    "이었다",
    "였다",
    "이다",
    "한다",
    "된다",
    "했다",
    "였다",
    "있다",
    "없다",
    "않다",
    "아니다",
    "넣는다",
    "나타낸다",
    "설명한다",
)
TRUNCATED_PREDICATE_ENDINGS = (
    "설명하",
    "나타내",
    "사용하",
    "제공하",
    "포함하",
    "생성하",
    "변경하",
    "감지하",
    "만든",
    "넣는",
    "되면",
    "안 된다",
)
PARTICLE_PATTERN = re.compile(
    r"[\w가-힣]+(?:은|는|이|가|을|를|에|에서|에게|으로|로|와|과|도|만)\s+"
)


def filter_candidate_concepts(values: list[str]) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_candidate_concept(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(cleaned)
    return filtered


def clean_candidate_concept(value: str) -> str:
    cleaned = _clean_surface(value)
    if not is_valid_candidate_concept(cleaned):
        return ""
    return cleaned


def is_valid_candidate_concept(value: str) -> bool:
    cleaned = _clean_surface(value)
    if len(cleaned) < 2 or len(cleaned) > 80:
        return False
    if cleaned.casefold() in GENERIC_CONCEPTS:
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,}", cleaned):
        return True
    if _has_disallowed_punctuation(cleaned):
        return False
    words = cleaned.split()
    if len(words) > 7:
        return False
    if _has_hangul(cleaned) and len(cleaned) > 36 and len(words) >= 4:
        return False
    if _looks_like_sentence(cleaned):
        return False
    return True


def _clean_surface(value: str) -> str:
    cleaned = value.strip()
    markdown_link = re.fullmatch(r"\[([^\]]+)\]\([^)]+\)", cleaned)
    if markdown_link:
        cleaned = markdown_link.group(1)
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" \t\r\n-\"'`“”‘’")


def _has_disallowed_punctuation(value: str) -> bool:
    for char in value:
        if char.isalnum() or char.isspace() or char in ALLOWED_PUNCTUATION:
            continue
        return True
    if re.search(r"[.!?。！？,;:]", value):
        return True
    return False


def _looks_like_sentence(value: str) -> bool:
    if not _has_hangul(value):
        return False
    words = value.split()
    if value.endswith(SENTENCE_ENDINGS) or value.endswith(TRUNCATED_PREDICATE_ENDINGS):
        return True
    if len(words) >= 5 and PARTICLE_PATTERN.search(value):
        return True
    if re.search(r"(?:은|는|이|가|을|를)\s+.+(?:설명하|나타내|넣는|된다|아니다|아닙니다)$", value):
        return True
    return False


def _has_hangul(value: str) -> bool:
    return any("가" <= char <= "힣" for char in value)
