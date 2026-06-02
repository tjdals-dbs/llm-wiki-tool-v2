import tempfile
import unittest
from pathlib import Path

from wiki_tool.config import DomainConfig, load_domain_config
from wiki_tool.workspace import ensure_workspace_structure


class DomainConfigTests(unittest.TestCase):
    def test_loads_domain_config_with_resolved_paths(self):
        root = Path(__file__).resolve().parents[1]
        config = load_domain_config(root / "examples" / "finance" / "domain.yml", root=root)

        self.assertIsInstance(config, DomainConfig)
        self.assertEqual(config.slug, "finance")
        self.assertEqual(config.language, "ko")
        self.assertEqual(config.raw_dir, root / "raw")
        self.assertEqual(config.wiki_dir, root / "wiki")
        self.assertEqual(config.manifest_path, root / "manifests" / "raw_sources.csv")

    def test_workspace_structure_keeps_existing_raw_files_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            raw_file = raw_dir / "note.md"
            raw_file.write_text("원본 자료", encoding="utf-8")

            domain_file = root / "domain.yml"
            domain_file.write_text(
                "\n".join(
                    [
                        "name: Test Domain",
                        "slug: test",
                        "description: Test wiki.",
                        "raw_dir: raw",
                        "wiki_dir: wiki",
                        "manifest: manifests/raw_sources.csv",
                        "language: ko",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_domain_config(domain_file, root=root)
            ensure_workspace_structure(config)

            self.assertEqual(raw_file.read_text(encoding="utf-8"), "원본 자료")
            self.assertTrue((root / "wiki" / "sources").is_dir())
            self.assertTrue((root / "wiki" / "concepts").is_dir())
            self.assertTrue((root / "wiki" / "answers").is_dir())
            self.assertTrue((root / "wiki" / "graph").is_dir())
            self.assertTrue((root / "manifests").is_dir())


if __name__ == "__main__":
    unittest.main()
