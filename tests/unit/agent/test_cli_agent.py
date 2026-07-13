import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

import yaml

from k8sagent.cli import main
from k8sagent.models.report import AgentValidationReport, CheckResult

FIXTURE = Path("tests/fixtures/repos/node-express-like")


def run_cli(args, home: Path) -> tuple[int, str]:
    out = io.StringIO()
    env = {"K8S_AGENT_HOME": str(home), "K8S_AGENT_NO_LLM": "1"}
    with patch.dict(os.environ, env, clear=False), redirect_stdout(out):
        code = main(args)
    return code, out.getvalue()


class AgentCliFlowTests(unittest.TestCase):
    def copy_repo(self, root: Path) -> Path:
        repo = root / "repo"
        copytree(FIXTURE, repo)
        return repo

    def make_session(self, tmp: str) -> tuple[Path, str]:
        root = Path(tmp)
        repo = self.copy_repo(root)
        code, out = run_cli(["analyze", str(repo), "--no-llm"], root / "home")
        self.assertEqual(code, 0, out)
        return root / "home", out.strip().splitlines()[-1]

    def test_full_noninteractive_flow_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, session_id = self.make_session(tmp)
            self.assertEqual(run_cli(["select", session_id, "--all"], home)[0], 0)
            answers = Path("tests/fixtures/agent/answers-node.yaml")
            self.assertEqual(run_cli(["answer", session_id, "--answers-file", str(answers)], home)[0], 0)
            self.assertEqual(run_cli(["generate", session_id, "--approve-plan"], home)[0], 0)
            report = AgentValidationReport(
                aggregate="PASS",
                k8s_version="1.29",
                checks=[CheckResult(name="yaml_syntax", status="pass")],
            )
            with patch("k8sagent.cli.run_validation", return_value=report):
                self.assertEqual(run_cli(["validate", session_id], home)[0], 0)
            session_dir = home / "sessions" / session_id
            self.assertTrue((Path(yaml.safe_load((session_dir / "session.json").read_text())["output_dir"]) / "manifests").is_dir())

    def test_generate_without_approve_plan_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, session_id = self.make_session(tmp)
            self.assertEqual(run_cli(["select", session_id, "--all"], home)[0], 0)
            answers = Path("tests/fixtures/agent/answers-node.yaml")
            self.assertEqual(run_cli(["answer", session_id, "--answers-file", str(answers)], home)[0], 0)
            code, out = run_cli(["generate", session_id], home)
            self.assertEqual(code, 1)
            self.assertIn("approve", out)

    def test_generate_before_select_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, session_id = self.make_session(tmp)
            code, out = run_cli(["generate", session_id, "--approve-plan"], home)
            self.assertEqual(code, 1)
            self.assertIn("select", out)

    def test_answer_invalid_value_exit1(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, session_id = self.make_session(tmp)
            self.assertEqual(run_cli(["select", session_id, "--all"], home)[0], 0)
            bad = Path(tmp) / "bad.yaml"
            bad.write_text("answers:\n  components.app.service.port: abc\n", encoding="utf-8")
            self.assertEqual(run_cli(["answer", session_id, "--answers-file", str(bad)], home)[0], 1)

    def test_sessions_list_and_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, session_id = self.make_session(tmp)
            self.assertIn(session_id, run_cli(["sessions", "list"], home)[1])
            self.assertIn(session_id, run_cli(["sessions", "show", session_id], home)[1])

    def test_unknown_command_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out = run_cli(["frobnicate"], Path(tmp) / "home")
            self.assertEqual(code, 2)

    def test_analyze_local_path_prints_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = self.copy_repo(Path(tmp))
            code, out = run_cli(["analyze", str(repo)], home)
            self.assertEqual(code, 0)
            self.assertIn("session", out)


if __name__ == "__main__":
    unittest.main()
