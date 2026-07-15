from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from pydantic import ValidationError

from migration_agent.capabilities.repository_analysis import (
    InvalidRepositoryInput,
    analyze_repository,
)
from migration_agent.capabilities.results import RepositoryAnalysisResult
from migration_agent.domain.common import FieldState


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")


class RepositoryAnalysisCapabilityTests(unittest.TestCase):
    def test_analyze_repository_writes_discovery_and_understanding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run-node-docker"

            result = analyze_repository(
                repository_path=FIXTURE_ROOT / "node-docker",
                run_root=run_root,
            )

            self.assertEqual(result.run_id, "run-node-docker")
            self.assertEqual(result.status, "analysis_complete")
            self.assertIsNotNone(result.understanding)
            self.assertEqual(
                set(result.artifact_paths),
                {"discovery", "repository_understanding"},
            )
            self.assertTrue((run_root / "discovery.json").is_file())
            self.assertTrue((run_root / "repository-understanding.yaml").is_file())

            discovery = json.loads((run_root / "discovery.json").read_text(encoding="utf-8"))
            self.assertEqual(discovery["schema_version"], "repository-discovery/v1-beta")
            self.assertIn("artifact_inventory", discovery)
            self.assertIn("evidence_model", discovery)
            self.assertIn("rule_inference", discovery)

            understanding = yaml.safe_load(
                (run_root / "repository-understanding.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(understanding["schema_version"], "repository-understanding/v1-beta")
            self.assertEqual(understanding["lifecycle"]["variants"][0]["run_command"]["state"], "resolved")
            self.assertEqual(understanding["lifecycle"]["variants"][0]["runtime_port"]["value"], 3000)

    def test_conflicts_complete_without_inventing_effective_values_or_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run-conflict"

            result = analyze_repository(
                repository_path=FIXTURE_ROOT / "node-compose-conflict",
                run_root=run_root,
            )

            self.assertEqual(result.status, "analysis_complete")
            self.assertIsNotNone(result.understanding)
            runtime_port = result.understanding.lifecycle.variants[0].runtime_port
            self.assertEqual(runtime_port.state, FieldState.CONFLICT)
            self.assertIsNone(runtime_port.value)
            self.assertEqual([candidate["value"] for candidate in runtime_port.candidates], [8080, 8081])

            generated_paths = [path.name for path in run_root.rglob("*") if path.is_file()]
            self.assertNotIn("manifest-bundle.yaml", generated_paths)
            self.assertFalse(any("proposal" in name for name in generated_paths))
            self.assertFalse(any("decision" in name for name in generated_paths))
            self.assertFalse(any("validation" in name for name in generated_paths))

    def test_invalid_repository_path_is_rejected_as_user_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InvalidRepositoryInput):
                analyze_repository(
                    repository_path=Path(tmp) / "missing",
                    run_root=Path(tmp) / "run-missing",
                )

    def test_repository_analysis_result_round_trips_and_rejects_invalid_status(self) -> None:
        result = RepositoryAnalysisResult(
            run_id="run-123",
            status="analysis_complete",
            artifact_paths={"discovery": "discovery.json"},
            warnings=["safe warning"],
            next_capabilities=["repository_assessment"],
        )

        again = RepositoryAnalysisResult.model_validate(result.model_dump(mode="json"))

        self.assertEqual(again, result)
        with self.assertRaises(ValidationError):
            RepositoryAnalysisResult(run_id="run-123", status="complete")

    def test_engine_failure_warning_is_redacted_before_result_or_cli_output(self) -> None:
        canary = "super-secret-token"

        def fail_analysis(*args, **kwargs):
            raise RuntimeError(f"password={canary} Bearer {canary}")

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "migration_agent.capabilities.repository_analysis.run_legacy_analysis",
                side_effect=fail_analysis,
            ):
                result = analyze_repository(
                    repository_path=FIXTURE_ROOT / "node-docker",
                    run_root=Path(tmp) / "run-failed",
                )

        self.assertEqual(result.status, "analysis_failed")
        dumped = json.dumps(result.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn(canary, dumped)
        self.assertIn("[REDACTED]", dumped)


if __name__ == "__main__":
    unittest.main()
