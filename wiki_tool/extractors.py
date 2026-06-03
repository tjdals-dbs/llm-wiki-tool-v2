from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


HTML_SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "header", "form", "button", "select", "option", "noscript"}
HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HTML_NOISE_ATTR_RE = re.compile(r"(nav|menu|footer|header|sidebar|breadcrumb|cookie|share|social|advert|banner|promo|subscribe)", re.I)


@dataclass(frozen=True)
class ExtractedSource:
    title: str
    text: str
    visual_notes: list[str]
    warnings: list[str]
    recommended_actions: list[str]


def extract_source(path: Path, source_type: str) -> ExtractedSource:
    if source_type == "markdown":
        return _extract_markdown(path)
    if source_type == "html":
        return _extract_html(path)
    if source_type == "pdf":
        return _extract_pdf_text_fallback(path)
    if source_type == "image":
        return ExtractedSource(
            title=path.stem,
            text="",
            visual_notes=["이미지 분석 adapter가 없어 내용을 충분히 해석하지 못했습니다."],
            warnings=["이미지 분석이 필요합니다."],
            recommended_actions=["enable_image_vision", "manual_review"],
        )
    return _extract_text(path)


def _extract_markdown(path: Path) -> ExtractedSource:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = _first_markdown_heading(text) or path.stem
    return ExtractedSource(title=title, text=text, visual_notes=[], warnings=[], recommended_actions=[])


def _extract_text(path: Path) -> ExtractedSource:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ExtractedSource(title=path.stem, text=text, visual_notes=[], warnings=[], recommended_actions=[])


def _extract_html(path: Path) -> ExtractedSource:
    parser = _ReadableHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(_clean_extracted_lines(parser.parts))
    title = parser.title or path.stem
    return ExtractedSource(title=title, text=text, visual_notes=[], warnings=[], recommended_actions=[])


def _extract_pdf_text_fallback(path: Path) -> ExtractedSource:
    page_texts = _extract_pdf_pages(path)
    if page_texts:
        text = "\n".join(page_texts)
        visual_notes = [f"PDF page {index}: {page_text[:160]}" for index, page_text in enumerate(page_texts, start=1)]
        return ExtractedSource(
            title=path.stem,
            text=text,
            visual_notes=visual_notes,
            warnings=[],
            recommended_actions=[],
        )

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"[^\w\s가-힣.,;:!?()\[\]{}%+-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    warnings: list[str] = []
    actions: list[str] = []
    if len(text) < 80:
        warnings.append("PDF 텍스트 추출 결과가 충분하지 않습니다.")
        actions.append("enable_pdf_vision")
        actions.append("manual_review")
    return ExtractedSource(
        title=path.stem,
        text=text,
        visual_notes=["PDF page boundary는 fallback 추출에서 보존되지 않았습니다."],
        warnings=warnings,
        recommended_actions=actions,
    )


def _extract_pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []

    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                cleaned = " ".join(_clean_extracted_lines(text.splitlines()))
                if cleaned:
                    pages.append(cleaned)
        return pages
    except Exception:
        return []


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._skip_tag_stack: list[str] = []
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        should_skip = tag in HTML_SKIP_TAGS or _has_noise_attr(attrs)
        if should_skip and tag not in HTML_VOID_TAGS:
            self._skip_depth += 1
            self._skip_tag_stack.append(tag)
        if tag == "title":
            self._capture_title = True
        if tag == "img" and not self._skip_depth:
            attrs_map = dict(attrs)
            alt = (attrs_map.get("alt") or "").strip()
            if alt:
                self.parts.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag_stack and self._skip_tag_stack[-1] == tag and self._skip_depth:
            self._skip_tag_stack.pop()
            self._skip_depth -= 1
        if tag == "title":
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._capture_title:
            self.title = text
        else:
            self.parts.append(text)


def _has_noise_attr(attrs: list[tuple[str, str | None]]) -> bool:
    attrs_map = {name.casefold(): (value or "") for name, value in attrs}
    role = attrs_map.get("role", "").casefold()
    if role in {"navigation", "banner", "contentinfo", "complementary"}:
        return True
    joined = " ".join(attrs_map.get(key, "") for key in ("id", "class", "aria-label"))
    return bool(HTML_NOISE_ATTR_RE.search(joined))


def _clean_extracted_lines(parts: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for part in parts:
        line = re.sub(r"\s+", " ", part).strip()
        if not line or _is_extraction_noise_line(line):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def _is_extraction_noise_line(line: str) -> bool:
    lowered = line.casefold()
    if len(line) <= 2:
        return True
    if re.fullmatch(r"(home|menu|login|logout|search|share|subscribe|previous|next|top|메뉴|홈|로그인|검색|공유|이전|다음)", lowered):
        return True
    if re.search(r"(copyright|all rights reserved|개인정보처리방침|이용약관|쿠키|cookie)", lowered):
        return True
    if re.fullmatch(r"[\W_0-9]+", line):
        return True
    return False
