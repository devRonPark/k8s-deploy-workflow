from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from k8s_agent.models.topology import ApplicationComponent, ApplicationTopology
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.evaluation.repository_analysis import (
    DEFAULT_QUALITY_THRESHOLDS,
    CaseScore,
    ExpectedField,
    FieldScore,
    HumanBaseline,
    RepositoryRegistry,
    RepositoryCorpus,
    RepositoryCorpusLock,
    initialize_human_baseline_lock,
    initialize_repository_corpus_lock,
    initialize_repository_registry_lock,
    load_repository_registry,
    validate_repository_registry,
    load_repository_corpus,
    load_human_baseline,
    run_repository_scorecard,
    update_human_baseline_lock,
    update_repository_registry_lock,
    verify_human_baseline_lock,
    verify_repository_registry_lock,
    update_repository_corpus_lock,
    verify_repository_corpus_lock,
    _evidence_reference_index,
    _calculate_metrics,
    _redact_value,
    _score_field,
)


EVALUATION_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "evaluation"
    / "repository_analysis"
)


def _corpus(case_ids: list[str] | None = None) -> dict:
    selected = case_ids or ["case-a"]
    return {
        "schema_version": "repository-analysis-corpus/v1",
        "corpus_version": "1",
        "change_history": [
            {
                "version": "1",
                "reason": "Initial expert truth.",
                "affected_cases": selected,
            }
        ],
        "cases": [
            {
                "case_id": case_id,
                "visibility": "contract",
                "revision": "fixture-v1",
                "fields": [
                    {
                        "field_id": "components.root.present",
                        "group": "core",
                        "expected_state": "resolved",
                        "expected_value": True,
                        "expected_evidence": [
                            {"artifact": "package.json", "locator": "jsonpath:$"}
                        ],
                    }
                ],
            }
            for case_id in selected
        ],
    }


class RepositoryCorpusLockTests(unittest.TestCase):
    def test_artifact_contract_requires_each_case_field_state_combination(self):
        corpus = _corpus()
        corpus["cases"][0]["scenario"] = "normal"
        corpus["cases"][0]["artifact_types"] = ["node_package"]
        corpus["artifact_contract"] = [
            {
                "artifact_type": "node_package",
                "field_id": "components.root.present",
                "scenario": "normal",
                "expected_state": "resolved",
                "not_applicable_reason": "Covered by a different explicit row in real corpora.",
            }
        ]

        with self.assertRaisesRegex(ValueError, "field/state combination"):
            RepositoryCorpus.model_validate(corpus)

    def test_artifact_contract_requires_each_supported_artifact_state(self):
        corpus = _corpus()
        corpus["cases"][0]["scenario"] = "normal"
        corpus["cases"][0]["artifact_types"] = ["node_package"]
        corpus["artifact_contract"] = [
            {
                "artifact_type": "node_package",
                "field_id": "components.root.present",
                "scenario": "normal",
                "expected_state": "resolved",
                "case_id": "case-a",
            },
            {
                "artifact_type": "node_package",
                "field_id": "artifact_contract.node_package.absence",
                "scenario": "absence",
                "expected_state": "not_applicable",
                "not_applicable_reason": "No absence fixture in this tiny corpus.",
            },
        ]

        with self.assertRaisesRegex(ValueError, "missing scenarios"):
            RepositoryCorpus.model_validate(corpus)

    def test_changed_truth_requires_new_version_reason_and_affected_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus = _corpus()
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            initialized = initialize_repository_corpus_lock(corpus_path, lock_path)

            self.assertEqual(
                initialized,
                RepositoryCorpusLock.model_validate(
                    initialized.model_dump(mode="json")
                ),
            )

            verify_repository_corpus_lock(corpus_path, lock_path)
            corpus["cases"][0]["fields"][0]["expected_value"] = False
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "content hash"):
                verify_repository_corpus_lock(corpus_path, lock_path)
            with self.assertRaisesRegex(ValueError, "new corpus version"):
                update_repository_corpus_lock(corpus_path, lock_path)

            corpus["corpus_version"] = "2"
            corpus["change_history"].append(
                {
                    "version": "2",
                    "reason": "Correct the component expectation.",
                    "affected_cases": ["case-a"],
                }
            )
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            update_repository_corpus_lock(corpus_path, lock_path)

            verify_repository_corpus_lock(corpus_path, lock_path)
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual([entry["version"] for entry in lock["entries"]], ["1", "2"])

    def test_scoring_rule_change_invalidates_existing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus_path.write_text(
                yaml.safe_dump(_corpus(), sort_keys=False), encoding="utf-8"
            )
            initialize_repository_corpus_lock(corpus_path, lock_path)

            with patch.dict(
                DEFAULT_QUALITY_THRESHOLDS,
                {"auto_confirmed_accuracy": 0.99},
            ):
                with self.assertRaisesRegex(ValueError, "scoring rules hash"):
                    verify_repository_corpus_lock(corpus_path, lock_path)


