from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_app.py"


def _load_run_app_module():
    spec = importlib.util.spec_from_file_location("run_app_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_domain(path: Path, *, name: str, slug: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"name: {name}",
                f"slug: {slug}",
                f"description: Local domain for {name}.",
                "raw_dir: raw",
                "wiki_dir: wiki",
                "manifest: manifests/raw_sources.csv",
                "language: ko",
                "",
            ]
        ),
        encoding="utf-8",
    )


class FakeCliRunner:
    def __init__(self, usable_commands=()):
        self.usable_commands = set(usable_commands)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command):
        self.calls.append(tuple(command))

        class Result:
            def __init__(self, ok: bool):
                self.returncode = 0 if ok else 1
                self.stdout = "ok" if ok else ""
                self.stderr = "" if ok else "not available"

        return Result(command[0] in self.usable_commands)


class RunAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_app = _load_run_app_module()

    def test_cli_domain_has_highest_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli_domain = root / "custom" / "domain.yml"
            env_domain = root / "env" / "domain.yml"
            _write_domain(cli_domain, name="CLI Domain", slug="cli")
            _write_domain(env_domain, name="Env Domain", slug="env")

            resolved = self.run_app.resolve_domain_file(
                project_root=root,
                cli_domain=str(cli_domain),
                env={"LLM_WIKI_DOMAIN": str(env_domain)},
            )

        self.assertEqual(resolved, cli_domain.resolve())

    def test_env_domain_is_used_after_cli_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_domain = root / "env" / "domain.yml"
            _write_domain(env_domain, name="Env Domain", slug="env")

            resolved = self.run_app.resolve_domain_file(
                project_root=root,
                cli_domain=None,
                env={"LLM_WIKI_DOMAIN": str(env_domain)},
            )

        self.assertEqual(resolved, env_domain.resolve())

    def test_user_domain_wins_over_examples_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_domain = root / "user_domains" / "mine" / "domain.yml"
            example_domain = root / "examples" / "finance" / "domain.yml"
            _write_domain(user_domain, name="User Domain", slug="mine")
            _write_domain(example_domain, name="Finance", slug="finance")

            resolved = self.run_app.resolve_domain_file(project_root=root, cli_domain=None, env={})

        self.assertEqual(resolved, user_domain.resolve())

    def test_examples_finance_is_default_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example_domain = root / "examples" / "finance" / "domain.yml"
            _write_domain(example_domain, name="Finance", slug="finance")

            resolved = self.run_app.resolve_domain_file(project_root=root, cli_domain=None, env={})

        self.assertEqual(resolved, example_domain.resolve())

    def test_missing_domain_returns_non_zero_with_friendly_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = self.run_app.main(
                ["--domain", str(root / "missing.yml"), "--check"],
                project_root=root,
                env={},
                stdout=stdout,
                stderr=stderr,
                load_dotenv=False,
                launch_gui=lambda config: (_ for _ in ()).throw(AssertionError("GUI should not launch")),
                cli_runner=FakeCliRunner(),
                pyside6_checker=lambda: True,
            )

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Domain file not found", stderr.getvalue())

    def test_check_does_not_launch_gui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example_domain = root / "examples" / "finance" / "domain.yml"
            _write_domain(example_domain, name="Finance", slug="finance")
            stdout = io.StringIO()
            launched = False

            def launch_gui(config):
                nonlocal launched
                launched = True

            exit_code = self.run_app.main(
                ["--check"],
                project_root=root,
                env={},
                stdout=stdout,
                stderr=io.StringIO(),
                load_dotenv=False,
                launch_gui=launch_gui,
                cli_runner=FakeCliRunner({"gemini.cmd"}),
                pyside6_checker=lambda: True,
            )

        self.assertEqual(exit_code, 0)
        self.assertFalse(launched)
        output = stdout.getvalue()
        self.assertIn("resolved domain path:", output)
        self.assertIn("PySide6 import: ok", output)
        self.assertIn("Gemini CLI: usable", output)
        self.assertIn("selected providers:", output)


if __name__ == "__main__":
    unittest.main()
