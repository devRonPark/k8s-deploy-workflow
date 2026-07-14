from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.evaluation.repository_analysis import (
    initialize_repository_corpus_lock,
    run_repository_scorecard,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
EVALUATION_FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "evaluation"
    / "repository_analysis"
)
FIXED_TIME = datetime(2026, 7, 14, 3, 0, 0, tzinfo=timezone.utc)


class RepositoryAnalysisScorecardAcceptanceTests(unittest.TestCase):
    def test_immutable_revision_must_match_checked_out_repository(self):
        corpus = {
            "schema_version": "repository-analysis-corpus/v1",
            "corpus_version": "1",
            "change_history": [
                {
                    "version": "1",
                    "reason": "Verify immutable source revisions.",
                    "affected_cases": ["wrong-revision"],
                }
            ],
            "cases": [
                {
                    "case_id": "wrong-revision",
                    "visibility": "contract",
                    "revision": "0" * 40,
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
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus_path.write_text(
                yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8"
            )
            initialize_repository_corpus_lock(corpus_path, lock_path)

            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                run_repository_scorecard(
                    corpus_path=corpus_path,
                    lock_path=lock_path,
                    repository_paths={"wrong-revision": FIXTURES / "node-express-like"},
                    output_dir=root / "report",
                    clock=lambda: FIXED_TIME,
                )

    def test_locked_corpus_runs_real_analysis_and_reports_current_baseline(self):
        corpus = {
            "schema_version": "repository-analysis-corpus/v1",
            "corpus_version": "2026-07-14.1",
            "change_history": [
                {
                    "version": "2026-07-14.1",
                    "reason": "Lock the initial Repository analysis scorecard contract.",
                    "affected_cases": ["node-express-contract"],
                }
            ],
            "cases": [
                {
                    "case_id": "node-express-contract",
                    "visibility": "contract",
                    "revision": "fixture-v1",
                    "fields": [
                        {
                            "field_id": "components.root.present",
                            "group": "core",
                            "expected_state": "resolved",
                            "expected_value": True,
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "jsonpath:$.dependencies.express",
                                }
                            ],
                        },
                        {
                            "field_id": "components.root.deployment_role",
                            "group": "core",
                            "expected_state": "resolved",
                            "expected_value": "application",
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "jsonpath:$.dependencies.express",
                                }
                            ],
                        },
                        {
                            "field_id": "components.root.workload_role",
                            "group": "core",
                            "expected_state": "resolved",
                            "expected_value": "api",
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "jsonpath:$.dependencies.express",
                                }
                            ],
                        },
                        {
                            "field_id": "components.root.effective_runtime_command",
                            "group": "core",
                            "expected_state": "resolved",
                            "expected_value": '["node", "server.js"]',
                            "expected_evidence": [
                                {"artifact": "Dockerfile", "locator": "jsonpath:$.CMD"}
                            ],
                        },
                        {
                            "field_id": "components.root.runtime_port",
                            "group": "core",
                            "expected_state": "resolved",
                            "expected_value": 3000,
                            "expected_evidence": [
                                {"artifact": "Dockerfile", "locator": "lines:5-5"}
                            ],
                        },
                        {
                            "field_id": "components.root.secret_classification",
                            "group": "core",
                            "expected_state": "not_applicable",
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "full-document:no-secret-inputs",
                                }
                            ],
                        },
                        {
                            "field_id": "components.root.build_strategy",
                            "group": "extended",
                            "expected_state": "resolved",
                            "expected_value": "dockerfile",
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "jsonpath:$.dependencies.express",
                                }
                            ],
                        },
                        {
                            "field_id": "package_dependencies.root.express",
                            "group": "extended",
                            "expected_state": "resolved",
                            "expected_value": True,
                            "expected_evidence": [
                                {
                                    "artifact": "package.json",
                                    "locator": "jsonpath:$.dependencies.express",
                                }
                            ],
                        },
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus_path = root / "corpus.yaml"
            lock_path = root / "corpus.lock.json"
            corpus_path.write_text(yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8")
            initialize_repository_corpus_lock(corpus_path, lock_path)

            report = run_repository_scorecard(
                corpus_path=corpus_path,
                lock_path=lock_path,
                repository_paths={"node-express-contract": FIXTURES / "node-express-like"},
                output_dir=root / "report",
                clock=lambda: FIXED_TIME,
            )

            self.assertEqual(report.corpus_version, "2026-07-14.1")
            self.assertEqual(report.case_count, 1)
            self.assertEqual(report.metrics.core_field_accountability_rate, 4 / 6)
            self.assertEqual(report.metrics.core_resolution_rate, 4 / 6)
            self.assertEqual(report.metrics.extended_resolution_rate, 1 / 2)
            self.assertEqual(report.metrics.auto_confirmed_accuracy, 1.0)
            self.assertEqual(report.metrics.evidence_reference_accuracy, 0.0)
            self.assertEqual(report.metrics.ungrounded_auto_confirmed_count, 5)
            self.assertFalse(report.quality_gate_passed)
            self.assertEqual(report.cases[0].fields[2].actual_state, "missing")
            self.assertTrue((root / "report" / "repository-analysis-scorecard.json").is_file())
            markdown = (
                root / "report" / "repository-analysis-scorecard.md"
            ).read_text(encoding="utf-8")

        self.assertIn("node-express-contract", markdown)
        self.assertIn("core_resolution_rate", markdown)

    def test_committed_contract_corpus_runs_through_application_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_repository_scorecard(
                corpus_path=EVALUATION_FIXTURES / "contract-corpus.yaml",
                lock_path=EVALUATION_FIXTURES / "contract-corpus.lock.json",
                repository_paths={
                    "node-normal": FIXTURES / "node-express-like",
                    "node-secret-absence": FIXTURES / "no-dockerfile-node",
                    "runtime-port-conflict": FIXTURES / "port-conflict-node",
                    "gradle-coverage-gap": FIXTURES / "gradle-spring-like",
                },
                output_dir=Path(tmp),
                clock=lambda: FIXED_TIME,
            )

        self.assertEqual(report.case_count, 4)
        self.assertEqual(report.metrics.core_field_accountability_rate, 3 / 7)
        self.assertEqual(report.metrics.core_resolution_rate, 3 / 5)
        self.assertEqual(report.metrics.extended_resolution_rate, 1 / 3)
        self.assertFalse(report.quality_gate_passed)
        conflict = next(case for case in report.cases if case.case_id == "runtime-port-conflict")
        self.assertEqual(conflict.fields[0].actual_state, "missing")


if __name__ == "__main__":
    unittest.main()
