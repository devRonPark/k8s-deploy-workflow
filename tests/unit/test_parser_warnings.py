from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

import yaml

from preanalyzer.analyzer.parsers.maven import ParseWarning as MavenWarning, try_parse as try_parse_maven
from preanalyzer.analyzer.parsers.nodejs import ParseWarning as NodeWarning, try_parse as try_parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import ParseWarning as PythonWarning, try_parse_pyproject
from preanalyzer.pipeline import run_phase1_analysis


class ParserWarningTests(unittest.TestCase):
    def test_malformed_maven_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pom.xml"
            path.write_text("<project>", encoding="utf-8")
            result = try_parse_maven(path)

        self.assertIsInstance(result, MavenWarning)
        self.assertEqual(result.path, str(path))
        self.assertEqual(result.parser, "maven")

    def test_malformed_package_json_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            path.write_text("{", encoding="utf-8")
            result = try_parse_nodejs(path)

        self.assertIsInstance(result, NodeWarning)
        self.assertEqual(result.parser, "nodejs")

    def test_malformed_pyproject_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text("[project", encoding="utf-8")
            result = try_parse_pyproject(path)

        self.assertIsInstance(result, PythonWarning)
        self.assertEqual(result.parser, "python_pyproject")


class PipelineParserWarningWiringTests(unittest.TestCase):
    """Integration-level coverage: proves run_phase1_analysis actually wires
    ParseWarning results into evidence_model.warnings (P5) and skips them
    from parsed facts, instead of just testing the try_parse_* wrappers in
    isolation.
    """

    def test_malformed_package_json_is_skipped_and_warned_while_dockerfile_still_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()

            # Malformed artifact: invalid JSON, should degrade to a warning.
            (repo / "package.json").write_text("{", encoding="utf-8")

            # Valid artifact in the same repo: should still be parsed normally.
            (repo / "Dockerfile").write_text(
                "FROM node:18\nEXPOSE 3000\nCMD [\"node\", \"server.js\"]\n",
                encoding="utf-8",
            )

            output_dir = Path(tmp) / "out"

            def fixed_clock() -> datetime:
                return datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)

            # Must not raise despite the malformed package.json.
            run_phase1_analysis(
                repo=repo,
                output_dir=output_dir,
                url="fixture://malformed-package-json",
                ref="fixture",
                clock=fixed_clock,
            )

            document = yaml.safe_load((output_dir / "02-evidence-model.yaml").read_text(encoding="utf-8"))
            evidence_model = document["evidence_model"]

            # P5: the warning must be recorded, not silently dropped.
            warnings = evidence_model["warnings"]
            self.assertEqual(len(warnings), 1)
            warning_payload = json.loads(warnings[0])
            # Relative inventory path only — no absolute temp-dir path leaked (P10).
            self.assertEqual(warning_payload["path"], "package.json")
            self.assertEqual(warning_payload["parser"], "nodejs")
            self.assertNotIn(str(repo), warning_payload["message"])

            facts = evidence_model["facts"]

            # The malformed package.json must not appear as if it parsed successfully:
            # no package_dependency/package_script facts should be derived from it.
            derived_from_malformed_file = [
                fact
                for fact in facts
                if fact["fact_type"] in {"package_dependency", "package_script"}
                and fact["artifact_ref"] == "package.json"
            ]
            self.assertEqual(derived_from_malformed_file, [])

            # The rest of the repo must still process normally: the Dockerfile's
            # EXPOSE port should be present as an observed fact.
            dockerfile_expose_facts = [fact for fact in facts if fact["fact_type"] == "dockerfile_expose"]
            self.assertEqual(len(dockerfile_expose_facts), 1)
            self.assertEqual(dockerfile_expose_facts[0]["value"], 3000)
            self.assertEqual(dockerfile_expose_facts[0]["artifact_ref"], "Dockerfile")

            # The malformed file is still recorded as present in the inventory
            # (P5 again: no silent disappearance), just not parsed into facts.
            presence_facts = [
                fact
                for fact in facts
                if fact["fact_type"] == "artifact_presence" and fact["artifact_ref"] == "package.json"
            ]
            self.assertEqual(len(presence_facts), 1)
            self.assertTrue(presence_facts[0]["value"]["present"])


if __name__ == "__main__":
    unittest.main()
