import unittest

from wiki_tool.concept_filter import filter_candidate_concepts, is_valid_candidate_concept


class ConceptFilterTests(unittest.TestCase):
    def test_domain_independent_concept_phrases_are_kept(self):
        candidates = [
            "CAPM",
            "베타",
            "시장 포트폴리오",
            "JWT",
            "Spring Security",
            "요구사항 분석",
            "분산 투자",
            "시장 변동에 대한 민감도",
        ]

        self.assertEqual(filter_candidate_concepts(candidates), candidates)

    def test_sentence_fragments_are_rejected(self):
        rejected = [
            "CAPM은 기대수익률과 체계적 위험의 관계를 설명하",
            "이 문서는 투자 조언이 아닙니다",
            "사용자는 raw 폴더에 자료를 넣는다",
            "베타는 시장 변동에 대한 민감도를 나타낸다",
            "raw source는 concept page가 되면 안 된다",
        ]

        for candidate in rejected:
            with self.subTest(candidate=candidate):
                self.assertFalse(is_valid_candidate_concept(candidate))

    def test_punctuation_and_overlong_explanatory_candidates_are_rejected(self):
        candidates = [
            "CAPM.",
            "Spring Security: 인증 필터",
            "raw source는 concept page가 되면 안 된다.",
            "사용자가 raw 폴더에 자료를 넣으면 agent가 변경점을 감지하고 source summary page를 만든다",
            "JWT",
        ]

        self.assertEqual(filter_candidate_concepts(candidates), ["JWT"])

    def test_candidates_are_cleaned_and_deduplicated(self):
        candidates = [
            "- CAPM",
            "CAPM ",
            "`JWT`",
            "[Spring Security](spring-security.md)",
        ]

        self.assertEqual(filter_candidate_concepts(candidates), ["CAPM", "JWT", "Spring Security"])


if __name__ == "__main__":
    unittest.main()
