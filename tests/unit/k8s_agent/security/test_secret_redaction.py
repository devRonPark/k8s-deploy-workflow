from __future__ import annotations

import unittest

from k8s_agent.llm.redaction import Redactor, redact_semantic_payload


class SecretRedactionSecurityTests(unittest.TestCase):
    def test_common_redactor_removes_git_url_userinfo_and_secret_assignments(self):
        canary = "task19-token-canary"
        redactor = Redactor()

        value = redactor.redact_value(
            {
                "repo": f"https://oauth2:{canary}@github.com/example/app.git",
                "args": ["--password=" + canary, "Bearer " + canary],
                "safe": "uvicorn main:app --host 0.0.0.0",
            }
        )
        dumped = repr(value)

        self.assertEqual(value["safe"], "uvicorn main:app --host 0.0.0.0")
        self.assertIn("https://github.com/example/app.git", dumped)
        self.assertNotIn(canary, dumped)
        self.assertIn("[REDACTED]", dumped)

    def test_semantic_payload_redaction_uses_common_redactor(self):
        canary = "task19-semantic-canary"

        redacted = redact_semantic_payload({"url": f"https://user:{canary}@github.com/org/repo.git"})

        self.assertNotIn(canary, repr(redacted))


if __name__ == "__main__":
    unittest.main()
