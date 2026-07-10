from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.analyzer.env_safety import build_env_fact
from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.models.inventory import ArtifactInventory


def _env_facts(compose_text: str):
    with tempfile.TemporaryDirectory() as tmp:
        compose = Path(tmp) / "docker-compose.yml"
        compose.write_text(compose_text, encoding="utf-8")
        parsed = parse_compose(compose)
        evidence = build_evidence(ArtifactInventory(), {"docker-compose.yml": parsed})
    return evidence


def _fact_for(evidence, name: str) -> dict:
    for fact in evidence.facts_by_type("compose_environment"):
        if fact.value["name"] == name:
            return fact.value
    raise AssertionError(f"missing env fact {name}")


def _serialize(evidence) -> str:
    return yaml.safe_dump({"evidence_model": evidence.model_dump()}, allow_unicode=False)


class EnvSecretRedactionTests(unittest.TestCase):
    def test_database_url_with_credentials_is_sanitized(self):
        evidence = _env_facts(
            "services:\n"
            "  api:\n"
            "    image: api\n"
            "    environment:\n"
            "      DATABASE_URL: postgresql://admin:real-password@db:5432/app\n"
        )
        serialized = _serialize(evidence)
        self.assertNotIn("real-password", serialized)
        self.assertNotIn("admin:real-password", serialized)
        self.assertNotIn("admin", serialized)

        fact = _fact_for(evidence, "DATABASE_URL")
        self.assertEqual(fact["value_type"], "uri")
        self.assertTrue(fact["contains_credentials"])
        self.assertEqual(fact["sanitized"], {"scheme": "postgresql", "host": "db", "port": 5432})
        self.assertNotIn("value", fact)

    def test_redis_url_password_removed(self):
        evidence = _env_facts(
            "services:\n"
            "  cache:\n"
            "    image: app\n"
            "    environment:\n"
            "      REDIS_URL: redis://:real-password@redis:6379\n"
        )
        serialized = _serialize(evidence)
        self.assertNotIn("real-password", serialized)
        self.assertNotIn("redis://:", serialized)

        fact = _fact_for(evidence, "REDIS_URL")
        self.assertTrue(fact["contains_credentials"])
        self.assertEqual(fact["sanitized"]["host"], "redis")
        self.assertEqual(fact["sanitized"]["port"], 6379)

    def test_jdbc_url_credentials_removed(self):
        fact = build_env_fact("api", "JDBC_URL", "jdbc:postgresql://user:password@db/app")
        self.assertEqual(fact["value_type"], "uri")
        self.assertTrue(fact["contains_credentials"])
        self.assertEqual(fact["sanitized"]["host"], "db")
        self.assertNotIn("value", fact)

    def test_query_parameter_token_flagged(self):
        fact = build_env_fact("api", "SERVICE_URL", "https://api.example.com/v1?token=abcdef123456")
        self.assertTrue(fact["contains_credentials"])
        self.assertEqual(fact["sanitized"]["host"], "api.example.com")

    def test_variable_reference_only_stores_names(self):
        fact = build_env_fact("api", "DB_PASSWORD_REF", "${POSTGRES_PASSWORD}")
        self.assertEqual(fact["value_type"], "reference")
        self.assertEqual(fact["referenced_variables"], ["POSTGRES_PASSWORD"])
        self.assertNotIn("value", fact)

    def test_uri_with_reference_password_keeps_reference_and_host(self):
        fact = build_env_fact("api", "DATABASE_URL", "postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/app")
        self.assertEqual(fact["value_type"], "uri")
        self.assertTrue(fact["contains_credentials"])
        self.assertEqual(fact["referenced_variables"], ["POSTGRES_PASSWORD"])
        self.assertEqual(fact["sanitized"]["host"], "db")

    def test_non_sensitive_name_with_credential_value_not_leaked(self):
        # Name has no sensitive keyword, but the value embeds a credential URI.
        evidence = _env_facts(
            "services:\n"
            "  worker:\n"
            "    image: app\n"
            "    environment:\n"
            "      SMTP_URL: smtp://account:real-password@mail.example.com\n"
        )
        serialized = _serialize(evidence)
        self.assertNotIn("real-password", serialized)
        self.assertNotIn("account", serialized)

        fact = _fact_for(evidence, "SMTP_URL")
        self.assertTrue(fact["contains_credentials"])

        # A credential-bearing var must be flagged as a secret candidate even
        # though its name has no sensitive keyword.
        rules = infer(evidence)
        secret_names = {c.name for c in rules.env_classification.secret_candidates}
        self.assertIn("SMTP_URL", secret_names)

    def test_plain_value_is_not_stored(self):
        fact = build_env_fact("api", "NODE_ENV", "production")
        self.assertEqual(fact["value_type"], "plain")
        self.assertTrue(fact["value_present"])
        self.assertFalse(fact["contains_credentials"])
        self.assertNotIn("value", fact)
        self.assertNotIn("sanitized", fact)

    def test_database_dependency_edge_still_detected_from_sanitized_host(self):
        evidence = _env_facts(
            "services:\n"
            "  backend:\n"
            "    image: api\n"
            "    environment:\n"
            "      DATABASE_URL: postgresql://postgres:secret@db:5432/app\n"
            "  db:\n"
            "    image: postgres:16\n"
        )
        rules = infer(evidence)
        edges = [
            (c.source_component, c.target, c.dependency_type)
            for c in rules.dependency_edge_candidates
        ]
        self.assertIn(("backend", "db", "database"), edges)


if __name__ == "__main__":
    unittest.main()
