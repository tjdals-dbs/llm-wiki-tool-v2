import unittest

from wiki_tool.maintenance_review import (
    build_review_changes_summary,
    maintenance_change_count,
    run_maintenance_review,
)


class MaintenanceReviewTests(unittest.TestCase):
    def test_codex_provider_with_changes_runs_review_and_builds_summary(self):
        calls = []
        summarize = {"summarized_count": 1, "needs_review_count": 2, "fallback_count": 3}
        organize = {"promoted_count": 4, "merged_count": 5, "fallback_count": 6}
        updates = {"applied_count": 7, "skipped_count": 8}

        def runner(summary):
            calls.append(summary)
            return {
                "role": "review",
                "provider": "codex",
                "fallback": False,
                "status": "ok",
                "draft": "- ok",
                "error": "",
            }

        result = run_maintenance_review(
            summarize,
            organize,
            updates,
            review_runner=runner,
            env={"LLM_WIKI_REVIEW_PROVIDER": "codex"},
        )

        self.assertEqual(result["provider"], "codex")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)
        self.assertIn("codex review provider", calls[0])
        self.assertIn("source summarized: 1", calls[0])
        self.assertIn("source needs review: 2", calls[0])
        self.assertIn("concept promoted: 4", calls[0])
        self.assertIn("concept merged: 5", calls[0])
        self.assertIn("answer concept updates applied: 7", calls[0])
        self.assertIn("answer concept updates skipped: 8", calls[0])

    def test_gemini_provider_with_changes_runs_review(self):
        calls = []

        result = run_maintenance_review(
            {"summarized_count": 1},
            {"promoted_count": 0},
            {"applied_count": 0},
            review_runner=lambda summary: calls.append(summary)
            or {"role": "review", "provider": "gemini", "fallback": False, "status": "ok", "draft": "", "error": ""},
            env={"LLM_WIKI_REVIEW_PROVIDER": "gemini"},
        )

        self.assertEqual(result["provider"], "gemini")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)

    def test_rule_based_provider_skips_review(self):
        calls = []

        result = run_maintenance_review(
            {"summarized_count": 1},
            {"promoted_count": 1},
            {"applied_count": 1},
            review_runner=lambda summary: calls.append(summary),
            env={"LLM_WIKI_REVIEW_PROVIDER": "rule_based"},
        )

        self.assertEqual(result["provider"], "rule_based")
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["fallback"])
        self.assertEqual(calls, [])

    def test_zero_change_count_skips_review(self):
        calls = []

        result = run_maintenance_review(
            {"summarized_count": 0, "needs_review_count": 0},
            {"promoted_count": 0, "merged_count": 0},
            {"applied_count": 0},
            review_runner=lambda summary: calls.append(summary),
            env={"LLM_WIKI_REVIEW_PROVIDER": "gemini"},
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls, [])
        self.assertEqual(maintenance_change_count({"summarized_count": 0}, {"merged_count": 0}, {"applied_count": 0}), 0)

    def test_review_exception_returns_fallback_result(self):
        def broken_runner(_summary):
            raise RuntimeError("review exploded")

        result = run_maintenance_review(
            {"summarized_count": 1},
            {},
            {},
            review_runner=broken_runner,
            env={"LLM_WIKI_REVIEW_PROVIDER": "codex"},
        )

        self.assertEqual(result["provider"], "rule_based")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["status"], "review_exception")
        self.assertIn("review exploded", result["error"])

    def test_summary_builder_is_shared_and_deterministic(self):
        summary = build_review_changes_summary(
            "gemini",
            {"summarized_count": 1, "needs_review_count": 2, "fallback_count": 3},
            {"promoted_count": 4, "merged_count": 5, "fallback_count": 6},
            {"applied_count": 7, "skipped_count": 8},
        )

        self.assertEqual(
            summary.splitlines(),
            [
                "gemini review provider is checking the wiki maintenance changes.",
                "- source summarized: 1",
                "- source needs review: 2",
                "- source fallback: 3",
                "- concept promoted: 4",
                "- concept merged: 5",
                "- concept fallback: 6",
                "- answer concept updates applied: 7",
                "- answer concept updates skipped: 8",
            ],
        )


if __name__ == "__main__":
    unittest.main()
