import unittest

from wiki_tool.agent_hooks import (
    draft_concept_update_with_agent,
    draft_source_summary_with_agent,
    review_wiki_changes_with_agent,
)
from wiki_tool.codex_agent import CodexAgentResult


class FakeBridge:
    def __init__(self, config):
        self.config = config
        self.calls = []

    def run_ingest(self, payload):
        self.calls.append(("ingest", payload))
        return CodexAgentResult(
            ok=True,
            status="ok",
            answer="source page draft",
            used_pages=[],
            related_pages=[],
            evidence=[],
        )

    def run_concept(self, payload):
        self.calls.append(("concept", payload))
        return CodexAgentResult(
            ok=True,
            status="ok",
            answer="concept merge draft",
            used_pages=[],
            related_pages=[],
            evidence=[],
        )

    def run_review(self, payload):
        self.calls.append(("review", payload))
        return CodexAgentResult(
            ok=False,
            status="codex_error",
            answer="",
            used_pages=[],
            related_pages=[],
            evidence=[],
            error="invalid model",
        )


class AgentHookTests(unittest.TestCase):
    def test_ingest_hook_uses_rule_based_fallback_without_codex_provider(self):
        result = draft_source_summary_with_agent("raw text", env={})

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "rule_based_fallback")

    def test_ingest_and_concept_hooks_call_codex_when_provider_enabled(self):
        created = []

        def factory(config):
            bridge = FakeBridge(config)
            created.append(bridge)
            return bridge

        env = {"LLM_WIKI_AGENT_PROVIDER": "codex", "LLM_WIKI_AGENT_MODEL": "model"}

        ingest = draft_source_summary_with_agent("raw text", env=env, bridge_factory=factory)
        concept = draft_concept_update_with_agent("# Source", env=env, bridge_factory=factory)

        self.assertEqual(ingest.provider, "codex")
        self.assertEqual(ingest.draft, "source page draft")
        self.assertEqual(concept.provider, "codex")
        self.assertEqual(concept.draft, "concept merge draft")
        self.assertEqual(created[0].calls, [("ingest", "raw text")])
        self.assertEqual(created[1].calls, [("concept", "# Source")])

    def test_review_hook_falls_back_when_codex_fails(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "codex"}

        result = review_wiki_changes_with_agent("changes", env=env, bridge_factory=FakeBridge)

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "codex_error")
        self.assertIn("invalid model", result.error)


if __name__ == "__main__":
    unittest.main()
