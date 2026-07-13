import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from preanalyzer.models.semantic import SemanticCandidate, SemanticResolution, SemanticResolutionStatus
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction
from preanalyzer.pipeline import run_analysis


FIXED = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
PROFILE = Path("tests/fixtures/profiles/dev-profile.yaml")
INVALID_MANIFEST_PORT_MARKERS = ("number: None", 'number: "None"', "__UNRESOLVED__")


def clock():
    return FIXED


def _validation_holds(output_dir: Path) -> list[dict]:
    report = yaml.safe_load((output_dir / "13-validation-report.yaml").read_text(encoding="utf-8"))
    return report["validation_report"].get("generation_holds", [])


def _assert_generated_manifests_do_not_contain_invalid_port_markers(test_case: unittest.TestCase, output_dir: Path) -> None:
    for path in (output_dir / "12-generated-manifests").rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for marker in INVALID_MANIFEST_PORT_MARKERS:
            test_case.assertNotIn(marker, text, str(path))


class _ResolveShellEntrypoint:
    def __init__(self) -> None:
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return ToolCallAction(
                tool_name="inspect_entrypoint_script",
                arguments={"path": "entrypoint.sh"},
            )
        evidence_ref = context.collected_evidence[0]["evidence_id"]
        return ResolutionAction(
            resolution=SemanticResolution(
                task_id=context.task_id,
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[
                    SemanticCandidate(
                        candidate_id="SC-1",
                        component_id=context.component_id,
                        target_field=context.target_field,
                        value={"command": "uvicorn main:app --host 0.0.0.0 --port 8000"},
                        classification="llm_semantic_inference",
                        confidence="medium",
                        evidence_refs=[evidence_ref],
                    )
                ],
                recommended_candidate_id="SC-1",
                tool_trace_refs=[evidence_ref],
            )
        )


class ShellEntrypointTests(unittest.TestCase):
    def test_shell_entrypoint_agent_resolves_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            run_analysis(
                Path("tests/fixtures/repos/fastapi-shell-entrypoint"),
                output_dir,
                url=None,
                ref=None,
                clock=clock,
                semantic_mode="fake",
                semantic_decision_provider=_ResolveShellEntrypoint(),
                profile_path=PROFILE,
            )
            intent = yaml.safe_load((output_dir / "09-kubernetes-intent.yaml").read_text())

        backend = next(
            component
            for component in intent["kubernetes_intent"]["components"]
            if component["component_id"] == "backend"
        )
        self.assertEqual(
            backend["workload"]["command"]["value"],
            "uvicorn main:app --host 0.0.0.0 --port 8000",
        )
        self.assertEqual(backend["workload"]["command"]["source"], "llm_semantic_inference")


class PortConflictTests(unittest.TestCase):
    def test_conflicting_ports_route_question_and_no_port_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            run_analysis(
                Path("tests/fixtures/repos/port-conflict-node"),
                output_dir,
                url=None,
                ref=None,
                clock=clock,
                semantic_mode="disabled",
                profile_path=PROFILE,
            )
            questions = yaml.safe_load((output_dir / "10-unresolved-questions.yaml").read_text())
            runtime = yaml.safe_load((output_dir / "07-runtime-model.yaml").read_text())
            holds = _validation_holds(output_dir)
            _assert_generated_manifests_do_not_contain_invalid_port_markers(self, output_dir)

        port_questions = [
            question
            for question in questions["unresolved_questions"]["questions"]
            if question["answer_type"] == "port"
        ]
        self.assertEqual(len(port_questions), 1)
        self.assertEqual(sorted(port_questions[0]["candidates"]), ["8080", "8081"])
        web = next(entry for entry in runtime["runtime_model"]["runtimes"] if entry["component_id"] == "web")
        self.assertIsNone(web["port"])
        ingress_holds = [
            hold
            for hold in holds
            if hold["component_id"] == "web"
            and hold["resource"]["kind"] == "Ingress"
            and hold["reason"]["code"] == "unresolved_service_port"
        ]
        self.assertEqual(len(ingress_holds), 1)
        self.assertEqual(ingress_holds[0]["display_status"], "생성 보류")
        self.assertEqual(ingress_holds[0]["resolution"]["status"], "unresolved")
        self.assertEqual(ingress_holds[0]["resolution"]["question_id"], port_questions[0]["id"])
        self.assertEqual(
            sorted(str(candidate["value"]) for candidate in ingress_holds[0]["reason"]["candidates"]),
            ["8080", "8081"],
        )

class DemoSpectrumTests(unittest.TestCase):
    def _run(self, repo: str, **kwargs) -> Path:
        output_dir = Path(tempfile.mkdtemp())
        run_analysis(Path(repo), output_dir, url=None, ref=None, clock=clock, **kwargs)
        return output_dir

    def test_node_express_completes_manifests(self):
        output_dir = self._run(
            "tests/fixtures/repos/node-express-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )

        manifests = list((output_dir / "12-generated-manifests").rglob("*.yaml"))
        self.assertTrue(any(path.name == "deployment.yaml" for path in manifests))

    def test_fastapi_multi_component_db_is_dependency(self):
        output_dir = self._run(
            "tests/fixtures/repos/fastapi-fullstack-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )
        intent = yaml.safe_load((output_dir / "09-kubernetes-intent.yaml").read_text())

        db = next(
            component
            for component in intent["kubernetes_intent"]["components"]
            if component["component_id"] == "db"
        )
        self.assertIsNone(db["workload"])

    def test_jpetstore_no_dockerfile_defers_and_flags_build(self):
        output_dir = self._run("tests/fixtures/repos/jpetstore-like", semantic_mode="disabled")

        rules_text = (output_dir / "03-rule-inference.yaml").read_text()
        self.assertIn("dockerfile_needed", rules_text)
        self.assertFalse(
            any(path.name == "deployment.yaml" for path in (output_dir / "12-generated-manifests").rglob("*.yaml"))
        )

    def test_jpetstore_ingress_without_service_port_is_held(self):
        output_dir = self._run(
            "tests/fixtures/repos/jpetstore-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )

        ingress_holds = [
            hold
            for hold in _validation_holds(output_dir)
            if hold["component_id"] == "root"
            and hold["resource"]["kind"] == "Ingress"
            and hold["reason"]["code"] == "unresolved_service_port"
        ]
        self.assertEqual(len(ingress_holds), 1)
        self.assertEqual(ingress_holds[0]["display_status"], "생성 보류")
        self.assertEqual(ingress_holds[0]["resolution"]["status"], "unresolved")
        self.assertIsNotNone(ingress_holds[0]["resolution"]["profile_field"])
        _assert_generated_manifests_do_not_contain_invalid_port_markers(self, output_dir)

    def test_no_secret_value_leaks_anywhere(self):
        output_dir = self._run(
            "tests/fixtures/repos/fastapi-fullstack-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )

        for path in output_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    "changethis",
                    path.read_text(encoding="utf-8", errors="ignore"),
                    str(path),
                )

    def test_determinism_full_tree(self):
        first = self._run(
            "tests/fixtures/repos/node-express-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )
        second = self._run(
            "tests/fixtures/repos/node-express-like",
            semantic_mode="disabled",
            profile_path=PROFILE,
        )

        names = [path.name for path in first.glob("0*.yaml")]
        for name in names:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
