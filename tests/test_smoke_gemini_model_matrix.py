import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


def load_matrix_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_gemini_model_matrix.py"
    spec = importlib.util.spec_from_file_location("smoke_gemini_model_matrix", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeGeminiModelMatrixTests(unittest.TestCase):
    def test_default_model_candidates_include_current_default_and_gemini_3_candidates(self):
        matrix = load_matrix_module()

        self.assertEqual(matrix.DEFAULT_MODEL_CANDIDATES[0], "gemini-2.5-flash")
        self.assertIn("gemini-3-flash-preview", matrix.DEFAULT_MODEL_CANDIDATES)
        self.assertIn("gemini-3.1-flash-lite-preview", matrix.DEFAULT_MODEL_CANDIDATES)

    def test_matrix_continues_after_invalid_model_and_reports_summary(self):
        matrix = load_matrix_module()
        calls = []

        def fake_runner(role, model, domain_path, question):
            calls.append((role, model))
            if model == "invalid-model":
                return matrix.MatrixRow(
                    model=model,
                    role=role,
                    result="FAIL",
                    provider="gemini",
                    fallback=True,
                    status="fallback",
                    reason="invalid model id",
                    details={"lint_ok": False},
                )
            return matrix.MatrixRow(
                model=model,
                role=role,
                result="PASS",
                provider="gemini",
                fallback=False,
                status="ok",
                reason="",
                details={"lint_ok": True},
            )

        with tempfile.TemporaryDirectory() as tmp:
            rows = matrix.run_model_matrix(
                models=["invalid-model", "gemini-ok"],
                roles=["ingest"],
                domain_path=Path(tmp) / "domain.yml",
                question="CAPM은 무엇인가?",
                role_runner=fake_runner,
            )

        self.assertEqual(calls, [("ingest", "invalid-model"), ("ingest", "gemini-ok")])
        self.assertEqual([row.result for row in rows], ["FAIL", "PASS"])
        self.assertEqual(matrix.matrix_exit_code(rows, ["ingest"]), 0)
        rendered = matrix.format_matrix_report(rows, ["ingest"])
        self.assertIn("invalid-model", rendered)
        self.assertIn("gemini-ok", rendered)
        self.assertIn("ingest: gemini-ok", rendered)

    def test_exit_code_fails_when_requested_role_has_no_pass(self):
        matrix = load_matrix_module()
        rows = [
            matrix.MatrixRow(
                model="bad",
                role="answer",
                result="FAIL",
                provider="gemini",
                fallback=False,
                status="timeout",
                reason="gemini_timeout",
                details={},
            )
        ]

        self.assertEqual(matrix.matrix_exit_code(rows, ["answer"]), 1)
        self.assertIn("answer: no passing model", matrix.format_recommendations(rows, ["answer"]))

    def test_role_model_environment_is_restored_after_each_smoke(self):
        matrix = load_matrix_module()

        def fake_runner(role, model, domain_path, question):
            self.assertEqual(os.environ.get("LLM_WIKI_INGEST_MODEL"), model)
            self.assertEqual(os.environ.get("LLM_WIKI_INGEST_PROVIDER"), "gemini")
            return matrix.MatrixRow(model, role, "PASS", "gemini", False, "ok", "", {})

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "LLM_WIKI_INGEST_PROVIDER": "codex",
                    "LLM_WIKI_INGEST_MODEL": "old-model",
                },
                clear=True,
            ):
                rows = matrix.run_model_matrix(
                    models=["gemini-test"],
                    roles=["ingest"],
                    domain_path=Path(tmp) / "domain.yml",
                    question="질문",
                    role_runner=fake_runner,
                )
                restored_provider = os.environ.get("LLM_WIKI_INGEST_PROVIDER")
                restored_model = os.environ.get("LLM_WIKI_INGEST_MODEL")

        self.assertEqual(rows[0].result, "PASS")
        self.assertEqual(restored_provider, "codex")
        self.assertEqual(restored_model, "old-model")

    def test_main_prints_table_and_returns_failure_when_role_has_no_pass(self):
        matrix = load_matrix_module()

        def fake_run_model_matrix(models, roles, domain_path, question, role_runner=None):
            return [
                matrix.MatrixRow(models[0], roles[0], "FAIL", "gemini", True, "fallback", "invalid model", {})
            ]

        with patch.object(matrix, "run_model_matrix", side_effect=fake_run_model_matrix):
            with patch.object(matrix, "load_environment_for_matrix", return_value={"exists": False, "loaded": False, "ignored": True}):
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = matrix.main(["--role", "answer", "--model", "bad", "--ignore-dotenv"])

        text = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("Gemini Model Matrix", text)
        self.assertIn("bad", text)
        self.assertIn("SMOKE RESULT: FAIL", text)


if __name__ == "__main__":
    unittest.main()