class ScorecardMetricTests(unittest.TestCase):
    def test_auto_confirmed_accuracy_counts_core_and_extended_fields(self):
        fields = [
            FieldScore(
                field_id="components.root.present",
                group="core",
                variant="common",
                expected_state="resolved",
                expected_value=True,
                actual_state="resolved",
                actual_value=False,
                correct=False,
            ),
            FieldScore(
                field_id="components.root.build_strategy",
                group="extended",
                variant="common",
                expected_state="resolved",
                expected_value="buildpack",
                actual_state="resolved",
                actual_value="buildpack",
                correct=True,
            ),
        ]

        metrics = _calculate_metrics(
            [
                CaseScore(
                    case_id="case-a",
                    visibility="contract",
                    revision="fixture-v1",
                    fields=fields,
                )
            ]
        )

        self.assertEqual(metrics.auto_confirmed_accuracy, 0.5)

    def test_evidence_reference_accuracy_counts_core_fields(self):
        fields = [
            FieldScore(
                field_id="components.root.runtime_port",
                group="core",
                variant="common",
                expected_state="resolved",
                expected_value=3000,
                actual_state="resolved",
                actual_value=3000,
                correct=True,
                evidence_correct=False,
                evidence_references=[
                    {
                        "evidence_id": "F0001",
                        "artifact": "Dockerfile",
                        "locator": "dockerfile:CMD",
                    }
                ],
            ),
            FieldScore(
                field_id="components.root.build_strategy",
                group="extended",
                variant="common",
                expected_state="resolved",
                expected_value="dockerfile",
                actual_state="resolved",
                actual_value="dockerfile",
                correct=True,
                evidence_correct=True,
                evidence_references=[
                    {
                        "evidence_id": "F0002",
                        "artifact": "package.json",
                        "locator": "jsonpath:$.dependencies.express",
                    }
                ],
            ),
        ]

        metrics = _calculate_metrics(
            [
                CaseScore(
                    case_id="case-a",
                    visibility="contract",
                    revision="fixture-v1",
                    fields=fields,
                )
            ]
        )

        self.assertEqual(metrics.evidence_reference_accuracy, 0.5)

    def test_extra_evidence_reference_is_not_exact_evidence_match(self):
        evidence = EvidenceModel(
            facts=[
                EvidenceFact(
                    evidence_id="F0001",
                    fact_type="package_dependency",
                    artifact_ref="package.json",
                    source="package.json",
                    classification="observed_fact",
                    value={"package": "express"},
                ),
                EvidenceFact(
                    evidence_id="F0002",
                    fact_type="dockerfile_cmd",
                    artifact_ref="Dockerfile",
                    source="dockerfile_cmd",
                    classification="observed_fact",
                    value='["node", "server.js"]',
                ),
            ]
        )
        topology = ApplicationTopology(
            components=[
                ApplicationComponent(
                    component_id="root",
                    evidence_refs=["F0001", "F0002"],
                )
            ]
        )

        score = _score_field(
            ExpectedField(
                field_id="components.root.present",
                group="core",
                expected_state="resolved",
                expected_value=True,
                expected_evidence=[
                    {"artifact": "package.json", "locator": "jsonpath:$.dependencies.express"}
                ],
            ),
            topology,
            evidence,
            _evidence_reference_index(evidence),
        )

        self.assertFalse(score.evidence_correct)

    def test_secret_values_are_rejected_and_report_values_are_redacted(self):
        canary = "postgresql://user:super-secret@db/app"

        with self.assertRaisesRegex(ValueError, "classification metadata only"):
            ExpectedField(
                field_id="components.root.database_password",
                group="core",
                expected_state="resolved",
                expected_value=canary,
                expected_evidence=[
                    {"artifact": "application.yml", "locator": "yamlpath:$.password"}
                ],
            )

        self.assertNotIn("super-secret", _redact_value("token=super-secret"))

    def test_command_shaped_secret_canary_is_rejected_and_redacted(self):
        canary = "TASK36_SECRET_CANARY"

        with self.assertRaisesRegex(ValueError, "secret values"):
            ExpectedField(
                field_id="components.root.effective_runtime_command",
                group="core",
                expected_state="resolved",
                expected_value=f"uvicorn main:app --password {canary}",
                expected_evidence=[
                    {"artifact": "Dockerfile", "locator": "dockerfile:CMD"}
                ],
            )

        score = FieldScore(
            field_id="components.root.effective_runtime_command",
            group="core",
            variant="common",
            expected_state="resolved",
            expected_value="uvicorn main:app",
            actual_state="resolved",
            actual_value={
                "command": f"uvicorn main:app --api-key {canary}",
                "nested": {"API_TOKEN": canary},
            },
            correct=False,
        )

        dumped = json.dumps(score.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn(canary, dumped)
        self.assertIn("[REDACTED]", dumped)


class HumanBaselineContractTests(unittest.TestCase):
    def test_manual_and_agent_measurements_fix_total_and_hands_on_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            baseline_path = root / "human-baseline.yaml"
            corpus_path.write_text(
                yaml.safe_dump(_corpus(), sort_keys=False), encoding="utf-8"
            )
            baseline = {
                "schema_version": "repository-analysis-human-baseline/v1",
                "baseline_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial timing template.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "cases": [
                    {
                        "case_id": "case-a",
                        "measurements": [
                            {
                                "method": "manual",
                                "operator_id": "engineer-a",
                                "status": "measured",
                                "total_seconds": 1200,
                                "hands_on_seconds": 900,
                            },
                            {
                                "method": "agent",
                                "operator_id": "engineer-b",
                                "status": "measured",
                                "total_seconds": 300,
                                "hands_on_seconds": 120,
                            },
                        ],
                    }
                ],
            }
            baseline_path.write_text(
                yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8"
            )

            loaded = load_human_baseline(baseline_path, corpus_path)

            self.assertEqual(loaded.cases[0].measurements[0].hands_on_seconds, 900)

    def test_hands_on_time_cannot_exceed_total_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            baseline_path = root / "human-baseline.yaml"
            corpus_path.write_text(
                yaml.safe_dump(_corpus(), sort_keys=False), encoding="utf-8"
            )
            baseline = {
                "schema_version": "repository-analysis-human-baseline/v1",
                "baseline_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial timing template.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "cases": [
                    {
                        "case_id": "case-a",
                        "measurements": [
                            {
                                "method": "manual",
                                "operator_id": "engineer-a",
                                "status": "measured",
                                "total_seconds": 10,
                                "hands_on_seconds": 11,
                            },
                            {
                                "method": "agent",
                                "operator_id": "engineer-b",
                                "status": "pending",
                            },
                        ],
                    }
                ],
            }
            baseline_path.write_text(
                yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "hands_on_seconds"):
                load_human_baseline(baseline_path, corpus_path)

    def test_human_baseline_requires_versioned_change_history(self):
        with self.assertRaisesRegex(ValueError, "latest change history version"):
            HumanBaseline.model_validate(
                {
                    "schema_version": "repository-analysis-human-baseline/v1",
                    "baseline_version": "2",
                    "corpus_version": "1",
                    "change_history": [
                        {
                            "version": "1",
                            "reason": "Initial timing template.",
                            "affected_evaluations": ["case-a"],
                        }
                    ],
                    "cases": [
                        {
                            "case_id": "case-a",
                            "measurements": [
                                {
                                    "method": "manual",
                                    "operator_id": "engineer-a",
                                    "status": "pending",
                                },
                                {
                                    "method": "agent",
                                    "operator_id": "engineer-b",
                                    "status": "pending",
                                },
                            ],
                        }
                    ],
                }
            )


