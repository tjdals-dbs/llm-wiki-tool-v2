import csv
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from wiki_tool.agent_hooks import AgentHookResult
from wiki_tool.config import load_domain_config
from wiki_tool.scanner import scan_raw_sources
from wiki_tool.summarizer import summarize_new_sources


def write_domain(root: Path) -> Path:
    domain_file = root / "domain.yml"
    domain_file.write_text(
        "\n".join(
            [
                "name: Test Domain",
                "slug: test",
                "description: Test wiki.",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                "language: ko",
            ]
        ),
        encoding="utf-8",
    )
    return domain_file


def section_bullets(content: str, heading: str) -> list[str]:
    marker = f"## {heading}"
    lines = content.splitlines()
    in_section = False
    bullets: list[str] = []
    for line in lines:
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


class SourceSummarizerTests(unittest.TestCase):
    def test_markdown_source_becomes_korean_source_summary_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# CAPM\nCAPM은 기대수익률과 체계적 위험을 연결한다. 베타는 시장 위험에 대한 민감도다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            self.assertEqual(result.provider, "rule_based")
            self.assertEqual(result.codex_used_count, 0)
            self.assertEqual(result.fallback_count, 0)
            source_page = root / "wiki" / "sources" / "capm.md"
            content = source_page.read_text(encoding="utf-8")
            self.assertIn("## Source Metadata", content)
            self.assertIn("- Raw path: capm.md", content)
            self.assertIn("## Summary", content)
            self.assertIn("## Key Points", content)
            self.assertIn("## Evidence", content)
            self.assertIn("## Candidate Concepts", content)
            self.assertIn("CAPM", content)
            self.assertIn("quality: usable", content)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "summarized")
            self.assertEqual(rows[0]["source_page"], "wiki/sources/capm.md")

    def test_codex_ingest_draft_is_used_when_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)
            codex_draft = "\n".join(
                [
                    "# Codex CAPM Source",
                    "",
                    "## Summary",
                    "",
                    "Codex가 정리한 요약입니다.",
                    "",
                    "## Key Points",
                    "",
                    "- CAPM은 위험과 수익을 연결한다.",
                    "",
                    "## Evidence",
                    "",
                    "- CAPM은 기대수익률과 위험을 연결한다.",
                    "",
                    "## Candidate Concepts",
                    "",
                    "- CAPM",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=codex_draft,
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "capm.md").read_text(encoding="utf-8")
            self.assertEqual(result.provider, "codex")
            self.assertEqual(result.codex_used_count, 1)
            self.assertEqual(result.fallback_count, 0)
            self.assertIn("Codex가 정리한 요약입니다.", content)
            self.assertIn("## Agent Metadata", content)
            self.assertIn("- provider: codex", content)
            self.assertIn("- fallback: false", content)
            hook.assert_called_once()

    def test_gemini_ingest_draft_is_used_when_valid_and_raw_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "gemini.md"
            raw_file.parent.mkdir()
            raw_text = "# Gemini\nGemini source text with JWT and Spring Security."
            raw_file.write_text(raw_text, encoding="utf-8")
            scan_raw_sources(domain)
            gemini_draft = "\n".join(
                [
                    "# Gemini Source",
                    "",
                    "## Summary",
                    "",
                    "Gemini source summary.",
                    "",
                    "## Key Points",
                    "",
                    "- JWT is a token format.",
                    "- Spring Security is a security framework.",
                    "",
                    "## Evidence",
                    "",
                    "- Gemini source text with JWT and Spring Security.",
                    "",
                    "## Candidate Concepts",
                    "",
                    "- JWT",
                    "- Spring Security",
                    "",
                    "## Candidate Concept Evidence",
                    "",
                    "- JWT: Gemini source text with JWT and Spring Security.",
                    "- Spring Security: Gemini source text with JWT and Spring Security.",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_INGEST_PROVIDER": "gemini"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="gemini",
                    fallback=False,
                    status="ok",
                    draft=gemini_draft,
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "gemini.md").read_text(encoding="utf-8")
            self.assertEqual(result.provider, "gemini")
            self.assertEqual(result.codex_used_count, 0)
            self.assertEqual(result.gemini_used_count, 1)
            self.assertEqual(result.fallback_count, 0)
            self.assertIn("Gemini source summary.", content)
            self.assertIn("- provider: gemini", content)
            self.assertIn("- fallback: false", content)
            self.assertEqual(raw_file.read_text(encoding="utf-8"), raw_text)

    def test_codex_ingest_candidate_concepts_are_filtered_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "mixed.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "# Mixed\nCAPM과 JWT를 함께 설명하는 공개 테스트 메모입니다.",
                encoding="utf-8",
            )
            scan_raw_sources(domain)
            codex_draft = "\n".join(
                [
                    "# Mixed Source",
                    "",
                    "## Summary",
                    "",
                    "CAPM과 JWT를 함께 설명하는 요약입니다.",
                    "",
                    "## Key Points",
                    "",
                    "- CAPM은 기대수익률과 체계적 위험의 관계를 설명한다.",
                    "- JWT는 인증 토큰 형식이다.",
                    "",
                    "## Evidence",
                    "",
                    "- CAPM은 기대수익률과 체계적 위험의 관계를 설명한다.",
                    "- JWT는 인증 토큰 형식이다.",
                    "",
                    "## Candidate Concepts",
                    "",
                    "- CAPM",
                    "- JWT",
                    "- CAPM은 기대수익률과 체계적 위험의 관계를 설명하",
                    "- 이 문서는 투자 조언이 아닙니다",
                    "- raw source는 concept page가 되면 안 된다",
                    "",
                    "## Candidate Concept Evidence",
                    "",
                    "- CAPM: CAPM은 기대수익률과 체계적 위험의 관계를 설명한다.",
                    "- JWT: JWT는 인증 토큰 형식이다.",
                    "- CAPM은 기대수익률과 체계적 위험의 관계를 설명하: 문장 조각 근거",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft=codex_draft,
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "mixed.md").read_text(encoding="utf-8")
            candidates = section_bullets(content, "Candidate Concepts")
            concept_evidence = section_bullets(content, "Candidate Concept Evidence")
            self.assertEqual(result.codex_used_count, 1)
            self.assertEqual(candidates, ["CAPM", "JWT"])
            self.assertNotIn("CAPM은 기대수익률과 체계적 위험의 관계를 설명하", "\n".join(candidates))
            self.assertNotIn("이 문서는 투자 조언이 아닙니다", "\n".join(candidates))
            self.assertNotIn("raw source는 concept page가 되면 안 된다", "\n".join(candidates))
            self.assertTrue(all(not item.startswith("CAPM은 기대수익률") for item in concept_evidence))

    def test_gemini_ingest_candidate_concepts_are_filtered_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "security.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# Security\nJWT and Spring Security are described here.", encoding="utf-8")
            scan_raw_sources(domain)
            gemini_draft = "\n".join(
                [
                    "# Gemini Security Source",
                    "",
                    "## Summary",
                    "",
                    "JWT and Spring Security are described here.",
                    "",
                    "## Key Points",
                    "",
                    "- JWT is a token format.",
                    "",
                    "## Evidence",
                    "",
                    "- JWT and Spring Security are described here.",
                    "",
                    "## Candidate Concepts",
                    "",
                    "- JWT",
                    "- Spring Security",
                    "- Users put files in the raw folder.",
                    "- JWT is a token format.",
                    "",
                    "## Candidate Concept Evidence",
                    "",
                    "- JWT: JWT and Spring Security are described here.",
                    "- Spring Security: JWT and Spring Security are described here.",
                    "- Users put files in the raw folder.: invalid",
                ]
            )

            with patch.dict("os.environ", {"LLM_WIKI_INGEST_PROVIDER": "gemini"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult("ingest", "gemini", False, "ok", gemini_draft)
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "security.md").read_text(encoding="utf-8")
            self.assertEqual(result.gemini_used_count, 1)
            self.assertEqual(section_bullets(content, "Candidate Concepts"), ["JWT", "Spring Security"])
            self.assertTrue(all("Users put files" not in item for item in section_bullets(content, "Candidate Concept Evidence")))

    def test_codex_ingest_draft_missing_required_sections_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="codex",
                    fallback=False,
                    status="ok",
                    draft="# Broken\n\n## Summary\n\n섹션이 부족합니다.",
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "capm.md").read_text(encoding="utf-8")
            self.assertEqual(result.codex_used_count, 0)
            self.assertEqual(result.fallback_count, 1)
            self.assertIn("CAPM은 기대수익률", content)
            self.assertIn("- fallback: true", content)
            self.assertIn("missing_sections", content)

    def test_gemini_ingest_draft_missing_required_sections_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "gemini.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# Gemini\nGemini source text with JWT.", encoding="utf-8")
            scan_raw_sources(domain)

            with patch.dict("os.environ", {"LLM_WIKI_INGEST_PROVIDER": "gemini"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="gemini",
                    fallback=False,
                    status="ok",
                    draft="# Broken\n\n## Summary\n\nmissing required sections",
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "gemini.md").read_text(encoding="utf-8")
            self.assertEqual(result.gemini_used_count, 0)
            self.assertEqual(result.fallback_count, 1)
            self.assertIn("- provider: gemini", content)
            self.assertIn("- fallback: true", content)
            self.assertIn("missing_sections", content)

    def test_codex_ingest_failure_falls_back_to_rule_based_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "capm.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# CAPM\nCAPM은 기대수익률과 위험을 연결한다.", encoding="utf-8")
            scan_raw_sources(domain)

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "codex"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="rule_based",
                    fallback=True,
                    status="codex_timeout",
                    draft="",
                    error="timeout",
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "capm.md").read_text(encoding="utf-8")
            self.assertEqual(result.fallback_count, 1)
            self.assertIn("CAPM은 기대수익률", content)
            self.assertIn("codex_timeout", content)
            self.assertIn("timeout", content)

    def test_gemini_ingest_failure_falls_back_to_rule_based_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "gemini.md"
            raw_file.parent.mkdir()
            raw_file.write_text("# Gemini\nGemini source text with JWT.", encoding="utf-8")
            scan_raw_sources(domain)

            with patch.dict("os.environ", {"LLM_WIKI_AGENT_PROVIDER": "gemini"}, clear=True), patch(
                "wiki_tool.summarizer.draft_source_summary_with_agent"
            ) as hook:
                hook.return_value = AgentHookResult(
                    role="ingest",
                    provider="rule_based",
                    fallback=True,
                    status="gemini_empty_output",
                    draft="",
                    error="empty",
                )
                result = summarize_new_sources(domain)

            content = (root / "wiki" / "sources" / "gemini.md").read_text(encoding="utf-8")
            self.assertEqual(result.provider, "gemini")
            self.assertEqual(result.gemini_used_count, 0)
            self.assertEqual(result.fallback_count, 1)
            self.assertIn("gemini_empty_output", content)
            self.assertIn("empty", content)

    def test_weak_pdf_is_left_as_needs_review_with_pdf_vision_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "slides.pdf"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"%PDF-1.7\n%%EOF")
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.needs_review_count, 1)
            source_page = root / "wiki" / "sources" / "slides.md"
            content = source_page.read_text(encoding="utf-8")
            self.assertIn("quality: weak", content)
            self.assertIn("enable_pdf_vision", content)
            self.assertIn("manual_review", content)
            self.assertIn("PDF 텍스트 추출 결과가 충분하지 않습니다.", content)
            self.assertIn("텍스트 레이어", content)
            self.assertIn("수동 요약", content)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "needs_review")

    def test_pdf_summary_preserves_page_boundary_when_text_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "lecture.pdf"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"%PDF-1.7\n%%EOF")
            scan_raw_sources(domain)

            with patch(
                "wiki_tool.extractors._extract_pdf_pages",
                return_value=["1쪽 CAPM 설명은 기대수익률과 위험을 연결한다.", "2쪽 베타는 시장 위험 민감도다."],
            ):
                result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "lecture.md").read_text(encoding="utf-8")
            self.assertIn("PDF page 1", content)
            self.assertIn("PDF page 2", content)

    def test_summary_prefers_substantive_evidence_over_markdown_chrome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "valuation.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "\n".join(
                    [
                        "# Memo",
                        "",
                        "## 잡담",
                        "이 문서는 수업 전에 적은 짧은 안내다.",
                        "",
                        "## DCF",
                        "DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.",
                        "할인율은 현금흐름의 위험과 자본비용을 반영한다.",
                    ]
                ),
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "valuation.md").read_text(encoding="utf-8")
            self.assertIn("## Candidate Concept Evidence", content)
            self.assertIn("DCF: DCF는 미래 현금흐름을 현재가치로 할인해 기업가치를 추정하는 방법이다.", content)
            self.assertIn("할인율은 현금흐름의 위험과 자본비용을 반영한다.", content)
            self.assertNotIn("# Memo", content.split("## Summary", 1)[1].split("## Key Points", 1)[0])

    def test_markdown_frontmatter_stays_out_of_reader_facing_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "frontmatter.md"
            raw_file.parent.mkdir()
            raw_file.write_text(
                "\n".join(
                    [
                        "---",
                        "source_path: private/lecture.pdf",
                        "sha256: should-not-appear-in-summary",
                        "tool_trace: extractor-v1",
                        "---",
                        "# 듀레이션",
                        "sha256: body-metadata-should-not-appear",
                        "메뉴",
                        "듀레이션은 금리 변화에 대한 채권 가격의 민감도를 설명하는 개념이다.",
                        "듀레이션은 금리 변화에 대한 채권 가격의 민감도를 설명하는 개념이다.",
                        "만기가 길고 쿠폰이 낮을수록 듀레이션은 커지는 경향이 있다.",
                    ]
                ),
                encoding="utf-8",
            )
            scan_raw_sources(domain)

            result = summarize_new_sources(domain)

            self.assertEqual(result.summarized_count, 1)
            content = (root / "wiki" / "sources" / "frontmatter.md").read_text(encoding="utf-8")
            reader_body = content.split("## Quality Review", 1)[0]
            self.assertIn("## Summary", reader_body)
            self.assertIn("듀레이션은 금리 변화", reader_body)
            self.assertNotIn("source_path", reader_body)
            self.assertNotIn("tool_trace", reader_body)
            self.assertNotIn("body-metadata-should-not-appear", reader_body)
            self.assertNotIn("메뉴", reader_body)
            self.assertLess(content.index("## Summary"), content.index("## Source Metadata"))


if __name__ == "__main__":
    unittest.main()
