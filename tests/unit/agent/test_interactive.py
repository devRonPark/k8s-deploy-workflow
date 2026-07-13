import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

from k8sagent.config import AgentConfig
from k8sagent.interactive import Wizard
from k8sagent.models.report import AgentValidationReport, CheckResult
from k8sagent.session import SessionStore
from tests.unit.agent.helpers import FakeLLM, ScriptedConsole

FIXTURE = Path("tests/fixtures/repos/node-express-like")


class InteractiveTests(unittest.TestCase):
    def repo(self, tmp: str) -> Path:
        repo = Path(tmp) / "repo"
        copytree(FIXTURE, repo)
        return repo

    def wizard(self, tmp: str, console: ScriptedConsole, llm=None) -> Wizard:
        home = Path(tmp) / "home"
        return Wizard(
            config=AgentConfig(home=home, llm_enabled=llm is not None),
            store=SessionStore(home, id_factory=lambda: "s1"),
            console=console,
            llm=llm,
        )

    def test_scripted_wizard_completes(self):
        report = AgentValidationReport(
            aggregate="PASS",
            k8s_version="1.29",
            checks=[CheckResult(name="yaml_syntax", status="pass")],
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "k8sagent.interactive.run_validation", return_value=report
        ):
            console = ScriptedConsole(
                [
                    str(self.repo(tmp)),
                    "demo",
                    "registry.example.com:5000",
                    "1.0.0",
                    "approve",
                ]
            )
            code = self.wizard(tmp, console).run()
        self.assertEqual(code, 0)
        self.assertIn("PASS", console.out.getvalue())

    def test_nl_rejected_does_not_apply(self):
        llm = FakeLLM(
            {
                "nl_to_changeset": [
                    __import__("k8sagent.changeset", fromlist=["ChangeSet"]).ChangeSet(
                        origin="nl_request",
                        changes=[
                            __import__("k8sagent.changeset", fromlist=["Change"]).Change(
                                op="set", path="namespace", value="changed"
                            )
                        ],
                    )
                ]
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            console = ScriptedConsole(
                [
                    str(self.repo(tmp)),
                    "demo",
                    "registry.example.com:5000",
                    "1.0.0",
                    "nl change namespace",
                    "n",
                    "quit",
                ]
            )
            code = self.wizard(tmp, console, llm=llm).run()
        self.assertEqual(code, 0)
        self.assertIn("discarded", console.out.getvalue())

    def test_llm_none_uses_deterministic_question_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = ScriptedConsole(
                [
                    str(self.repo(tmp)),
                    "demo",
                    "registry.example.com:5000",
                    "1.0.0",
                    "quit",
                ]
            )
            self.wizard(tmp, console).run()
        self.assertIn("Which namespace", console.out.getvalue())


if __name__ == "__main__":
    unittest.main()
