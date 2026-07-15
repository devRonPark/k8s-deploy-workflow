from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from migration_agent.adapters.preanalyzer_adapter import run_legacy_analysis


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")


class PreanalyzerAdapterTests(unittest.TestCase):
    def test_returns_parsed_phase1_structures_for_node_docker_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = run_legacy_analysis(
                repository_path=FIXTURE_ROOT / "node-docker",
                output_dir=Path(tmp),
            )

        self.assertEqual(artifacts.repository_snapshot["analyzed_at"], "1970-01-01T00:00:00Z")
        self.assertEqual(artifacts.artifact_inventory["build_files"][0]["path"], "package.json")
        self.assertEqual(
            artifacts.evidence_model["facts"][0]["classification"],
            "observed_fact",
        )
        self.assertTrue(artifacts.rule_inference["runtime_candidates"])
        self.assertIsNone(artifacts.application_topology)

    def test_adapter_does_not_generate_manifests_or_legacy_agent_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            run_legacy_analysis(
                repository_path=FIXTURE_ROOT / "node-docker",
                output_dir=output_dir,
            )

            self.assertFalse((output_dir / "12-generated-manifests").exists())
            self.assertFalse((output_dir / "13-validation-report.yaml").exists())
            self.assertFalse((output_dir / "04-application-topology.yaml").exists())

    def test_adapter_output_is_stable_across_two_runs(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_artifacts = run_legacy_analysis(
                repository_path=FIXTURE_ROOT / "node-compose-conflict",
                output_dir=Path(first),
            )
            second_artifacts = run_legacy_analysis(
                repository_path=FIXTURE_ROOT / "node-compose-conflict",
                output_dir=Path(second),
            )

        self.assertEqual(first_artifacts.model_dump(), second_artifacts.model_dump())
        self.assertEqual(
            [candidate["port"] for candidate in first_artifacts.rule_inference["runtime_port_candidates"]],
            [8080, 8081],
        )


if __name__ == "__main__":
    unittest.main()
