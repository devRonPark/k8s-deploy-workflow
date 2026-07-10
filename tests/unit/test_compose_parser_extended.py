from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse, parse_with_override


class ComposeParserExtendedTests(unittest.TestCase):
    def test_override_file_merges_service_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            base.write_text("services:\n  api:\n    image: old/api\n    ports:\n      - \"8080:80\"\n", encoding="utf-8")
            override.write_text("services:\n  api:\n    image: new/api\n", encoding="utf-8")

            parsed = parse_with_override(base, override)

        self.assertEqual(parsed.service("api").image, "new/api")
        self.assertEqual(parsed.service("api").ports[0].container_port, 80)

    def test_override_file_merges_environment_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            base.write_text(
                "services:\n  api:\n    image: api\n    environment:\n      A: \"1\"\n      B: \"2\"\n",
                encoding="utf-8",
            )
            override.write_text(
                "services:\n  api:\n    environment:\n      C: \"3\"\n",
                encoding="utf-8",
            )

            parsed = parse_with_override(base, override)

        self.assertEqual(parsed.service("api").environment, {"A": "1", "B": "2", "C": "3"})

    def test_empty_secret_environment_value_is_not_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text(
                "services:\n  api:\n    image: api\n    environment:\n      API_SECRET_KEY:\n",
                encoding="utf-8",
            )

            parsed = parse(compose)
            evidence = build_evidence(inventory=_empty_inventory(), parsed_artifacts={"docker-compose.yml": parsed})

        self.assertIn(
            {
                "fact_type": "compose_environment",
                "artifact_ref": "docker-compose.yml",
                "source": "compose_environment",
                "classification": "observed_fact",
                "value": {"service": "api", "name": "API_SECRET_KEY", "value_present": False},
            },
            [_without_id(fact.model_dump()) for fact in evidence.facts],
        )
        self.assertNotIn("None", repr(evidence.model_dump()))

    def test_unsupported_keys_warned_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text("services:\n  api:\n    image: api\n    network_mode: host\n", encoding="utf-8")

            parsed = parse(compose)

        self.assertEqual(parsed.warnings, ["api: unsupported key network_mode"])

    def test_named_volume_recorded_as_evidence_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text("services:\n  db:\n    image: postgres:16\n    volumes:\n      - pgdata:/var/lib/postgresql/data\nvolumes:\n  pgdata: {}\n", encoding="utf-8")

            parsed = parse(compose)
            evidence = build_evidence(inventory=_empty_inventory(), parsed_artifacts={"docker-compose.yml": parsed})

        self.assertIn(
            {
                "fact_type": "compose_volume",
                "artifact_ref": "docker-compose.yml",
                "source": "compose_volumes",
                "classification": "observed_fact",
                "value": {"service": "db", "volume": "pgdata:/var/lib/postgresql/data"},
            },
            [_without_id(fact.model_dump()) for fact in evidence.facts],
        )


def _empty_inventory():
    from preanalyzer.models.inventory import ArtifactInventory
    return ArtifactInventory()


def _without_id(value):
    value = dict(value)
    value.pop("evidence_id")
    return value


if __name__ == "__main__":
    unittest.main()
