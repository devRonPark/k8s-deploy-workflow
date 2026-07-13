import tempfile
import unittest
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

    def test_unknown_command_returns_nonzero(self):
        self.assertNotEqual(main(["frobnicate"]), 0)


if __name__ == "__main__":
    unittest.main()
