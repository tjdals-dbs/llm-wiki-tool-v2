from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


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
    text = "\n".join(part.strip() for part in parser.parts if part.strip())
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
                pages.append(re.sub(r"\s+", " ", text))
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
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "aside"}:
            self._skip_depth += 1
        if tag == "title":
            self._capture_title = True
        if tag == "img" and not self._skip_depth:
            attrs_map = dict(attrs)
            alt = (attrs_map.get("alt") or "").strip()
            if alt:
                self.parts.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "aside"} and self._skip_depth:
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
