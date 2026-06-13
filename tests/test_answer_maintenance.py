import tempfile
import unittest
from pathlib import Path

from wiki_tool.answer_maintenance import analyze_answer_candidates, draft_answer_concept_updates
from wiki_tool.config import load_domain_config
from wiki_tool.mcp_tools import WikiToolAdapter


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


class AnswerMaintenanceTests(unittest.TestCase):
    def test_ok_answer_with_evidence_becomes_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            (root / "wiki" / "concepts").mkdir(parents=True)
            concept = root / "wiki" / "concepts" / "capm.md"
            concept.write_text("# CAPM\n\n## Definition\n\nConcept body.\n", encoding="utf-8")
            adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM is a risk-return model.",
                used_pages=[{"path": "wiki/concepts/capm.md", "title": "CAPM"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "Evidence text"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            result = analyze_answer_candidates(domain)

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["skipped_count"], 0)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["action"], "candidate")
            self.assertEqual(candidate["candidate_title"], "CAPM은 무엇인가")
            self.assertEqual(candidate["question"], "CAPM은 무엇인가?")
            self.assertEqual(candidate["evidence_count"], 1)
            self.assertEqual(candidate["used_pages"], ["wiki/concepts/capm.md"])
            self.assertEqual(candidate["existing_concept_matches"], ["wiki/concepts/capm.md"])
            self.assertIn("risk-return", candidate["answer_preview"])

    def test_no_evidence_answer_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            adapter.apply_wiki_update(
                question="알 수 없는 개념은?",
                answer="근거가 없습니다.",
                used_pages=[],
                related_pages=[],
                evidence=[],
                status="no_evidence",
                suggested_title="알 수 없는 개념은",
            )

            result = analyze_answer_candidates(domain)

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            skipped = result["skipped"][0]
            self.assertEqual(skipped["action"], "skip")
            self.assertIn("no_evidence", skipped["candidate_reason"])

    def test_answer_without_evidence_or_used_pages_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            adapter.apply_wiki_update(
                question="저장 후보인가?",
                answer="본문은 있지만 근거는 없습니다.",
                used_pages=[],
                related_pages=[],
                evidence=[],
                status="ok",
                suggested_title="저장 후보인가",
            )

            result = analyze_answer_candidates(domain)

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            self.assertIn("근거", result["skipped"][0]["candidate_reason"])

    def test_malformed_answer_page_is_skipped_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            answer_dir = root / "wiki" / "answers"
            answer_dir.mkdir(parents=True)
            (answer_dir / "broken.md").write_text("# Broken\n\nNo answer section.", encoding="utf-8")

            result = analyze_answer_candidates(domain)

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            self.assertEqual(result["skipped"][0]["answer_path"], "wiki/answers/broken.md")
            self.assertIn("malformed", result["skipped"][0]["candidate_reason"])

    def test_analysis_does_not_modify_concept_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            concept = root / "wiki" / "concepts" / "capm.md"
            concept.parent.mkdir(parents=True)
            concept.write_text("# CAPM\n\nHuman edited concept body.\n", encoding="utf-8")
            before = concept.read_text(encoding="utf-8")
            adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM is a model.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "Evidence"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )
            concept.write_text(before, encoding="utf-8")

            analyze_answer_candidates(domain)

            self.assertEqual(concept.read_text(encoding="utf-8"), before)

    def test_existing_concept_match_creates_update_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            concept = root / "wiki" / "concepts" / "capm.md"
            concept.parent.mkdir(parents=True)
            concept.write_text("# CAPM\n\nHuman edited concept body.\n", encoding="utf-8")
            adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM explains expected return with systematic risk.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "CAPM evidence"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )

            result = draft_answer_concept_updates(domain)

            self.assertEqual(result["draft_count"], 1)
            draft = result["drafts"][0]
            self.assertEqual(draft["draft_action"], "update_existing_concept")
            self.assertEqual(draft["target_concept_path"], "wiki/concepts/capm.md")
            self.assertEqual(draft["candidate_title"], "CAPM은 무엇인가")
            self.assertIn("expected return", draft["draft_summary"])
            self.assertEqual(draft["evidence"][0]["text"], "CAPM evidence")
            self.assertEqual(draft["used_pages"], ["wiki/concepts/capm.md"])

    def test_answer_without_existing_concept_creates_new_concept_candidate_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            adapter.apply_wiki_update(
                question="요구사항 분석은 무엇인가?",
                answer="요구사항 분석은 사용자의 필요를 구조화하는 활동입니다.",
                used_pages=[{"path": "wiki/sources/requirements.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/sources/requirements.md", "text": "요구사항 분석 evidence"}],
                status="ok",
                suggested_title="요구사항 분석",
            )

            result = draft_answer_concept_updates(domain)

            self.assertEqual(result["draft_count"], 1)
            draft = result["drafts"][0]
            self.assertEqual(draft["draft_action"], "new_concept_candidate")
            self.assertEqual(draft["target_concept_path"], "")
            self.assertEqual(draft["candidate_title"], "요구사항 분석")

    def test_answer_candidate_without_source_evidence_is_skipped_for_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            adapter.apply_wiki_update(
                question="근거 없는 후보인가?",
                answer="used page만 있는 답변입니다.",
                used_pages=[{"path": "wiki/concepts/foo.md"}],
                related_pages=[],
                evidence=[],
                status="ok",
                suggested_title="근거 없는 후보",
            )

            candidates = analyze_answer_candidates(domain)
            result = draft_answer_concept_updates(domain)

            self.assertEqual(candidates["candidate_count"], 1)
            self.assertEqual(result["draft_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            self.assertEqual(result["skipped"][0]["draft_action"], "skip")
            self.assertIn("evidence", result["skipped"][0]["reason"])

    def test_skipped_or_malformed_answer_pages_are_not_drafted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            answer_dir = root / "wiki" / "answers"
            answer_dir.mkdir(parents=True)
            (answer_dir / "broken.md").write_text("# Broken\n\nNo answer section.", encoding="utf-8")

            result = draft_answer_concept_updates(domain)

            self.assertEqual(result["draft_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            self.assertEqual(result["skipped"][0]["answer_path"], "wiki/answers/broken.md")

    def test_draft_generation_does_not_modify_concept_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            adapter = WikiToolAdapter(domain)
            concept = root / "wiki" / "concepts" / "capm.md"
            concept.parent.mkdir(parents=True)
            concept.write_text("# CAPM\n\nHuman edited concept body.\n", encoding="utf-8")
            before = concept.read_text(encoding="utf-8")
            adapter.apply_wiki_update(
                question="CAPM은 무엇인가?",
                answer="CAPM is a model.",
                used_pages=[{"path": "wiki/concepts/capm.md"}],
                related_pages=[],
                evidence=[{"path": "wiki/concepts/capm.md", "text": "Evidence"}],
                status="ok",
                suggested_title="CAPM은 무엇인가",
            )
            concept.write_text(before, encoding="utf-8")

            draft_answer_concept_updates(domain)

            self.assertEqual(concept.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
