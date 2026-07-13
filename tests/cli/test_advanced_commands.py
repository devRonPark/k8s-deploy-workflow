from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.cli.test_prepare_arguments import run_agent
from tests.unit.k8s_agent.test_stage_commands import _renderable_profile


class AdvancedCommandCliTests(unittest.TestCase):
    def test_analyze_and_plan_stage_commands_write_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            analyzed = run_agent(
                "analyze",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )
            text = analyzed.stdout + analyzed.stderr
            self.assertEqual(analyzed.returncode, 0, text)
            self.assertIn("analyze run_id=", text)
            run_id = analyzed.stdout.split("run_id=", 1)[1].split()[0]
            run_root = Path(tmp) / "runs" / run_id
            self.assertTrue((run_root / "analysis" / "04-application-topology.yaml").is_file())
            self.assertFalse((run_root / "analysis" / "05-kubernetes-intent.yaml").exists())

            planned = run_agent("plan", run_id, extra_env={"K8S_AGENT_HOME": tmp})

            text = planned.stdout + planned.stderr
            self.assertEqual(planned.returncode, 0, text)
            self.assertIn("plan run_id=", text)
            self.assertTrue((run_root / "analysis" / "05-kubernetes-intent.yaml").is_file())
            self.assertTrue((run_root / "agent" / "questions.yaml").is_file())

    def test_stage_preconditions_return_stable_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            analyzed = run_agent(
                "analyze",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )
            self.assertIn("analyze run_id=", analyzed.stdout + analyzed.stderr)
            run_id = analyzed.stdout.split("run_id=", 1)[1].split()[0]

            generate = run_agent("generate", run_id, extra_env={"K8S_AGENT_HOME": tmp})
            validate = run_agent("validate", run_id, extra_env={"K8S_AGENT_HOME": tmp})

            self.assertEqual(generate.returncode, 3, generate.stdout + generate.stderr)
            self.assertIn("STAGE-201", generate.stdout + generate.stderr)
            self.assertEqual(validate.returncode, 3, validate.stdout + validate.stderr)
            self.assertIn("STAGE-301", validate.stdout + validate.stderr)

    def test_generate_and_validate_stage_commands_use_existing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            analyzed = run_agent(
                "analyze",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )
            self.assertIn("analyze run_id=", analyzed.stdout + analyzed.stderr)
            run_id = analyzed.stdout.split("run_id=", 1)[1].split()[0]
            run_root = Path(tmp) / "runs" / run_id
            profile_dir = run_root / "profile"
            profile_dir.mkdir(parents=True)
            (profile_dir / "deployment-profile.yaml").write_text(
                "deployment_profile:\n" + _indent_yaml(_renderable_profile().model_dump(mode="json")),
                encoding="utf-8",
            )

            generated = run_agent("generate", run_id, extra_env={"K8S_AGENT_HOME": tmp})
            validated = run_agent("validate", run_id, extra_env={"K8S_AGENT_HOME": tmp})

            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertIn("generate run_id=", generated.stdout)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            self.assertIn("validate run_id=", validated.stdout)
            self.assertTrue((run_root / "generated" / "manifest-bundle.yaml").is_file())
            self.assertTrue((run_root / "validation" / "13-validation-report.yaml").is_file())


def _indent_yaml(payload: dict) -> str:
    import yaml

    return "".join(f"  {line}" if line.strip() else line for line in yaml.safe_dump(payload, sort_keys=False).splitlines(True))


if __name__ == "__main__":
    unittest.main()
