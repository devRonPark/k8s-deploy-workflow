import unittest

from k8sagent.errors import AgentError
from k8sagent.procutil import ProcResult, redact_text, run_command


class ProcutilTests(unittest.TestCase):
    def test_run_echo(self):
        result = run_command(["echo", "hello"])
        self.assertIsInstance(result, ProcResult)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_stdout_redacted(self):
        result = run_command(["echo", "token=s3cr3t done"], redact=["s3cr3t"])
        self.assertNotIn("s3cr3t", result.stdout)
        self.assertIn("***", result.stdout)

    def test_stderr_redacted(self):
        result = run_command(
            ["sh", "-c", "echo bad-s3cr3t >&2; exit 1"], redact=["s3cr3t"]
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("s3cr3t", result.stderr)

    def test_timeout_raises_redacted_error(self):
        with self.assertRaises(AgentError) as ctx:
            run_command(["sh", "-c", "sleep 5"], timeout=0.2, redact=["sleep"])
        self.assertNotIn("sleep", str(ctx.exception))

    def test_missing_binary_raises(self):
        with self.assertRaises(AgentError):
            run_command(["definitely-not-a-binary-xyz"])

    def test_redact_empty_secret_ignored(self):
        self.assertEqual(redact_text("abc", ["", "b"]), "a***c")


if __name__ == "__main__":
    unittest.main()
