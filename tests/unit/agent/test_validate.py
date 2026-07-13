import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from k8sagent.models.intent import AgentKubernetesIntent
from k8sagent.models.report import AgentValidationReport, CheckResult
from k8sagent.procutil import ProcResult
from k8sagent.validate import aggregate_checks, run_validation, write_report
from tests.unit.agent.helpers import FakeRunner


def write_yaml(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def manifests(root: Path, *, mismatch: bool = False) -> Path:
    manifest_dir = root / "manifests"
    labels = {"app.kubernetes.io/name": "web"}
    write_yaml(
        manifest_dir / "web" / "deployment.yaml",
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "web", "namespace": "demo"},
            "spec": {
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "web",
                                "image": "registry.example.com/web:1",
                                "ports": [{"containerPort": 3000}],
                            }
                        ]
                    },
                },
            },
        },
    )
    write_yaml(
        manifest_dir / "web" / "service.yaml",
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "web-service", "namespace": "demo"},
            "spec": {
                "selector": labels,
                "ports": [{"port": 3000, "targetPort": 3001 if mismatch else 3000}],
            },
        },
    )
    return manifest_dir


class ValidateTests(unittest.TestCase):
    def test_all_checks_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([ProcResult(0, "ok", ""), ProcResult(0, "ok", "")])
            with patch("k8sagent.validate.shutil.which", side_effect=lambda name: f"/bin/{name}"):
                report = run_validation(
                    manifests(Path(tmp)),
                    AgentKubernetesIntent(),
                    k8s_version="1.29",
                    kubeconform_path=Path("/bin/kubeconform"),
                    runner=runner,
                    project_root=Path(tmp),
                )
        self.assertEqual(report.aggregate, "PASS")

    def test_missing_kubeconform_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([ProcResult(0, "ok", "")])
            with patch("k8sagent.validate.resolve_kubeconform", return_value=None), patch(
                "k8sagent.validate.shutil.which", side_effect=lambda name: "/bin/kubectl" if name == "kubectl" else None
            ):
                report = run_validation(
                    manifests(Path(tmp)),
                    AgentKubernetesIntent(),
                    k8s_version="1.29",
                    kubeconform_path=None,
                    runner=runner,
                    project_root=Path(tmp),
                )
        self.assertEqual(report.aggregate, "PARTIAL")
        self.assertEqual(report.checks[2].skipped_reason, "tool_not_found")

    def test_kubeconform_failure_still_runs_kubectl(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([ProcResult(1, "", "schema bad"), ProcResult(0, "ok", "")])
            with patch("k8sagent.validate.shutil.which", side_effect=lambda name: f"/bin/{name}"):
                report = run_validation(
                    manifests(Path(tmp)),
                    AgentKubernetesIntent(),
                    k8s_version="1.29",
                    kubeconform_path=Path("/bin/kubeconform"),
                    runner=runner,
                    project_root=Path(tmp),
                )
        self.assertEqual(report.aggregate, "FAIL")
        self.assertEqual(len(runner.calls), 2)

    def test_yaml_error_skips_later_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp) / "manifests"
            (manifest_dir / "bad.yaml").parent.mkdir(parents=True)
            (manifest_dir / "bad.yaml").write_text("apiVersion: [", encoding="utf-8")
            report = run_validation(
                manifest_dir,
                AgentKubernetesIntent(),
                k8s_version="1.29",
                kubeconform_path=None,
                runner=FakeRunner(),
                project_root=Path(tmp),
            )
        self.assertEqual(report.aggregate, "FAIL")
        self.assertEqual([check.skipped_reason for check in report.checks[1:]], ["prior_check_failed"] * 3)

    def test_invariant_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_validation(
                manifests(Path(tmp), mismatch=True),
                AgentKubernetesIntent(),
                k8s_version="1.29",
                kubeconform_path=None,
                runner=FakeRunner(),
                project_root=Path(tmp),
            )
        self.assertEqual(report.aggregate, "FAIL")
        self.assertIn("targetPort", report.checks[1].detail)

    def test_version_normalized_for_kubeconform(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([ProcResult(0, "ok", ""), ProcResult(0, "ok", "")])
            with patch("k8sagent.validate.shutil.which", side_effect=lambda name: f"/bin/{name}"):
                run_validation(
                    manifests(Path(tmp)),
                    AgentKubernetesIntent(),
                    k8s_version="1.29",
                    kubeconform_path=Path("/bin/kubeconform"),
                    runner=runner,
                    project_root=Path(tmp),
                )
        self.assertIn("1.29.0", runner.calls[0]["argv"])

    def test_report_roundtrip(self):
        report = AgentValidationReport(
            aggregate="PARTIAL",
            k8s_version="1.29",
            checks=[CheckResult(name="kubeconform", status="skipped", skipped_reason="tool_not_found")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(report, Path(tmp))
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))["validation_report"]
        self.assertEqual(AgentValidationReport.model_validate(loaded), report)

    def test_aggregate_checks(self):
        self.assertEqual(aggregate_checks([CheckResult(name="yaml_syntax", status="pass")]), "PASS")
        self.assertEqual(aggregate_checks([CheckResult(name="yaml_syntax", status="fail")]), "FAIL")
        self.assertEqual(
            aggregate_checks(
                [CheckResult(name="kubeconform", status="skipped", skipped_reason="tool_not_found")]
            ),
            "PARTIAL",
        )


if __name__ == "__main__":
    unittest.main()
