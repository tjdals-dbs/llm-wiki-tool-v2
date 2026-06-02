import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_EXAMPLE_RAW_SUFFIXES = {
    ".env",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".key",
    ".pdf",
    ".png",
    ".webp",
    ".zip",
}


class RepositoryPrivacyTests(unittest.TestCase):
    def test_gitignore_blocks_private_and_binary_example_raw_sources(self):
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("/examples/**/raw/private/", gitignore)
        for suffix in sorted(FORBIDDEN_EXAMPLE_RAW_SUFFIXES):
            self.assertIn(f"/examples/**/raw/**/*{suffix}", gitignore)

    def test_tracked_example_raw_files_are_public_safe_text_fixtures(self):
        result = subprocess.run(
            ["git", "ls-files", "examples"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        tracked_example_raw = [
            Path(path)
            for path in result.stdout.splitlines()
            if "/raw/" in path.replace("\\", "/")
        ]
        forbidden = [
            path.as_posix()
            for path in tracked_example_raw
            if "private" in path.parts or path.suffix.lower() in FORBIDDEN_EXAMPLE_RAW_SUFFIXES
        ]
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
