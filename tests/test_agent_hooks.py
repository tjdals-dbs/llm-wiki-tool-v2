import unittest

from wiki_tool.agent_hooks import (
    draft_concept_update_with_agent,
    draft_source_summary_with_agent,
    review_wiki_changes_with_agent,
)
from wiki_tool.codex_agent import CodexAgentResult
from wiki_tool.gemini_agent import GeminiAgentResult


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


class FakeGeminiBridge:
    def __init__(self, config):
        self.config = config
        self.calls = []

    def run_ingest(self, payload):
        self.calls.append(("ingest", payload))
        return GeminiAgentResult(
            ok=True,
            status="ok",
            answer="# Gemini Source\n\n## Summary\n\nGemini summary\n\n## Key Points\n\n- Point\n\n## Evidence\n\n- Evidence\n\n## Candidate Concepts\n\n- Gemini",
            used_pages=[],
            related_pages=[],
            evidence=[],
        )

    def run_concept(self, payload):
        self.calls.append(("concept", payload))
        return GeminiAgentResult(
            ok=True,
            status="ok",
            answer="# Gemini Concept\n\n## Definition\n\nGemini concept draft\n\n## Source Evidence\n\n- [source](../sources/source.md)",
            used_pages=[],
            related_pages=[],
            evidence=[],
        )

    def run_review(self, payload):
        self.calls.append(("review", payload))
        return GeminiAgentResult(
            ok=True,
            status="ok",
            answer="- Gemini review ok",
            used_pages=[],
            related_pages=[],
            evidence=[],
        )


class FailingGeminiBridge(FakeGeminiBridge):
    def run_ingest(self, payload):
        self.calls.append(("ingest", payload))
        return GeminiAgentResult(
            ok=False,
            status="gemini_timeout",
            answer="",
            used_pages=[],
            related_pages=[],
            evidence=[],
            error="Gemini timeout",
        )

    def run_concept(self, payload):
        self.calls.append(("concept", payload))
        return GeminiAgentResult(
            ok=False,
            status="gemini_timeout",
            answer="",
            used_pages=[],
            related_pages=[],
            evidence=[],
            error="Gemini timeout",
        )

    def run_review(self, payload):
        self.calls.append(("review", payload))
        return GeminiAgentResult(
            ok=False,
            status="gemini_timeout",
            answer="",
            used_pages=[],
            related_pages=[],
            evidence=[],
            error="Gemini timeout",
        )


class AgentHookTests(unittest.TestCase):
    def test_ingest_hook_uses_rule_based_fallback_without_codex_provider(self):
        result = draft_source_summary_with_agent("raw text", env={})

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "rule_based_fallback")

    def test_gemini_ingest_hook_calls_gemini_bridge(self):
        created = []

        def factory(config):
            bridge = FakeGeminiBridge(config)
            created.append(bridge)
            return bridge

        env = {"LLM_WIKI_INGEST_PROVIDER": "gemini", "LLM_WIKI_INGEST_MODEL": "gemini-ingest"}

        result = draft_source_summary_with_agent("raw text", env=env, gemini_bridge_factory=factory)

        self.assertEqual(result.provider, "gemini")
        self.assertFalse(result.fallback)
        self.assertEqual(result.status, "ok")
        self.assertIn("Gemini Source", result.draft)
        self.assertEqual(created[0].config.model, "gemini-ingest")
        self.assertEqual(created[0].calls, [("ingest", "raw text")])

    def test_gemini_ingest_hook_falls_back_when_bridge_fails(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "gemini"}

        result = draft_source_summary_with_agent("raw text", env=env, gemini_bridge_factory=FailingGeminiBridge)

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "gemini_timeout")
        self.assertIn("Gemini timeout", result.error)

    def test_gemini_concept_hook_calls_gemini_bridge(self):
        created = []

        def factory(config):
            bridge = FakeGeminiBridge(config)
            created.append(bridge)
            return bridge

        env = {"LLM_WIKI_CONCEPT_PROVIDER": "gemini", "LLM_WIKI_CONCEPT_MODEL": "gemini-concept"}
        result = draft_concept_update_with_agent("# Source", env=env, gemini_bridge_factory=factory)

        self.assertEqual(result.provider, "gemini")
        self.assertFalse(result.fallback)
        self.assertEqual(result.status, "ok")
        self.assertIn("Gemini Concept", result.draft)
        self.assertEqual(created[0].config.model, "gemini-concept")
        self.assertEqual(created[0].calls, [("concept", "# Source")])

    def test_gemini_concept_hook_falls_back_when_bridge_fails(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "gemini"}

        result = draft_concept_update_with_agent("# Source", env=env, gemini_bridge_factory=FailingGeminiBridge)

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "gemini_timeout")
        self.assertIn("Gemini timeout", result.error)

    def test_review_hook_calls_gemini_when_review_provider_is_gemini(self):
        created = []

        def factory(config):
            bridge = FakeGeminiBridge(config)
            created.append(bridge)
            return bridge

        env = {"LLM_WIKI_REVIEW_PROVIDER": "gemini", "LLM_WIKI_REVIEW_MODEL": "gemini-review"}

        result = review_wiki_changes_with_agent("changes", env=env, gemini_bridge_factory=factory)

        self.assertEqual(result.provider, "gemini")
        self.assertFalse(result.fallback)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.draft, "- Gemini review ok")
        self.assertEqual(created[0].config.model, "gemini-review")
        self.assertEqual(created[0].calls, [("review", "changes")])

    def test_review_hook_falls_back_when_gemini_fails(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "gemini"}

        result = review_wiki_changes_with_agent("changes", env=env, gemini_bridge_factory=FailingGeminiBridge)

        self.assertEqual(result.provider, "rule_based")
        self.assertTrue(result.fallback)
        self.assertEqual(result.status, "gemini_timeout")
        self.assertIn("Gemini timeout", result.error)

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
