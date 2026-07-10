from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

import yaml

from preanalyzer.analyzer.parsers.compose import try_parse as try_parse_compose
from preanalyzer.analyzer.parsers.dockerfile import try_parse as try_parse_dockerfile
from preanalyzer.analyzer.parsers.result import ParseWarning
from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


class ParserWarningIsolationTests(unittest.TestCase):
    def test_invalid_compose_yaml_becomes_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compose.yaml"
            path.write_text("services: [unbalanced\n", encoding="utf-8")
            result = try_parse_compose(path)

        self.assertIsInstance(result, ParseWarning)
        self.assertEqual(result.parser, "compose")
        self.assertEqual(result.code, "invalid_yaml")
        self.assertFalse(result.fatal)

    def test_uninterpolatable_compose_port_is_recorded_unresolved(self):
        # ${VAR} ports must not crash the parser; they are preserved as raw and
        # flagged unresolved rather than guessed (TASK-005).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compose.yaml"
            path.write_text(
                "services:\n  web:\n    image: nginx\n    ports:\n      - \"${HTTP_PORT}:80\"\n",
                encoding="utf-8",
            )
            result = try_parse_compose(path)

        self.assertNotIsInstance(result, ParseWarning)
        port = result.service("web").ports[0]
        self.assertEqual(port.raw, "${HTTP_PORT}:80")
        self.assertFalse(port.resolved)
        self.assertIsNone(port.host_port)
        self.assertEqual(port.container_port, 80)

    def test_invalid_dockerfile_encoding_becomes_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_bytes(b"FROM scratch\n\xff\xfe not utf-8\n")
            result = try_parse_dockerfile(path)

        self.assertIsInstance(result, ParseWarning)
        self.assertEqual(result.parser, "dockerfile")
        self.assertEqual(result.code, "invalid_encoding")


class PipelineIsolationTests(unittest.TestCase):
    def test_multiple_broken_parsers_do_not_abort_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()

            # Three simultaneously broken artifacts.
            (repo / "compose.yaml").write_text("services: [broken\n", encoding="utf-8")
            (repo / "package.json").write_text("{", encoding="utf-8")
            (repo / "pom.xml").write_text("<project>", encoding="utf-8")

            # A healthy artifact that must still parse.
            (repo / "Dockerfile").write_text(
                'FROM python:3.12\nEXPOSE 8000\nCMD ["python", "app.py"]\n',
                encoding="utf-8",
            )

            out = Path(tmp) / "out"
            run_phase1_analysis(
                repo=repo,
                output_dir=out,
                url="fixture://broken",
                ref="fixture",
                clock=fixed_clock,
            )

            # All four Phase 1 outputs must exist despite the broken files.
            for filename in [
                "00-repository-snapshot.yaml",
                "01-artifact-inventory.yaml",
                "02-evidence-model.yaml",
                "03-rule-inference.yaml",
            ]:
                self.assertTrue((out / filename).is_file(), filename)

            evidence = yaml.safe_load((out / "02-evidence-model.yaml").read_text(encoding="utf-8"))
            warnings = evidence["evidence_model"]["warnings"]
            payloads = [json.loads(w) for w in warnings]
            parsers = {p["parser"] for p in payloads}

            # Every broken parser reported a uniform warning with a code + path.
            self.assertEqual({"compose", "nodejs", "maven"}, parsers)
            for payload in payloads:
                self.assertIn("code", payload)
                self.assertIn("fatal", payload)
                self.assertNotIn(str(repo), payload["message"])

            # The healthy Dockerfile still produced its EXPOSE fact.
            facts = evidence["evidence_model"]["facts"]
            expose = [f for f in facts if f["fact_type"] == "dockerfile_expose"]
            self.assertEqual(len(expose), 1)
            self.assertEqual(expose[0]["value"], 8000)

            # Broken artifacts remain present in the inventory (no silent loss).
            presence = {
                f["artifact_ref"]
                for f in facts
                if f["fact_type"] == "artifact_presence"
            }
            self.assertIn("compose.yaml", presence)
            self.assertIn("package.json", presence)


if __name__ == "__main__":
    unittest.main()
