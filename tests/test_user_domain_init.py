import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wiki_tool.user_domain import UserDomainInitError, create_user_domain


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "init_user_domain.py"


class UserDomainInitTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
