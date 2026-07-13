from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python3"


def run_agent(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [str(PYTHON), "-m", "k8s_agent.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class PrepareArgumentTests(unittest.TestCase):
    def assertPrepareError(self, result: subprocess.CompletedProcess[str], code: str) -> str:
        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, text)
        self.assertIn(code, text)
        self.assertIn("Resolution:", text)
        self.assertIn("k8s-agent prepare", text)
        self.assertNotIn("Traceback", text)
        return text

    def test_prepare_requires_explicit_source(self):
        result = run_agent("prepare", "--target", "development")

        self.assertPrepareError(result, "CLI-101")

    def test_prepare_rejects_two_sources(self):
        result = run_agent(
            "prepare",
            "--repo-url",
            "https://github.com/example/app.git",
            "--local-path",
            "tests/fixtures/repos/node-express-like",
            "--target",
            "development",
        )

        self.assertPrepareError(result, "CLI-102")

    def test_prepare_rejects_local_path_with_ref(self):
        result = run_agent(
            "prepare",
            "--local-path",
            "tests/fixtures/repos/node-express-like",
            "--ref",
            "main",
            "--target",
            "development",
        )

        self.assertPrepareError(result, "CLI-103")

    def test_prepare_rejects_unknown_target(self):
        result = run_agent(
            "prepare",
            "--local-path",
            "tests/fixtures/repos/node-express-like",
            "--target",
            "qa",
        )

        self.assertPrepareError(result, "CLI-104")

    def test_prepare_non_interactive_requires_answers_file(self):
        result = run_agent(
            "prepare",
            "--local-path",
            "tests/fixtures/repos/node-express-like",
            "--target",
            "development",
            "--non-interactive",
        )

        self.assertPrepareError(result, "CLI-105")

    def test_prepare_accepts_production_target(self):
        result = run_agent(
            "prepare",
            "--local-path",
            "tests/fixtures/repos/node-express-like",
            "--target",
            "production",
        )

        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, text)
        self.assertIn("prepare accepted", text)
        self.assertIn("target=production", text)

    def test_debug_includes_traceback_for_cli_errors(self):
        result = run_agent("--debug", "prepare", "--target", "development")

        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, text)
        self.assertIn("CLI-101", text)
        self.assertIn("Traceback", text)


if __name__ == "__main__":
    unittest.main()