class RepositoryRegistryContractTests(unittest.TestCase):
    def test_registry_lock_rejects_unversioned_content_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "repository-registry.yaml"
            lock_path = root / "repository-registry.lock.json"
            registry = {
                "schema_version": "repository-analysis-registry/v1",
                "registry_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial repository registry.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "repositories": [
                    {
                        "case_id": "case-a",
                        "visibility": "public",
                        "stack": "node",
                        "repository_url": "https://github.com/example/repo",
                        "revision": "a" * 40,
                        "expert_truth_path": "expert-truth/case-a.yaml",
                    }
                ],
            }
            registry_path.write_text(
                yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
            )
            initialize_repository_registry_lock(registry_path, lock_path)
            verify_repository_registry_lock(registry_path, lock_path)

            registry["repositories"][0]["revision"] = "b" * 40
            registry_path.write_text(
                yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "content hash"):
                verify_repository_registry_lock(registry_path, lock_path)
            with self.assertRaisesRegex(ValueError, "new version"):
                update_repository_registry_lock(registry_path, lock_path)

    def test_human_baseline_lock_rejects_unversioned_content_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "human-baseline.yaml"
            lock_path = root / "human-baseline.lock.json"
            baseline = {
                "schema_version": "repository-analysis-human-baseline/v1",
                "baseline_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial timing template.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "cases": [
                    {
                        "case_id": "case-a",
                        "measurements": [
                            {
                                "method": "manual",
                                "operator_id": "engineer-a",
                                "status": "pending",
                            },
                            {
                                "method": "agent",
                                "operator_id": "engineer-b",
                                "status": "pending",
                            },
                        ],
                    }
                ],
            }
            baseline_path.write_text(
                yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8"
            )
            initialize_human_baseline_lock(baseline_path, lock_path)
            verify_human_baseline_lock(baseline_path, lock_path)

            baseline["cases"][0]["measurements"][0]["status"] = "measured"
            baseline["cases"][0]["measurements"][0]["total_seconds"] = 120
            baseline["cases"][0]["measurements"][0]["hands_on_seconds"] = 90
            baseline_path.write_text(
                yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "content hash"):
                verify_human_baseline_lock(baseline_path, lock_path)
            with self.assertRaisesRegex(ValueError, "new version"):
                update_human_baseline_lock(baseline_path, lock_path)

    def test_real_repository_scorecard_requires_registry_and_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus = _corpus(["case-a"])
            corpus["cases"][0]["visibility"] = "public"
            corpus["cases"][0]["revision"] = "a" * 40
            corpus["cases"][0]["repository_url"] = "https://github.com/example/repo"
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            initialize_repository_corpus_lock(corpus_path, lock_path)

            with self.assertRaisesRegex(ValueError, "repository registry is required"):
                run_repository_scorecard(
                    corpus_path=corpus_path,
                    lock_path=lock_path,
                    repository_paths={"case-a": EVALUATION_ROOT},
                    output_dir=root / "report",
                    clock=lambda: None,
                )

    def test_registry_model_requires_versioned_change_history(self):
        with self.assertRaisesRegex(ValueError, "latest change history version"):
            RepositoryRegistry.model_validate(
                {
                    "schema_version": "repository-analysis-registry/v1",
                    "registry_version": "2",
                    "corpus_version": "1",
                    "change_history": [
                        {
                            "version": "1",
                            "reason": "Initial repository registry.",
                            "affected_evaluations": ["case-a"],
                        }
                    ],
                    "repositories": [
                        {
                            "case_id": "case-a",
                            "visibility": "public",
                            "stack": "node",
                            "repository_url": "https://github.com/example/repo",
                            "revision": "a" * 40,
                            "expert_truth_path": "expert-truth/case-a.yaml",
                        }
                    ],
                }
            )

    def test_registry_and_corpus_must_match_before_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            registry_path = root / "repository-registry.yaml"
            corpus = _corpus(["case-a"])
            corpus["cases"][0]["visibility"] = "public"
            corpus["cases"][0]["revision"] = "a" * 40
            corpus["cases"][0]["repository_url"] = "https://github.com/example/repo"
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            registry = {
                "schema_version": "repository-analysis-registry/v1",
                "registry_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial repository registry.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "repositories": [
                    {
                        "case_id": "case-a",
                        "visibility": "public",
                        "stack": "node",
                        "repository_url": "https://github.com/example/repo",
                        "revision": "b" * 40,
                        "expert_truth_path": "expert-truth/case-a.yaml",
                    }
                ],
            }
            registry_path.write_text(
                yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "registry revision"):
                validate_repository_registry(
                    load_repository_registry(registry_path),
                    load_repository_corpus(corpus_path),
                )

    def test_internal_registry_revision_uses_fingerprint_not_private_value(self):
        registry = RepositoryRegistry.model_validate(
            {
                "schema_version": "repository-analysis-registry/v1",
                "registry_version": "1",
                "corpus_version": "1",
                "change_history": [
                    {
                        "version": "1",
                        "reason": "Initial repository registry.",
                        "affected_evaluations": ["case-a"],
                    }
                ],
                "repositories": [
                    {
                        "case_id": "case-a",
                        "visibility": "internal",
                        "stack": "node",
                        "repository_url_env": "CASE_A_URL",
                        "repository_path_env": "CASE_A_PATH",
                        "revision_env": "CASE_A_REVISION",
                        "revision_sha256": (
                            "sha256:"
                            "1111111111111111111111111111111111111111111111111111111111111111"
                        ),
                        "expert_truth_path_env": "CASE_A_TRUTH",
                    }
                ],
            }
        )

        dumped = registry.repositories[0].model_dump(exclude_none=True)
        self.assertNotIn("repository_url", dumped)
        self.assertNotIn("revision", dumped)


