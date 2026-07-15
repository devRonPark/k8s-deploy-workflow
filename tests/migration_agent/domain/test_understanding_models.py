from __future__ import annotations

import unittest

import yaml
from pydantic import ValidationError

from migration_agent.domain.common import FieldState, TrackedValue
from migration_agent.domain.lifecycle import LifecycleModel, LifecycleVariant
from migration_agent.domain.repository import RepositoryIdentity
from migration_agent.domain.topology import ApplicationComponent, ApplicationTopology
from migration_agent.domain.understanding import (
    ConfirmedFact,
    ConflictFinding,
    EvidenceRef,
    RepositoryUnderstanding,
    UnderstandingCoverage,
    UnknownFinding,
)


def evidence(evidence_id: str = "F0001") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        artifact_ref="Dockerfile",
        fact_type="dockerfile_expose",
        source="dockerfile_expose",
        classification="observed_fact",
    )


def resolved(value: object = 3000) -> TrackedValue:
    return TrackedValue(
        state=FieldState.RESOLVED,
        value=value,
        source="dockerfile_expose",
        confidence="high",
        classification="rule_inference",
        evidence_refs=["F0001"],
    )


def unresolved(reason: str = "No repository evidence was found.") -> TrackedValue:
    return TrackedValue(state=FieldState.UNRESOLVED, reason=reason)


def lifecycle_variant() -> LifecycleVariant:
    return LifecycleVariant(
        build_command=unresolved("No build command evidence was found."),
        package_command=unresolved("No package command evidence was found."),
        run_command=resolved('["node", "server.js"]'),
        runtime_port=resolved(3000),
        environment_variable_names=["NODE_ENV"],
        external_dependencies=[],
        container_build_strategy=resolved("existing_dockerfile"),
        container_entrypoint=resolved('["node", "server.js"]'),
    )


def understanding(**overrides: object) -> RepositoryUnderstanding:
    payload: dict[str, object] = {
        "schema_version": "repository-understanding/v1-beta",
        "repository": RepositoryIdentity(
            path="tests/fixtures/migration_agent/node-docker",
            commit_sha="abc123",
            workspace_hash="sha256:123",
            analyzed_at="1970-01-01T00:00:00Z",
        ),
        "topology": ApplicationTopology(
            components=[
                ApplicationComponent(
                    component_id="root",
                    root_path=".",
                    role="application",
                    evidence_refs=["F0001"],
                )
            ]
        ),
        "lifecycle": LifecycleModel(variants=[lifecycle_variant()]),
        "confirmed_facts": [
            ConfirmedFact(
                fact_id="runtime_port",
                field_path="lifecycle.variants[0].runtime_port",
                value=3000,
                source="dockerfile_expose",
                confidence="high",
                classification="rule_inference",
                evidence_refs=["F0001"],
            )
        ],
        "unknowns": [
            UnknownFinding(
                field_path="lifecycle.variants[0].build_command",
                reason="No build command evidence was found.",
            )
        ],
        "conflicts": [],
        "evidence": [evidence()],
        "coverage": UnderstandingCoverage(
            analyzed_artifacts=2,
            supported_artifacts=2,
            unsupported_artifacts=[],
        ),
    }
    payload.update(overrides)
    return RepositoryUnderstanding(**payload)


class UnderstandingModelTests(unittest.TestCase):
    def test_tracked_value_state_payloads_are_validated(self) -> None:
        with self.assertRaises(ValidationError):
            TrackedValue(state=FieldState.RESOLVED)

        with self.assertRaises(ValidationError):
            TrackedValue(state=FieldState.CONFLICT, candidates=[3000])

        with self.assertRaises(ValidationError):
            TrackedValue(state=FieldState.CONFLICT, value=3000, candidates=[3000, 8080])

        with self.assertRaises(ValidationError):
            TrackedValue(state=FieldState.UNRESOLVED)

        conflict = TrackedValue(
            state=FieldState.CONFLICT,
            candidates=[
                {
                    "value": 3000,
                    "source": "dockerfile_expose",
                    "confidence": "high",
                    "classification": "rule_inference",
                    "evidence_refs": ["F0001"],
                },
                {
                    "value": 8080,
                    "source": "compose_ports",
                    "confidence": "medium",
                    "classification": "rule_inference",
                    "evidence_refs": ["F0002"],
                },
            ],
            evidence_refs=["F0001", "F0002"],
            reason="Dockerfile and Compose expose different runtime ports.",
        )

        self.assertIsNone(conflict.value)
        self.assertEqual([candidate["value"] for candidate in conflict.candidates], [3000, 8080])

    def test_repository_understanding_requires_evidence_backed_facts(self) -> None:
        with self.assertRaises(ValidationError):
            ConfirmedFact(
                fact_id="runtime_port",
                field_path="lifecycle.variants[0].runtime_port",
                value=3000,
                source="dockerfile_expose",
                confidence="high",
                classification="rule_inference",
                evidence_refs=[],
            )

        with self.assertRaises(ValidationError):
            understanding(evidence=[evidence("F0001"), evidence("F0001")])

        with self.assertRaises(ValidationError):
            understanding(
                confirmed_facts=[
                    ConfirmedFact(
                        fact_id="runtime_port",
                        field_path="lifecycle.variants[0].runtime_port",
                        value=3000,
                        source="dockerfile_expose",
                        confidence="high",
                        classification="rule_inference",
                        evidence_refs=["missing"],
                    )
                ]
            )

    def test_unknowns_and_conflicts_are_first_class_findings(self) -> None:
        finding = UnknownFinding(
            field_path="lifecycle.variants[0].container_build_strategy",
            reason="No Dockerfile evidence was found.",
            evidence_refs=[],
        )
        conflict = ConflictFinding(
            field_path="lifecycle.variants[0].runtime_port",
            candidates=[
                {
                    "value": 3000,
                    "source": "dockerfile_expose",
                    "confidence": "high",
                    "classification": "rule_inference",
                    "evidence_refs": ["F0001"],
                },
                {
                    "value": 8080,
                    "source": "compose_ports",
                    "confidence": "medium",
                    "classification": "rule_inference",
                    "evidence_refs": ["F0002"],
                },
            ],
            evidence_refs=["F0001", "F0002"],
            reason="Dockerfile and Compose expose different runtime ports.",
        )

        model = understanding(
            unknowns=[finding],
            conflicts=[conflict],
            evidence=[evidence("F0001"), evidence("F0002")],
        )

        self.assertEqual(model.unknowns[0].field_path, "lifecycle.variants[0].container_build_strategy")
        self.assertEqual([candidate["value"] for candidate in model.conflicts[0].candidates], [3000, 8080])

    def test_extra_fields_block_target_proposal_decision_and_manifest_concepts(self) -> None:
        for forbidden in ("target", "proposal", "decision", "manifest"):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValidationError):
                    understanding(**{forbidden: {"value": "not repository evidence"}})

        with self.assertRaises(ValidationError):
            TrackedValue(
                state=FieldState.RESOLVED,
                value=3000,
                evidence_refs=["F0001"],
                manifest={"kind": "Deployment"},
            )

    def test_yaml_serialization_is_stable(self) -> None:
        dumped = yaml.safe_dump(
            understanding().model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )

        self.assertEqual(
            dumped,
            yaml.safe_dump(yaml.safe_load(dumped), sort_keys=False, allow_unicode=True),
        )
        self.assertLess(dumped.index("schema_version:"), dumped.index("repository:"))
        self.assertIn("confirmed_facts:", dumped)


if __name__ == "__main__":
    unittest.main()
