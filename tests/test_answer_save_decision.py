import unittest

from wiki_tool.answer_save_decision import decide_answer_save, suggested_answer_title


class AnswerSaveDecisionTests(unittest.TestCase):
    def test_ok_answer_with_evidence_is_save_eligible(self):
        payload = {
            "status": "ok",
            "fallback": False,
            "answer": "CAPM은 기대수익률과 위험의 관계를 설명합니다.",
            "used_pages": [],
            "related_pages": [{"path": "wiki/concepts/beta.md"}],
            "evidence": [{"path": "wiki/concepts/capm.md", "text": "CAPM 근거"}],
        }

        decision = decide_answer_save("CAPM은 무엇인가?", payload)

        self.assertEqual(decision.save_action, "save")
        self.assertTrue(decision.save_eligible)
        self.assertIn("근거 문서", decision.save_reason)
        self.assertEqual(decision.suggested_title, "CAPM은 무엇인가")
        self.assertEqual(decision.suggested_page_type, "answer")
        self.assertEqual(decision.decision_made_by, "agent_policy")
        self.assertEqual(decision.evidence, payload["evidence"])

    def test_ok_answer_with_used_pages_is_save_eligible(self):
        payload = {
            "status": "ok",
            "fallback": False,
            "answer": "요약 답변",
            "used_pages": [{"path": "wiki/concepts/capm.md"}],
            "related_pages": [],
            "evidence": [],
        }

        decision = decide_answer_save("CAPM?", payload)

        self.assertEqual(decision.save_action, "save")
        self.assertTrue(decision.save_eligible)

    def test_no_evidence_answer_is_skipped(self):
        decision = decide_answer_save(
            "없는 개념은?",
            {"status": "no_evidence", "fallback": False, "answer": "근거가 부족합니다.", "used_pages": [], "evidence": []},
        )

        self.assertEqual(decision.save_action, "skip")
        self.assertFalse(decision.save_eligible)
        self.assertIn("근거가 부족", decision.save_reason)

    def test_fallback_answer_is_skipped(self):
        decision = decide_answer_save(
            "CAPM?",
            {
                "status": "ok",
                "fallback": True,
                "answer": "fallback 답변",
                "used_pages": [{"path": "wiki/concepts/capm.md"}],
                "evidence": [],
            },
        )

        self.assertEqual(decision.save_action, "skip")
        self.assertFalse(decision.save_eligible)
        self.assertIn("fallback", decision.save_reason)

    def test_empty_answer_is_skipped(self):
        decision = decide_answer_save(
            "CAPM?",
            {"status": "ok", "fallback": False, "answer": " ", "used_pages": [{"path": "wiki/concepts/capm.md"}]},
        )

        self.assertEqual(decision.save_action, "skip")
        self.assertFalse(decision.save_eligible)
        self.assertIn("비어", decision.save_reason)

    def test_missing_evidence_and_used_pages_is_skipped(self):
        decision = decide_answer_save(
            "CAPM?",
            {"status": "ok", "fallback": False, "answer": "답변", "used_pages": [], "evidence": []},
        )

        self.assertEqual(decision.save_action, "skip")
        self.assertFalse(decision.save_eligible)
        self.assertIn("근거 문서", decision.save_reason)

    def test_suggested_title_is_short_safe_question_title(self):
        self.assertEqual(suggested_answer_title("CAPM은 무엇인가?"), "CAPM은 무엇인가")
        self.assertEqual(suggested_answer_title("   요구사항 분석은 어떻게 해요?\n"), "요구사항 분석은 어떻게 해요")
        long_title = suggested_answer_title("이 질문은 너무 길어서 위키 제목으로 그대로 쓰기에는 적절하지 않은 매우 긴 질문입니다")
        self.assertLessEqual(len(long_title), 40)
        self.assertTrue(long_title.endswith("..."))

    def test_decision_can_be_serialized_to_payload_dict(self):
        decision = decide_answer_save(
            "CAPM?",
            {
                "status": "ok",
                "fallback": False,
                "answer": "답변 본문입니다.",
                "used_pages": [{"path": "wiki/concepts/capm.md"}],
                "related_pages": [],
                "evidence": [],
            },
        )

        payload = decision.as_dict()

        self.assertEqual(payload["decision_made_by"], "agent_policy")
        self.assertEqual(payload["question"], "CAPM?")
        self.assertIn("답변 본문", payload["answer_preview"])
        self.assertEqual(payload["used_pages"], [{"path": "wiki/concepts/capm.md"}])


if __name__ == "__main__":
    unittest.main()
