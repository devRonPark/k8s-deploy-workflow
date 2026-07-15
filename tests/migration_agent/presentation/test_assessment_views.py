from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from migration_agent.capabilities.repository_analysis import analyze_repository
from migration_agent.presentation.assessment import (
    AssessmentCoverageItem,
    AssessmentCoverageView,
    AssessmentLevel,
    RepositoryAssessmentView,
    build_assessment_view,
)
from migration_agent.presentation.console_view import render_console
from migration_agent.presentation.json_view import render_json
from migration_agent.presentation.markdown_view import render_markdown


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")
LIMITATION_MESSAGE = "Kubernetes manifests are not generated in v1."


def analyze_fixture(fixture_name: str):
    with tempfile.TemporaryDirectory() as tmp:
        result = analyze_repository(FIXTURE_ROOT / fixture_name, Path(tmp) / f"run-{fixture_name}")
        assert result.understanding is not None
        return result.understanding


class RepositoryAssessmentViewTests(unittest.TestCase):
    def test_clear_node_docker_assessment_exposes_required_counts_and_levels(self) -> None:
        view = build_assessment_view(analyze_fixture("node-docker"))

        self.assertEqual(view.components, ["root"])
        self.assertEqual(view.execution, AssessmentLevel.COMPLETE)
        self.assertEqual(view.structure, AssessmentLevel.COMPLETE)
        self.assertEqual(view.build, AssessmentLevel.COMPLETE)
        self.assertEqual(view.container, AssessmentLevel.COMPLETE)
        self.assertGreater(view.confirmed_count, 0)
        self.assertGreater(view.unknown_count, 0)
        self.assertEqual(view.conflict_count, 0)
        self.assertGreater(view.evidence_count, 0)
        self.assertIn("topology.components[0].role", view.notable_unknowns)

    def test_conflict_assessment_keeps_conflict_visible_in_every_view(self) -> None:
        view = build_assessment_view(analyze_fixture("node-compose-conflict"))

        self.assertEqual(view.execution, AssessmentLevel.CONFLICTED)
        self.assertEqual(view.conflict_count, 1)
        self.assertIn("lifecycle.variants[0].runtime_port: 8080, 8081", view.notable_conflicts)

        json_payload = json.loads(render_json(view))
        markdown = render_markdown(view)
        console = render_console(view)

        self.assertEqual(json_payload["conflict_count"], view.conflict_count)
        self.assertEqual(json_payload["execution"], "conflicted")
        for rendered in (markdown, console):
            self.assertIn("8080, 8081", rendered)
            self.assertIn(LIMITATION_MESSAGE, rendered)
            self.assertIn("Confirmed", rendered)
            self.assertIn("Unknown", rendered)
            self.assertIn("Conflicts", rendered)

    def test_json_markdown_and_console_share_the_same_assessment_values(self) -> None:
        view = build_assessment_view(analyze_fixture("node-docker"))
        json_payload = json.loads(render_json(view))
        markdown = render_markdown(view)
        console = render_console(view)

        for key in (
            "components_count",
            "execution",
            "structure",
            "build",
            "container",
            "confirmed_count",
            "unknown_count",
            "conflict_count",
            "evidence_count",
        ):
            self.assertIn(str(json_payload[key]), markdown)
            self.assertIn(str(json_payload[key]), console)
        self.assertEqual(json_payload["kubernetes_manifest_limitation"], LIMITATION_MESSAGE)

    def test_assessment_view_round_trips_and_rejects_invalid_level(self) -> None:
        view = RepositoryAssessmentView(
            components=["root"],
            execution=AssessmentLevel.COMPLETE,
            structure=AssessmentLevel.COMPLETE,
            build=AssessmentLevel.PARTIAL,
            container=AssessmentLevel.UNKNOWN,
            confirmed_count=3,
            unknown_count=2,
            conflict_count=0,
            evidence_count=7,
            notable_unknowns=["lifecycle.variants[0].build_command"],
        )

        again = RepositoryAssessmentView.model_validate(view.model_dump(mode="json"))

        self.assertEqual(again, view)
        with self.assertRaises(ValidationError):
            RepositoryAssessmentView(
                components=["root"],
                execution="done",
                structure=AssessmentLevel.COMPLETE,
                build=AssessmentLevel.COMPLETE,
                container=AssessmentLevel.COMPLETE,
                confirmed_count=1,
                unknown_count=0,
                conflict_count=0,
                evidence_count=1,
            )

    def test_assessment_coverage_view_round_trips_and_rejects_invalid_shape(self) -> None:
        coverage = AssessmentCoverageView(
            parsed_count=1,
            partial_count=1,
            unsupported_count=1,
            ignored_count=0,
            items=[
                AssessmentCoverageItem(
                    artifact_ref="docker-compose.yml",
                    artifact_type="compose",
                    status="partial",
                    reason_code="unresolved_interpolation",
                    details=["web: unresolved interpolation: ${APP_PORT}"],
                )
            ],
            limitations=["docker-compose.yml: partial (unresolved_interpolation)"],
        )

        again = AssessmentCoverageView.model_validate(coverage.model_dump(mode="json"))

        self.assertEqual(again, coverage)
        with self.assertRaises(ValidationError):
            AssessmentCoverageItem(
                artifact_ref="docker-compose.yml",
                artifact_type="compose",
                status="partial",
                details=[],
            )


if __name__ == "__main__":
    unittest.main()
