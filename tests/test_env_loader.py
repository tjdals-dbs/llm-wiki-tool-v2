import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class EnvLoaderTests(unittest.TestCase):
    def test_missing_env_file_is_noop(self):
        from wiki_tool.env_loader import load_dotenv_if_present

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            loaded = load_dotenv_if_present(Path(tmp))

        self.assertEqual(loaded, {})

    def test_loads_values_comments_blank_lines_and_quotes_without_overriding_environment(self):
        from wiki_tool.env_loader import load_dotenv_if_present

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"LLM_WIKI_AGENT_PROVIDER": "rule_based"},
            clear=True,
        ):
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "# local agent settings",
                        "",
                        "LLM_WIKI_AGENT_PROVIDER=codex",
                        'LLM_WIKI_AGENT_MODEL="gpt-5.5"',
                        "LLM_WIKI_CODEX_COMMAND='codex.cmd'",
                        "INVALID_LINE_WITHOUT_EQUALS",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = load_dotenv_if_present(root)

            self.assertEqual(os.environ["LLM_WIKI_AGENT_PROVIDER"], "rule_based")
            self.assertEqual(os.environ["LLM_WIKI_AGENT_MODEL"], "gpt-5.5")
            self.assertEqual(os.environ["LLM_WIKI_CODEX_COMMAND"], "codex.cmd")
            self.assertEqual(
                loaded,
                {
                    "LLM_WIKI_AGENT_MODEL": "gpt-5.5",
                    "LLM_WIKI_CODEX_COMMAND": "codex.cmd",
                },
            )

    def test_gitignore_excludes_local_env_files(self):
        gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn(".env", gitignore)
        self.assertIn(".env.local", gitignore)

    def test_env_example_documents_codex_provider_settings(self):
        example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

        self.assertIn("LLM_WIKI_AGENT_PROVIDER=codex", example)
        self.assertIn("LLM_WIKI_ANSWER_MODEL=gpt-5.5", example)
        self.assertIn("LLM_WIKI_CODEX_COMMAND=codex.cmd", example)


if __name__ == "__main__":
    unittest.main()
