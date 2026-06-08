import unittest

from wiki_tool.agent_provider import (
    DEFAULT_CODEX_COMMAND,
    PROVIDER_CLAUDE,
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    PROVIDER_RULE_BASED,
    detect_agent_providers,
    load_agent_provider_config,
    resolve_agent_model,
    resolve_agent_provider,
    resolve_codex_command,
    select_agent_provider,
)


class FakeCliRunner:
    def __init__(self, usable_commands=()):
        self.usable_commands = set(usable_commands)
        self.calls = []

    def __call__(self, command):
        self.calls.append(tuple(command))

        class Result:
            def __init__(self, ok):
                self.returncode = 0 if ok else 1
                self.stdout = "ok" if ok else ""
                self.stderr = "" if ok else "not available"

        return Result(command[0] in self.usable_commands)


class RaisingCliRunner:
    def __call__(self, command):
        raise FileNotFoundError(command[0])


class AgentProviderConfigTests(unittest.TestCase):
    def test_missing_environment_uses_rule_based_fallback(self):
        env = {}

        config = load_agent_provider_config("answer", env)

        self.assertEqual(config.provider, PROVIDER_RULE_BASED)
        self.assertFalse(config.uses_codex)
        self.assertEqual(config.model, "")
        self.assertEqual(config.codex_command, DEFAULT_CODEX_COMMAND)

    def test_role_config_auto_selects_codex_when_usable_without_explicit_provider(self):
        config = load_agent_provider_config("answer", env={}, runner=FakeCliRunner({"codex.cmd"}))

        self.assertEqual(config.provider, PROVIDER_CODEX)
        self.assertTrue(config.uses_codex)
        self.assertEqual(config.selection_reason, "auto_detected")

    def test_role_config_uses_rule_based_when_no_cli_provider_is_usable(self):
        config = load_agent_provider_config("answer", env={}, runner=FakeCliRunner())

        self.assertEqual(config.provider, PROVIDER_RULE_BASED)
        self.assertFalse(config.uses_codex)
        self.assertEqual(config.selection_reason, "fallback")

    def test_role_provider_override_wins_over_global_provider(self):
        env = {
            "LLM_WIKI_AGENT_PROVIDER": "codex",
            "LLM_WIKI_ANSWER_PROVIDER": "rule_based",
        }

        config = load_agent_provider_config("answer", env, runner=FakeCliRunner({"codex.cmd"}))

        self.assertEqual(config.provider, PROVIDER_RULE_BASED)
        self.assertEqual(config.selection_reason, "explicit_env")

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

    def test_explicit_provider_environment_wins_over_auto_detection(self):
        env = {"LLM_WIKI_AGENT_PROVIDER": "claude", "LLM_WIKI_CLAUDE_COMMAND": "claude-custom"}
        runner = FakeCliRunner()

        selected = select_agent_provider(env=env, runner=runner)

        self.assertEqual(selected.provider, PROVIDER_CLAUDE)
        self.assertEqual(selected.command, "claude-custom")
        self.assertEqual(selected.selection_reason, "explicit_env")

    def test_auto_detection_selects_codex_when_usable_without_explicit_provider(self):
        runner = FakeCliRunner({"codex.cmd"})

        selected = select_agent_provider(env={}, runner=runner)

        self.assertEqual(selected.provider, PROVIDER_CODEX)
        self.assertTrue(selected.usable)
        self.assertEqual(selected.selection_reason, "auto_detected")

    def test_auto_detection_falls_through_to_claude_then_gemini(self):
        claude_selected = select_agent_provider(env={}, runner=FakeCliRunner({"claude"}))
        gemini_selected = select_agent_provider(env={}, runner=FakeCliRunner({"gemini"}))

        self.assertEqual(claude_selected.provider, PROVIDER_CLAUDE)
        self.assertEqual(gemini_selected.provider, PROVIDER_GEMINI)

    def test_auto_detection_uses_rule_based_when_all_cli_providers_fail(self):
        selected = select_agent_provider(env={}, runner=FakeCliRunner())

        self.assertEqual(selected.provider, PROVIDER_RULE_BASED)
        self.assertTrue(selected.usable)
        self.assertEqual(selected.selection_reason, "fallback")

    def test_command_environment_overrides_are_used_for_detection(self):
        env = {"LLM_WIKI_CODEX_COMMAND": "codex-local"}
        runner = FakeCliRunner({"codex-local"})

        selected = select_agent_provider(env=env, runner=runner)

        self.assertEqual(selected.provider, PROVIDER_CODEX)
        self.assertEqual(selected.command, "codex-local")

    def test_detection_preserves_failure_reasons(self):
        detections = detect_agent_providers(env={}, runner=FakeCliRunner())
        codex_detection = next(item for item in detections if item.provider == PROVIDER_CODEX)

        self.assertFalse(codex_detection.usable)
        self.assertIn("version command failed", codex_detection.status_message)

    def test_detection_handles_missing_command_without_exception(self):
        selected = select_agent_provider(env={}, runner=RaisingCliRunner())

        self.assertEqual(selected.provider, PROVIDER_RULE_BASED)

    def test_detection_uses_cli_runner_without_reading_credential_files(self):
        runner = FakeCliRunner({"codex.cmd"})

        select_agent_provider(env={}, runner=runner)

        self.assertTrue(runner.calls)
        self.assertTrue(all(call[0] in {"codex.cmd", "claude", "gemini"} for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
