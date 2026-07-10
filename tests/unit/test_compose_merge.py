from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from preanalyzer.analyzer.env_safety import HOST_ENVIRONMENT
from preanalyzer.analyzer.parsers.compose import (
    _merge_compose_documents,
    parse_with_override,
)


def _merge(base_text: str, override_text: str):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / "docker-compose.yml"
        override = root / "docker-compose.override.yml"
        base.write_text(base_text, encoding="utf-8")
        override.write_text(override_text, encoding="utf-8")
        return parse_with_override(base, override)


class ComposeMergeTests(unittest.TestCase):
    def test_distinct_ports_are_combined(self):
        parsed = _merge(
            'services:\n  api:\n    image: api\n    ports:\n      - "8080:80"\n',
            'services:\n  api:\n    ports:\n      - "9090:90"\n',
        )
        pairs = {(p.host_port, p.container_port) for p in parsed.service("api").ports}
        self.assertEqual(pairs, {(8080, 80), (9090, 90)})

    def test_same_key_port_is_replaced_not_duplicated(self):
        parsed = _merge(
            'services:\n  api:\n    image: api\n    ports:\n      - "8080:80"\n      - "9090:90"\n',
            'services:\n  api:\n    ports:\n      - "9090:90"\n      - "7000:70"\n',
        )
        pairs = sorted((p.host_port, p.container_port) for p in parsed.service("api").ports)
        self.assertEqual(pairs, [(7000, 70), (8080, 80), (9090, 90)])

    def test_volume_target_is_overridden(self):
        parsed = _merge(
            "services:\n  api:\n    image: api\n    volumes:\n      - ./a:/data\n",
            "services:\n  api:\n    volumes:\n      - ./b:/data\n",
        )
        self.assertEqual(parsed.service("api").volumes, ["./b:/data"])

    def test_environment_map_and_list_forms_unify(self):
        parsed = _merge(
            'services:\n  api:\n    image: api\n    environment:\n      - A=1\n',
            'services:\n  api:\n    environment:\n      B: "2"\n',
        )
        self.assertEqual(parsed.service("api").environment, {"A": "1", "B": "2"})

    def test_labels_map_and_list_forms_unify(self):
        parsed = _merge(
            "services:\n  api:\n    image: api\n    labels:\n      - a=1\n",
            'services:\n  api:\n    labels:\n      b: "2"\n',
        )
        self.assertEqual(parsed.service("api").labels, {"a": "1", "b": "2"})

    def test_bare_environment_key_survives_merge(self):
        parsed = _merge(
            "services:\n  api:\n    image: api\n    environment:\n      - DEBUG\n",
            'services:\n  api:\n    environment:\n      B: "2"\n',
        )
        env = parsed.service("api").environment
        self.assertIs(env["DEBUG"], HOST_ENVIRONMENT)
        self.assertEqual(env["B"], "2")

    def test_override_tag_replaces_environment(self):
        parsed = _merge(
            'services:\n  api:\n    image: api\n    environment:\n      A: "1"\n',
            'services:\n  api:\n    environment: !override\n      B: "2"\n',
        )
        self.assertEqual(parsed.service("api").environment, {"B": "2"})

    def test_reset_tag_removes_key(self):
        parsed = _merge(
            'services:\n  api:\n    image: api\n    environment:\n      A: "1"\n',
            "services:\n  api:\n    environment: !reset null\n",
        )
        self.assertEqual(parsed.service("api").environment, {})


class ComposeThreeFileMergeTests(unittest.TestCase):
    def test_three_documents_merge_in_order(self):
        import yaml

        base = {"services": {"api": {"image": "api", "ports": ["8080:80"]}}}
        mid = {"services": {"api": {"ports": ["9090:90"]}}}
        top = {"services": {"api": {"image": "final/api"}}}

        merged = _merge_compose_documents(_merge_compose_documents(base, mid), top)
        api = merged["services"]["api"]
        self.assertEqual(api["image"], "final/api")
        self.assertEqual(sorted(api["ports"]), ["8080:80", "9090:90"])
        # Sanity: serializable / real compose shape.
        self.assertIn("services", yaml.safe_load(yaml.safe_dump(merged)))


@unittest.skipUnless(shutil.which("docker"), "docker CLI not available")
class ComposeMergeGoldenTests(unittest.TestCase):
    """Compare our merge against `docker compose config` (the reference)."""

    def _docker_ports(self, base_text: str, override_text: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.yml"
            override = root / "override.yml"
            base.write_text(base_text, encoding="utf-8")
            override.write_text(override_text, encoding="utf-8")
            result = subprocess.run(
                ["docker", "compose", "-f", str(base), "-f", str(override), "config", "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.skipTest(f"docker compose config unavailable: {result.stderr.strip()[:120]}")
            document = json.loads(result.stdout)
        ports = document["services"]["api"]["ports"]
        return sorted((int(p["published"]), int(p["target"])) for p in ports)

    def test_port_merge_matches_docker(self):
        base = 'services:\n  api:\n    image: nginx\n    ports:\n      - "8080:80"\n      - "9090:90"\n'
        override = 'services:\n  api:\n    ports:\n      - "9090:90"\n      - "7000:70"\n'

        parsed = _merge(base, override)
        ours = sorted((p.host_port, p.container_port) for p in parsed.service("api").ports)

        self.assertEqual(ours, self._docker_ports(base, override))


if __name__ == "__main__":
    unittest.main()
