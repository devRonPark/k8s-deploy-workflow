from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from migration_agent.cli.main import main


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")
LIMITATION_MESSAGE = "Kubernetes manifests are not generated in v1."


class AssessCommandTests(unittest.TestCase):
    def test_assess_writes_required_outputs_and_console_summary_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "beta-run"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["assess", str(FIXTURE_ROOT / "node-docker"), "--output", str(output)])

            self.assertEqual(code, 0)
            text = stdout.getvalue()
            for label in (
                "Components",
                "Execution",
                "Structure",
                "Build",
                "Container",
                "Confirmed",
                "Unknown",
                "Conflicts",
                "Evidence",
            ):
                self.assertIn(label, text)
            self.assertIn(LIMITATION_MESSAGE, text)

            for name in (
                "discovery.json",
                "repository-understanding.yaml",
                "repository-assessment.json",
                "repository-assessment.md",
            ):
                self.assertTrue((output / name).is_file(), name)

            generated_paths = [path.name for path in output.rglob("*") if path.is_file()]
            self.assertFalse(any("manifest" in name and name != "repository-assessment.md" for name in generated_paths))
            self.assertFalse(any("proposal" in name for name in generated_paths))
            self.assertFalse(any("decision" in name for name in generated_paths))
            self.assertFalse(any("validation" in name for name in generated_paths))

    def test_assess_conflict_returns_zero_and_keeps_conflict_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "conflict-run"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["assess", str(FIXTURE_ROOT / "node-compose-conflict"), "--output", str(output)])

            self.assertEqual(code, 0)
            self.assertIn("8080, 8081", stdout.getvalue())
            assessment = json.loads((output / "repository-assessment.json").read_text(encoding="utf-8"))
            self.assertEqual(assessment["execution"], "conflicted")
            self.assertEqual(assessment["conflict_count"], 1)

    def test_format_json_prints_json_but_still_writes_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "json-run"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "assess",
                        str(FIXTURE_ROOT / "node-docker"),
                        "--output",
                        str(output),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["kubernetes_manifest_limitation"], LIMITATION_MESSAGE)
            self.assertTrue((output / "repository-assessment.md").is_file())

    def test_invalid_repository_path_returns_exit_code_two(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            code = main(["assess", "tests/fixtures/migration_agent/missing"])

        self.assertEqual(code, 2)
        self.assertIn("repository path does not exist", stderr.getvalue())

    def test_pyproject_exposes_repository_agent_entry_point(self) -> None:
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('repository-agent = "migration_agent.cli.main:main"', pyproject)


if __name__ == "__main__":
    unittest.main()
