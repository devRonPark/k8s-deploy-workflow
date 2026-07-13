from __future__ import annotations

import unittest

from k8s_agent.llm.redaction import redact_semantic_payload


class SemanticRedactionTests(unittest.TestCase):
    def test_redacts_secret_like_values_recursively_without_changing_shape(self):
        payload = {
            "seed_evidence": [
                {"value": "DATABASE_PASSWORD=changethis"},
                {"value": {"Authorization": "Bearer abc.def.ghi", "nested": ["api_key=sk-1234567890abcdef"]}},
            ],
            "safe": "uvicorn main:app --host 0.0.0.0",
        }

        redacted = redact_semantic_payload(payload)
        dumped = str(redacted)

        self.assertEqual(redacted["safe"], "uvicorn main:app --host 0.0.0.0")
        self.assertNotIn("changethis", dumped)
        self.assertNotIn("abc.def.ghi", dumped)
        self.assertNotIn("sk-1234567890abcdef", dumped)
        self.assertIn("[REDACTED]", dumped)


if __name__ == "__main__":
    unittest.main()
