import csv
import tempfile
import unittest
from pathlib import Path

from wiki_tool.config import load_domain_config
from wiki_tool.scanner import scan_raw_sources


def write_domain(root: Path) -> Path:
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
    return domain_file


class RawScannerTests(unittest.TestCase):
    def test_scan_records_new_raw_file_with_sha256_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "lesson.md"
            raw_file.parent.mkdir()
            raw_file.write_text("CAPM은 위험과 기대수익률을 연결한다.", encoding="utf-8")
            before = raw_file.stat().st_mtime_ns

            result = scan_raw_sources(domain)

            self.assertEqual(result.new_count, 1)
            self.assertEqual(raw_file.read_text(encoding="utf-8"), "CAPM은 위험과 기대수익률을 연결한다.")
            self.assertEqual(raw_file.stat().st_mtime_ns, before)

            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], "lesson.md")
            self.assertEqual(rows[0]["source_type"], "markdown")
            self.assertEqual(rows[0]["status"], "new")
            self.assertEqual(len(rows[0]["sha256"]), 64)

    def test_scan_preserves_status_for_unchanged_files_and_marks_changed_file_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            raw_file = root / "raw" / "lesson.md"
            raw_file.parent.mkdir()
            raw_file.write_text("첫 버전", encoding="utf-8")

            scan_raw_sources(domain)
            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            rows[0]["status"] = "summarized"
            domain.manifest_path.write_text(
                _write_csv(rows),
                encoding="utf-8",
                newline="",
            )

            unchanged = scan_raw_sources(domain)
            self.assertEqual(unchanged.changed_count, 0)
            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "summarized")

            raw_file.write_text("두 번째 버전", encoding="utf-8")
            changed = scan_raw_sources(domain)

            self.assertEqual(changed.changed_count, 1)
            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0]["status"], "new")

    def test_scan_ignores_private_raw_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = load_domain_config(write_domain(root), root=root)
            private_file = root / "raw" / "private" / "secret.md"
            private_file.parent.mkdir(parents=True)
            private_file.write_text("비공개 자료", encoding="utf-8")

            result = scan_raw_sources(domain)

            self.assertEqual(result.ignored_count, 1)
            rows = list(csv.DictReader(domain.manifest_path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows, [])


def _write_csv(rows: list[dict[str, str]]) -> str:
    from io import StringIO

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["path", "sha256", "source_type", "status", "detected_at", "source_page", "notes"],
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
