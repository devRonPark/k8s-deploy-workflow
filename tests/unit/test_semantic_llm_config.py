from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from preanalyzer.semantic.llm_config import (
    SemanticLLMConfigError,
    load_dotenv_values,
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

    def test_loads_dotenv_values_without_printing_or_requiring_shell_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "# local secrets stay outside git",
                        "SEMANTIC_LLM_BASE_URL=https://api.upstage.ai/v1",
                        "SEMANTIC_LLM_MODEL=solar-pro3",
                        "SEMANTIC_LLM_API_KEY='local-secret-key'",
                        'SEMANTIC_LLM_TIMEOUT_SECONDS="15"',
                    ]
                ),
                encoding="utf-8",
            )

            values = load_dotenv_values(env_path)
            settings = load_semantic_llm_settings(values)

        self.assertEqual(settings.base_url, "https://api.upstage.ai/v1")
        self.assertEqual(settings.model, "solar-pro3")
        self.assertEqual(settings.api_key, "local-secret-key")
        self.assertEqual(settings.timeout_seconds, 15.0)

    def test_dotenv_loader_rejects_malformed_lines_without_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("SEMANTIC_LLM_API_KEY local-secret-key\n", encoding="utf-8")

            with self.assertRaises(SemanticLLMConfigError) as raised:
                load_dotenv_values(env_path)

        self.assertIn("invalid .env line", str(raised.exception))
        self.assertNotIn("local-secret-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
