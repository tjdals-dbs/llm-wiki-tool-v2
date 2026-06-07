import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wiki_tool.user_domain import UserDomainInitError, create_user_domain, discover_domain_files, domain_display_name


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "init_user_domain.py"


class UserDomainInitTests(unittest.TestCase):
    def _write_domain(self, path: Path, *, name: str, slug: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    f"name: {name}",
                    f"slug: {slug}",
                    f"description: Local user domain for {name}.",
                    "raw_dir: raw",
                    "wiki_dir: wiki",
                    "manifest: manifests/raw_sources.csv",
                    "language: ko",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_creates_user_domain_structure_and_domain_yml(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_user_domain(project_root=Path(tmp), slug="finance-private", name="내 금융 위키")
            domain_root = Path(tmp) / "user_domains" / "finance-private"

            self.assertEqual(result.domain_dir, domain_root)
            self.assertTrue((domain_root / "domain.yml").is_file())
            self.assertTrue((domain_root / "raw").is_dir())
            self.assertTrue((domain_root / "manifests").is_dir())
            self.assertTrue((domain_root / "wiki" / "sources").is_dir())
            self.assertTrue((domain_root / "wiki" / "concepts").is_dir())
            self.assertTrue((domain_root / "wiki" / "answers").is_dir())
            self.assertTrue((domain_root / "wiki" / "graph").is_dir())

            domain_yml = (domain_root / "domain.yml").read_text(encoding="utf-8")
            self.assertIn("name: 내 금융 위키", domain_yml)
            self.assertIn("slug: finance-private", domain_yml)
            self.assertIn("description: Local user domain for 내 금융 위키.", domain_yml)
            self.assertIn("raw_dir: raw", domain_yml)
            self.assertIn("wiki_dir: wiki", domain_yml)
            self.assertIn("manifest: manifests/raw_sources.csv", domain_yml)
            self.assertIn("language: ko", domain_yml)

    def test_existing_slug_fails_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_user_domain(project_root=root, slug="finance-private", name="내 금융 위키")

            with self.assertRaises(UserDomainInitError):
                create_user_domain(project_root=root, slug="finance-private", name="다른 이름")

    def test_invalid_slug_and_path_traversal_are_rejected(self):
        invalid_slugs = ["Finance", "finance private", "../escape", "finance/private", "한글", ".hidden"]

        with tempfile.TemporaryDirectory() as tmp:
            for slug in invalid_slugs:
                with self.subTest(slug=slug):
                    with self.assertRaises(UserDomainInitError):
                        create_user_domain(project_root=Path(tmp), slug=slug, name="Invalid")

    def test_cli_success_prints_domain_path_and_gui_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    tmp,
                    "--slug",
                    "finance-private",
                    "--name",
                    "내 금융 위키",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("domain.yml", result.stdout)
            self.assertIn("python scripts\\run_desktop_gui.py --domain", result.stdout)
            self.assertTrue((Path(tmp) / "user_domains" / "finance-private" / "domain.yml").is_file())

    def test_cli_failure_returns_non_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    tmp,
                    "--slug",
                    "../escape",
                    "--name",
                    "Invalid",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid slug", result.stderr.lower())

    def test_discovers_examples_user_domains_current_and_deduplicates_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example_domain = root / "examples" / "finance" / "domain.yml"
            user_domain = root / "user_domains" / "finance-private" / "domain.yml"
            broken_domain = root / "user_domains" / "broken" / "domain.yml"
            self._write_domain(example_domain, name="Finance", slug="finance")
            self._write_domain(user_domain, name="내 금융 위키", slug="finance-private")
            broken_domain.parent.mkdir(parents=True, exist_ok=True)
            broken_domain.write_text("name only", encoding="utf-8")

            discovered = discover_domain_files(root, current_domain=example_domain)

            self.assertEqual(discovered, [example_domain.resolve(), user_domain.resolve()])

    def test_discovers_current_domain_outside_repo_without_scanning_outside(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            current = Path(outside) / "domain.yml"
            self._write_domain(current, name="Outside", slug="outside")

            discovered = discover_domain_files(root, current_domain=current)

            self.assertEqual(discovered, [current.resolve()])

    def test_domain_display_name_uses_name_and_slug_with_safe_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "domain.yml"
            self._write_domain(domain, name="내 금융 위키", slug="finance-private")
            invalid = Path(tmp) / "broken.yml"
            invalid.write_text("name only", encoding="utf-8")

            self.assertEqual(domain_display_name(domain), "내 금융 위키 (finance-private)")
            self.assertEqual(domain_display_name(invalid), "broken")


if __name__ == "__main__":
    unittest.main()
