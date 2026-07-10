from __future__ import annotations

import unittest

from preanalyzer.semantic.llm_config import (
    SemanticLLMConfigError,
    load_semantic_llm_settings,
)


class SemanticLLMConfigTests(unittest.TestCase):
    def test_loads_all_semantic_llm_settings(self):
        settings = load_semantic_llm_settings(
            {
                "SEMANTIC_LLM_BASE_URL": "https://llm.example.test/v1",
                "SEMANTIC_LLM_MODEL": "local-model",
                "SEMANTIC_LLM_API_KEY": "secret-key",
                "SEMANTIC_LLM_TIMEOUT_SECONDS": "12.5",
            }
        )

        self.assertEqual(settings.base_url, "https://llm.example.test/v1")
        self.assertEqual(settings.model, "local-model")
        self.assertEqual(settings.api_key, "secret-key")
        self.assertEqual(settings.timeout_seconds, 12.5)

        with self.assertRaises(Exception):
            settings.model = "other"

    def test_timeout_defaults_when_omitted(self):
        settings = load_semantic_llm_settings(
            {
                "SEMANTIC_LLM_BASE_URL": "https://llm.example.test/v1",
                "SEMANTIC_LLM_MODEL": "local-model",
                "SEMANTIC_LLM_API_KEY": "secret-key",
            }
        )

        self.assertEqual(settings.timeout_seconds, 30.0)

    def test_missing_required_value_raises_sanitized_error(self):
        with self.assertRaises(SemanticLLMConfigError) as raised:
            load_semantic_llm_settings(
                {
                    "SEMANTIC_LLM_BASE_URL": "https://llm.example.test/v1",
                    "SEMANTIC_LLM_MODEL": "local-model",
                }
            )

        message = str(raised.exception)
        self.assertIn("SEMANTIC_LLM_API_KEY", message)
        self.assertNotIn("secret-key", message)

    def test_invalid_timeout_raises_sanitized_error(self):
        with self.assertRaises(SemanticLLMConfigError) as raised:
            load_semantic_llm_settings(
                {
                    "SEMANTIC_LLM_BASE_URL": "https://llm.example.test/v1",
                    "SEMANTIC_LLM_MODEL": "local-model",
                    "SEMANTIC_LLM_API_KEY": "secret-key",
                    "SEMANTIC_LLM_TIMEOUT_SECONDS": "not-a-number",
                }
            )

        message = str(raised.exception)
        self.assertIn("SEMANTIC_LLM_TIMEOUT_SECONDS", message)
        self.assertNotIn("secret-key", message)


if __name__ == "__main__":
    unittest.main()
