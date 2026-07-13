import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from preanalyzer.cli import main


class CliTests(unittest.TestCase):
    def test_analyze_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                [
                    "analyze",
                    "tests/fixtures/repos/node-express-like",
                    "--profile",
                    "tests/fixtures/profiles/dev-profile.yaml",
                    "--no-llm",
                    "--out",
                    tmp,
                ]
            )

            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "09-kubernetes-intent.yaml").is_file())

    def test_analyze_summary_reports_generation_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "analyze",
                        "tests/fixtures/repos/jpetstore-like",
                        "--profile",
                        "tests/fixtures/profiles/dev-profile.yaml",
                        "--no-llm",
                        "--out",
                        tmp,
                    ]
                )

            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("generation_holds=1", text)
            self.assertIn("생성 보류", text)

    def test_unknown_command_returns_nonzero(self):
        self.assertNotEqual(main(["frobnicate"]), 0)


if __name__ == "__main__":
    unittest.main()
