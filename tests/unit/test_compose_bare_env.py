from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.env_safety import HOST_ENVIRONMENT, build_env_fact
from preanalyzer.analyzer.parsers.compose import parse


def _service(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "docker-compose.yml"
        path.write_text(text, encoding="utf-8")
        return parse(path).service("api")


class BareEnvironmentKeyTests(unittest.TestCase):
    def test_bare_list_key_is_host_environment(self):
        service = _service("services:\n  api:\n    image: api\n    environment:\n      - DEBUG\n")
        self.assertIs(service.environment["DEBUG"], HOST_ENVIRONMENT)

    def test_empty_list_assignment_is_empty_string(self):
        service = _service("services:\n  api:\n    image: api\n    environment:\n      - DEBUG=\n")
        self.assertEqual(service.environment["DEBUG"], "")

    def test_map_null_is_none(self):
        service = _service("services:\n  api:\n    image: api\n    environment:\n      DEBUG:\n")
        self.assertIsNone(service.environment["DEBUG"])

    def test_map_empty_string_is_empty_string(self):
        service = _service('services:\n  api:\n    image: api\n    environment:\n      DEBUG: ""\n')
        self.assertEqual(service.environment["DEBUG"], "")


class BareEnvironmentFactTests(unittest.TestCase):
    def test_host_environment_fact_shape(self):
        fact = build_env_fact("api", "DEBUG", HOST_ENVIRONMENT)
        self.assertEqual(
            fact,
            {
                "service": "api",
                "name": "DEBUG",
                "value_present": "unknown",
                "value_type": "host_environment",
                "source": "host_environment",
                "resolved": False,
                "contains_credentials": False,
            },
        )

    def test_bare_key_never_reads_a_real_value(self):
        # Distinct from an explicitly empty value, which stays "empty".
        bare = build_env_fact("api", "DEBUG", HOST_ENVIRONMENT)
        empty = build_env_fact("api", "DEBUG", "")
        self.assertEqual(bare["source"], "host_environment")
        self.assertEqual(empty["value_type"], "empty")
        self.assertNotIn("source", empty)


if __name__ == "__main__":
    unittest.main()
