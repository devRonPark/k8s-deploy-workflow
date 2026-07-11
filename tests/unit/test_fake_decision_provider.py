import unittest

from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction
from preanalyzer.semantic.fake_provider import ScriptedFakeDecisionProvider

from tests.unit.test_semantic_agent_models import resolution


class FakeDecisionProviderTests(unittest.TestCase):
    def test_actions_are_returned_in_order(self):
        actions = [
            ToolCallAction(tool_name="read_source_range", arguments={"path": "app.py", "start_line": 1, "end_line": 1}),
            ResolutionAction(resolution=resolution()),
        ]
        provider = ScriptedFakeDecisionProvider(actions)

        self.assertEqual(provider.decide(None), actions[0])
        self.assertEqual(provider.decide(None), actions[1])
        self.assertEqual(provider.call_count, 2)

    def test_exhausted_script_raises_provider_error(self):
        provider = ScriptedFakeDecisionProvider([])

        with self.assertRaises(RuntimeError):
            provider.decide(None)

    def test_fake_provider_does_not_execute_tools(self):
        action = ToolCallAction(tool_name="read_source_range", arguments={"path": "app.py", "start_line": 1, "end_line": 1})
        provider = ScriptedFakeDecisionProvider([action])

        self.assertEqual(provider.decide(None), action)
        self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
