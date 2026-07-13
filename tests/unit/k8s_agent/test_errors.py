from __future__ import annotations

import unittest

from k8s_agent.errors import AgentError, format_agent_error


class AgentErrorTests(unittest.TestCase):
    def test_formats_error_with_code_message_resolution_and_context(self):
        error = AgentError(
            code="CLI-101",
            exit_code=2,
            message="prepare requires an explicit source.",
            resolution="Pass --repo-url or --local-path.",
            context={"command": "prepare", "example": "k8s-agent prepare --local-path . --target development"},
        )

        text = format_agent_error(error)

        self.assertIn("[CLI-101]", text)
        self.assertIn("prepare requires an explicit source.", text)
        self.assertIn("Resolution: Pass --repo-url or --local-path.", text)
        self.assertIn("command: prepare", text)
        self.assertIn("example: k8s-agent prepare --local-path . --target development", text)

    def test_agent_error_requires_stable_code_exit_message_and_resolution(self):
        with self.assertRaises(ValueError):
            AgentError(code="", exit_code=2, message="message", resolution="fix")

        with self.assertRaises(ValueError):
            AgentError(code="CLI-101", exit_code=0, message="message", resolution="fix")

        with self.assertRaises(ValueError):
            AgentError(code="CLI-101", exit_code=2, message="", resolution="fix")

        with self.assertRaises(ValueError):
            AgentError(code="CLI-101", exit_code=2, message="message", resolution="")

    def test_agent_error_can_propagate_with_traceback_metadata(self):
        try:
            raise AgentError(code="RUN-201", exit_code=8, message="bad transition", resolution="resume")
        except AgentError as exc:
            self.assertIsNotNone(exc.__traceback__)
            exc.__traceback__ = exc.__traceback__


if __name__ == "__main__":
    unittest.main()