class CommittedEvaluationContractTests(unittest.TestCase):
    def test_registry_selects_two_public_and_two_internal_repositories(self):
        registry = yaml.safe_load(
            (EVALUATION_ROOT / "repository-registry.yaml").read_text(encoding="utf-8")
        )

        repositories = registry["repositories"]
        self.assertEqual(registry["schema_version"], "repository-analysis-registry/v1")
        self.assertIn("change_history", registry)
        loaded = load_repository_registry(EVALUATION_ROOT / "repository-registry.yaml")
        self.assertEqual(
            loaded,
            RepositoryRegistry.model_validate(loaded.model_dump(mode="json")),
        )
        self.assertEqual(len(repositories), 4)
        self.assertEqual(
            [item["visibility"] for item in repositories].count("public"), 2
        )
        self.assertEqual(
            [item["visibility"] for item in repositories].count("internal"), 2
        )
        for item in repositories:
            if item["visibility"] == "public":
                self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
                self.assertTrue(item["repository_url"].startswith("https://github.com/"))
            else:
                self.assertNotIn("repository_url", item)
                self.assertIn("repository_url_env", item)
                self.assertIn("revision_env", item)
                self.assertRegex(item["revision_sha256"], r"^sha256:[0-9a-f]{64}$")
                self.assertIn("expert_truth_path_env", item)

    def test_public_expert_truth_has_core_extended_variant_and_precise_evidence(self):
        registry = yaml.safe_load(
            (EVALUATION_ROOT / "repository-registry.yaml").read_text(encoding="utf-8")
        )
        public_repositories = [
            item for item in registry["repositories"] if item["visibility"] == "public"
        ]
        variants: set[str] = set()

        for repository in public_repositories:
            truth = yaml.safe_load(
                (EVALUATION_ROOT / repository["expert_truth_path"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(truth["revision"], repository["revision"])
            self.assertEqual({field["group"] for field in truth["fields"]}, {"core", "extended"})
            for field in truth["fields"]:
                variants.add(field.get("variant", "common"))
                for evidence in field["expected_evidence"]:
                    self.assertTrue(evidence["artifact"])
                    self.assertTrue(evidence["locator"])

        self.assertIn("common", variants)
        self.assertGreater(len(variants), 1)

    def test_contract_corpus_covers_normal_absence_conflict_and_coverage_gap(self):
        corpus_path = EVALUATION_ROOT / "contract-corpus.yaml"

        corpus = load_repository_corpus(corpus_path)
        verify_repository_corpus_lock(
            corpus_path, EVALUATION_ROOT / "contract-corpus.lock.json"
        )

        self.assertEqual(
            {case.scenario for case in corpus.cases},
            {"normal", "absence", "conflict", "coverage_gap"},
        )
        self.assertEqual(
            corpus,
            RepositoryCorpus.model_validate(corpus.model_dump(mode="json")),
        )
        self.assertEqual(
            {artifact for case in corpus.cases for artifact in case.artifact_types},
            {
                "dockerfile",
                "docker_compose",
                "maven",
                "gradle_groovy",
                "gradle_kotlin",
                "node_package",
                "python_package",
                "application_config",
                "kubernetes_manifest",
                "kustomize",
            },
        )
        self.assertTrue(
            (
                Path(__file__).resolve().parents[1]
                / "fixtures"
                / "repos"
                / "gradle-spring-like"
                / "build.gradle"
            ).is_file()
        )

    def test_human_baseline_template_crosses_manual_and_agent_operators(self):
        payload = yaml.safe_load(
            (EVALUATION_ROOT / "human-baseline.template.yaml").read_text(
                encoding="utf-8"
            )
        )

        baseline = HumanBaseline.model_validate(payload)

        self.assertEqual(
            baseline,
            HumanBaseline.model_validate(baseline.model_dump(mode="json")),
        )

        methods_by_operator: dict[str, set[str]] = {}
        for case in baseline.cases:
            for measurement in case.measurements:
                methods_by_operator.setdefault(measurement.operator_id, set()).add(
                    measurement.method
                )
        self.assertEqual(
            methods_by_operator,
            {
                "engineer-a": {"manual", "agent"},
                "engineer-b": {"manual", "agent"},
            },
        )


if __name__ == "__main__":
    unittest.main()
