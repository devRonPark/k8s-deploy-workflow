import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from k8sagent.changeset import Change, ChangeSet
from k8sagent.corrections import explain_failure, propose_correction, run_correction_cycle
from k8sagent.models.intent import AgentKubernetesIntent, ComponentIntentSpec, set_intent_path
from k8sagent.models.report import AgentValidationReport, CheckResult
from tests.unit.agent.helpers import FakeLLM


def make_intent(namespace: str = "bad-name") -> AgentKubernetesIntent:
    intent = AgentKubernetesIntent(
        components=[ComponentIntentSpec(component_id="api", role="application")]
    )
    return set_intent_path(intent, "namespace", namespace, source="user_decision")


def fail_report(detail: str) -> AgentValidationReport:
    return AgentValidationReport(
        aggregate="FAIL",
        k8s_version="1.29",
        checks=[
            CheckResult(name="yaml_syntax", status="pass"),
            CheckResult(name="intent_invariants", status="fail", detail=detail),
        ],
    )


class CorrectionTests(unittest.TestCase):
    def test_rule_table_normalizes_rfc1123_name(self):
        cs, source = propose_correction(
            fail_report("namespace Bad_Name violates RFC 1123"),
            make_intent("fallback"),
            None,
        )
        self.assertEqual(source, "rule_table")
        self.assertEqual(cs.changes[0].path, "namespace")
        self.assertEqual(cs.changes[0].value, "bad-name")

    def test_llm_used_when_no_rule_matches(self):
        llm = FakeLLM(
            {
                "propose_correction": [
                    ChangeSet(
                        origin="correction",
                        changes=[Change(op="set", path="namespace", value="prod")],
                    )
                ]
            }
        )
        cs, source = propose_correction(fail_report("something else"), make_intent(), llm)
        self.assertEqual(source, "llm")
        self.assertEqual(cs.changes[0].value, "prod")

    def test_invalid_llm_changeset_ignored(self):
        llm = FakeLLM(
            {
                "propose_correction": [
                    ChangeSet(
                        origin="correction",
                        changes=[Change(op="set", path="bad.path", value="x")],
                    )
                ]
            }
        )
        cs, source = propose_correction(fail_report("something else"), make_intent(), llm)
        self.assertIsNone(cs)
        self.assertEqual(source, "none")

    def test_decline_approval_does_not_apply_or_revalidate(self):
        calls = []

        def fake_validate(*args, **kwargs):
            calls.append(args)
            return fail_report("after")

        with tempfile.TemporaryDirectory() as tmp, patch(
            "k8sagent.corrections.run_validation", side_effect=fake_validate
        ):
            intent, report, applied = run_correction_cycle(
                None,
                make_intent(),
                Path(tmp) / "manifests",
                report=fail_report("namespace Bad_Name violates RFC 1123"),
                llm=None,
                approve=lambda text: False,
                k8s_version="1.29",
                kubeconform_path=None,
                output_dir=Path(tmp),
                commit_sha="abc",
            )
        self.assertFalse(applied)
        self.assertEqual(intent.namespace.value, "bad-name")
        self.assertEqual(report.aggregate, "FAIL")
        self.assertEqual(calls, [])

    def test_approval_applies_once_and_revalidates_once(self):
        calls = []
        new_report = AgentValidationReport(
            aggregate="PASS",
            k8s_version="1.29",
            checks=[CheckResult(name="yaml_syntax", status="pass")],
        )

        def fake_validate(*args, **kwargs):
            calls.append(args)
            return new_report

        with tempfile.TemporaryDirectory() as tmp, patch(
            "k8sagent.corrections.run_validation", side_effect=fake_validate
        ):
            intent, report, applied = run_correction_cycle(
                None,
                make_intent(),
                Path(tmp) / "manifests",
                report=fail_report("namespace Bad_Name violates RFC 1123"),
                llm=None,
                approve=lambda text: True,
                k8s_version="1.29",
                kubeconform_path=None,
                output_dir=Path(tmp),
                commit_sha="abc",
            )
        self.assertTrue(applied)
        self.assertEqual(intent.namespace.value, "bad-name")
        self.assertEqual(report.aggregate, "PASS")
        self.assertEqual(len(calls), 1)

    def test_explain_failure_without_llm_uses_details(self):
        self.assertIn("boom", explain_failure(fail_report("boom"), None))


if __name__ == "__main__":
    unittest.main()
