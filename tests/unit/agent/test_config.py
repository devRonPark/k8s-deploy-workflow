import tempfile
import unittest
from pathlib import Path

from k8sagent.config import load_config
from k8sagent.errors import AgentError, ConfigError


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config(env={}, home_override=Path("/tmp/x"))
        self.assertEqual(cfg.k8s_version, "1.29")
        self.assertTrue(cfg.llm_enabled)
        self.assertEqual(cfg.git_token_env, "K8S_AGENT_GIT_TOKEN")
        self.assertEqual(cfg.home, Path("/tmp/x"))

    def test_precedence_cli_over_env_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("k8s_version: '1.27'\n", encoding="utf-8")
            env = {"K8S_AGENT_K8S_VERSION": "1.28"}
            self.assertEqual(load_config(env=env, home_override=home).k8s_version, "1.28")
            cfg = load_config(cli_overrides={"k8s_version": "1.30"}, env=env, home_override=home)
            self.assertEqual(cfg.k8s_version, "1.30")

    def test_file_only_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("k8s_version: '1.27'\n", encoding="utf-8")
            self.assertEqual(load_config(env={}, home_override=home).k8s_version, "1.27")

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("registry: oops\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(env={}, home_override=home)

    def test_no_llm_env(self):
        cfg = load_config(env={"K8S_AGENT_NO_LLM": "1"}, home_override=Path("/tmp/x"))
        self.assertFalse(cfg.llm_enabled)

    def test_home_from_env(self):
        cfg = load_config(env={"K8S_AGENT_HOME": "/tmp/agent-home"})
        self.assertEqual(cfg.home, Path("/tmp/agent-home"))

    def test_error_taxonomy_codes(self):
        self.assertEqual(ConfigError("x").code, "config_error")
        self.assertIsInstance(ConfigError("x"), AgentError)


if __name__ == "__main__":
    unittest.main()
