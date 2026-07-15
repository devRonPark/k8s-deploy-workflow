from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


class PipelineComposeOverrideTests(unittest.TestCase):
    def test_override_file_is_merged_not_double_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "docker-compose.yml").write_text(
                "services:\n  api:\n    image: old/api\n    ports:\n      - \"8080:80\"\n",
                encoding="utf-8",
            )
            (repo / "docker-compose.override.yml").write_text(
                "services:\n  api:\n    image: new/api\n",
                encoding="utf-8",
            )

            output_dir = Path(tmp) / "out"
            _, _, evidence, _ = run_phase1_analysis(
                repo=repo,
                output_dir=output_dir,
                url="fixture://override",
                ref="fixture",
                clock=fixed_clock,
            )

            # Outputs were written normally.
            self.assertTrue((output_dir / "02-evidence-model.yaml").is_file())
            rules = yaml.safe_load((output_dir / "03-rule-inference.yaml").read_text(encoding="utf-8"))
            self.assertIn("rule_inference", rules)

        facts = [fact.model_dump() for fact in evidence.facts]

        service_facts = [
            fact for fact in facts
            if fact["fact_type"] == "compose_service" and fact["value"].get("service") == "api"
        ]
        self.assertEqual(len(service_facts), 1, "expected exactly one merged compose_service fact for api")

        image_facts = [
            fact for fact in facts
            if fact["fact_type"] == "compose_image" and fact["value"].get("service") == "api"
        ]
        self.assertEqual(len(image_facts), 1)
        self.assertEqual(image_facts[0]["value"]["image"], "new/api")
        self.assertNotIn(
            "old/api",
            [fact["value"].get("image") for fact in image_facts],
        )

        # The override file still shows up as present via the inventory-derived facts.
        presence_paths = {
            fact["value"]["path"]
            for fact in facts
            if fact["fact_type"] == "artifact_presence"
        }
        self.assertIn("docker-compose.override.yml", presence_paths)

        # Merged service still carries the base file's port mapping.
        port_facts = [
            fact for fact in facts
            if fact["fact_type"] == "compose_port" and fact["value"].get("service") == "api"
        ]
        self.assertEqual(len(port_facts), 1)
        self.assertEqual(port_facts[0]["value"]["container_port"], 80)

    def test_compose_override_file_is_merged_for_compose_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "compose.yaml").write_text(
                "services:\n  api:\n    image: old/api\n    ports:\n      - \"8080:80\"\n",
                encoding="utf-8",
            )
            (repo / "compose.override.yml").write_text(
                "services:\n  api:\n    image: new/api\n",
                encoding="utf-8",
            )

            _, _, evidence, _ = run_phase1_analysis(
                repo=repo,
                output_dir=Path(tmp) / "out",
                url="fixture://compose-override",
                ref="fixture",
                clock=fixed_clock,
            )

        image_facts = [
            fact.model_dump()
            for fact in evidence.facts
            if fact.fact_type == "compose_image" and fact.value.get("service") == "api"
        ]
        self.assertEqual(len(image_facts), 1)
        self.assertEqual(image_facts[0]["value"]["image"], "new/api")


if __name__ == "__main__":
    unittest.main()
