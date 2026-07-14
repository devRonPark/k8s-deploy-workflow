from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.evaluation.repository_analysis import (
    HumanBaseline,
    initialize_repository_corpus_lock,
    load_repository_corpus,
    load_human_baseline,
    update_repository_corpus_lock,
    verify_repository_corpus_lock,
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
    def test_changed_truth_requires_new_version_reason_and_affected_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus = _corpus()
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            initialize_repository_corpus_lock(corpus_path, lock_path)

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
                "corpus_version": "1",
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
                "corpus_version": "1",
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


class CommittedEvaluationContractTests(unittest.TestCase):
    def test_registry_selects_two_public_and_two_internal_repositories(self):
        registry = yaml.safe_load(
            (EVALUATION_ROOT / "repository-registry.yaml").read_text(encoding="utf-8")
        )

        repositories = registry["repositories"]
        self.assertEqual(registry["schema_version"], "repository-analysis-registry/v1")
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
