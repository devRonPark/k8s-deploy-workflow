import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

import yaml

from k8sagent.analysis import run_agent_analysis
from k8sagent.cli import main
from k8sagent.config import AgentConfig
from k8sagent.interactive import Wizard
from k8sagent.models.report import AgentValidationReport, CheckResult
from k8sagent.session import SessionStore
from tests.unit.agent.helpers import ScriptedConsole

FIXTURE = Path("tests/fixtures/repos/node-express-like")
ANSWERS = Path("tests/fixtures/agent/answers-node.yaml")


def run_cli(args: list[str], home: Path) -> tuple[int, str]:
    out = io.StringIO()
    env = {"K8S_AGENT_HOME": str(home), "K8S_AGENT_NO_LLM": "1"}
    with patch.dict(os.environ, env, clear=False), redirect_stdout(out):
        code = main(args)
    return code, out.getvalue()


class AgentWorkflowAcceptanceTests(unittest.TestCase):
    def copy_repo(self, root: Path) -> Path:
        repo = root / "repo"
        copytree(FIXTURE, repo)
        return repo

    def analyze_session(self, root: Path) -> tuple[Path, Path, str]:
        home = root / "home"
        repo = self.copy_repo(root)
        code, out = run_cli(["analyze", str(repo), "--no-llm"], home)
        self.assertEqual(code, 0, out)
        return home, repo, out.strip().splitlines()[-1]

    def generate_session(self, home: Path, session_id: str) -> Path:
        self.assertEqual(run_cli(["select", session_id, "--all"], home)[0], 0)
        self.assertEqual(
            run_cli(["answer", session_id, "--answers-file", str(ANSWERS)], home)[0],
            0,
        )
        self.assertEqual(run_cli(["generate", session_id, "--approve-plan"], home)[0], 0)
        session_doc = yaml.safe_load((home / "sessions" / session_id / "session.json").read_text())
        return Path(session_doc["output_dir"])

    def test_noninteractive_flow_writes_deterministic_safe_manifests(self):
        report = AgentValidationReport(
            aggregate="PASS",
            k8s_version="1.29",
            checks=[CheckResult(name="yaml_syntax", status="pass")],
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "k8sagent.cli.run_validation", return_value=report
        ):
            root = Path(tmp)
            home, _repo, session_id = self.analyze_session(root)
            output_dir = self.generate_session(home, session_id)
            code, out = run_cli(["validate", session_id], home)
            self.assertEqual(code, 0, out)

            manifests = {
                path.relative_to(output_dir / "manifests").as_posix(): path.read_text(encoding="utf-8")
                for path in sorted((output_dir / "manifests").rglob("*.yaml"))
            }
            self.assertIn("namespace.yaml", manifests)
            self.assertIn("root/deployment.yaml", manifests)
            self.assertIn("root/service.yaml", manifests)
            all_text = "\n".join(manifests.values())
            self.assertIn("kind: Deployment", all_text)
            self.assertIn("registry.example.com:5000/root:1.0.0", all_text)
            self.assertNotIn("kind: Secret", all_text)
            self.assertNotIn("__UNRESOLVED__", all_text)
            self.assertTrue((output_dir / "validation" / "report.yaml").is_file())

            home2, _repo2, session_id2 = self.analyze_session(root / "second")
            output_dir2 = self.generate_session(home2, session_id2)
            manifests2 = {
                path.relative_to(output_dir2 / "manifests").as_posix(): path.read_text(encoding="utf-8")
                for path in sorted((output_dir2 / "manifests").rglob("*.yaml"))
            }
            self.assertEqual(manifests, manifests2)

    def test_agent_output_directory_is_not_reanalyzed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, repo, session_id = self.analyze_session(root)
            output_dir = self.generate_session(home, session_id)
            self.assertTrue((output_dir / "manifests").is_dir())

            bundle = run_agent_analysis(
                repo,
                url=None,
                ref=None,
                clock=lambda: datetime(2026, 7, 13, tzinfo=timezone.utc),
            )
            inventory_text = yaml.safe_dump(bundle.inventory.model_dump(mode="json"))
            self.assertNotIn("k8s-agent-output", inventory_text)

    def test_scripted_interactive_start_can_approve_and_validate(self):
        report = AgentValidationReport(
            aggregate="PASS",
            k8s_version="1.29",
            checks=[CheckResult(name="yaml_syntax", status="pass")],
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "k8sagent.interactive.run_validation", return_value=report
        ):
            root = Path(tmp)
            repo = self.copy_repo(root)
            console = ScriptedConsole(
                [
                    str(repo),
                    "demo",
                    "registry.example.com:5000",
                    "1.0.0",
                    "approve",
                ]
            )
            home = root / "home"
            wizard = Wizard(
                config=AgentConfig(home=home, llm_enabled=False),
                store=SessionStore(home, id_factory=lambda: "interactive"),
                console=console,
                llm=None,
            )
            self.assertEqual(wizard.run(), 0)
            self.assertIn("PASS", console.out.getvalue())
            self.assertTrue((repo / "k8s-agent-output" / "manifests" / "root" / "deployment.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
