import unittest

from wiki_tool.agent_provider import (
    DEFAULT_CODEX_COMMAND,
    PROVIDER_CODEX,
    PROVIDER_RULE_BASED,
    load_agent_provider_config,
    resolve_agent_model,
    resolve_agent_provider,
    resolve_codex_command,
)


class AgentProviderConfigTests(unittest.TestCase):
    def test_missing_environment_uses_rule_based_fallback(self):
        env = {}

        config = load_agent_provider_config("answer", env)

        self.assertEqual(config.provider, PROVIDER_RULE_BASED)
        self.assertFalse(config.uses_codex)
        self.assertEqual(config.model, "")
        self.assertEqual(config.codex_command, DEFAULT_CODEX_COMMAND)

    def test_codex_provider_is_enabled_from_environment(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "codex"}

        self.assertEqual(resolve_agent_provider(env), PROVIDER_CODEX)

    def test_unknown_provider_falls_back_to_rule_based(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "unknown"}

        self.assertEqual(resolve_agent_provider(env), PROVIDER_RULE_BASED)

    def test_role_model_override_wins_over_global_model(self):
        env = {
            "LLM_WIKI_AGENT_MODEL": "global-model",
            "LLM_WIKI_ANSWER_MODEL": "answer-model",
        }

        self.assertEqual(resolve_agent_model("answer", env), "answer-model")
        self.assertEqual(resolve_agent_model("concept", env), "global-model")

    def test_codex_command_uses_environment_or_default(self):
        self.assertEqual(resolve_codex_command({}), DEFAULT_CODEX_COMMAND)
        self.assertEqual(resolve_codex_command({"LLM_WIKI_CODEX_COMMAND": "codex"}), "codex")


if __name__ == "__main__":
    unittest.main()
