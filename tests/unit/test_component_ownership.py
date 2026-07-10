from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def _clock():
    return FIXED_TIME


def _infer(repo: Path, parsers: dict):
    inventory = build_inventory(repo, snapshot(repo, None, None, _clock))
    evidence = build_evidence(inventory, parsers)
    return infer(evidence)


def _components(rules):
    return {c.component_id: c.root_path for c in rules.component_candidates}


class ComponentOwnershipTests(unittest.TestCase):
    def test_package_only_monorepo_detects_each_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "api").mkdir(parents=True)
            (repo / "services" / "worker").mkdir(parents=True)
            (repo / "services" / "api" / "package.json").write_text(
                '{"name": "api", "dependencies": {"express": "^4"}}', encoding="utf-8"
            )
            (repo / "services" / "worker" / "package.json").write_text(
                '{"name": "worker", "dependencies": {"express": "^4"}}', encoding="utf-8"
            )

            rules = _infer(
                repo,
                {
                    "services/api/package.json": parse_nodejs(repo / "services/api/package.json"),
                    "services/worker/package.json": parse_nodejs(repo / "services/worker/package.json"),
                },
            )

        self.assertEqual(
            _components(rules),
            {"services/api": "services/api", "services/worker": "services/worker"},
        )
        # Each package's runtime is attributed to its own component (longest prefix).
        runtimes = {(c.component_id, c.framework) for c in rules.runtime_candidates}
        self.assertIn(("services/api", "express"), runtimes)
        self.assertIn(("services/worker", "express"), runtimes)

    def test_compose_with_image_only_service_plus_package_keeps_both(self):
        # An image-only db service must not swallow the root application package.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "docker-compose.yml").write_text(
                "services:\n"
                "  app:\n"
                "    build: .\n"
                "  db:\n"
                "    image: postgres:16\n",
                encoding="utf-8",
            )
            (repo / "package.json").write_text(
                '{"name": "app", "dependencies": {"express": "^4"}}', encoding="utf-8"
            )

            rules = _infer(
                repo,
                {
                    "docker-compose.yml": parse_compose(repo / "docker-compose.yml"),
                    "package.json": parse_nodejs(repo / "package.json"),
                },
            )

        components = _components(rules)
        # app builds from ".", so its package is subsumed into the compose service.
        self.assertEqual(components["app"], ".")
        # db is image-only: present as a component but owning no source root.
        self.assertIsNone(components["db"])
        # The express runtime belongs to app, never to the image-only db.
        express = [c for c in rules.runtime_candidates if c.framework == "express"]
        self.assertEqual([c.component_id for c in express], ["app"])

    def test_image_only_service_gets_no_source_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "docker-compose.yml").write_text(
                "services:\n  cache:\n    image: redis:7\n", encoding="utf-8"
            )
            (repo / "package.json").write_text(
                '{"name": "root", "dependencies": {"express": "^4"}}', encoding="utf-8"
            )

            rules = _infer(
                repo,
                {
                    "docker-compose.yml": parse_compose(repo / "docker-compose.yml"),
                    "package.json": parse_nodejs(repo / "package.json"),
                },
            )

        components = _components(rules)
        # cache is image-only; the root package is a separate component.
        self.assertIsNone(components["cache"])
        self.assertEqual(components["root"], ".")
        # The express runtime is attributed to root, not the image-only cache.
        express = [c for c in rules.runtime_candidates if c.framework == "express"]
        self.assertEqual([c.component_id for c in express], ["root"])

    def test_nested_package_attributed_to_most_specific_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                '{"name": "root", "dependencies": {"react": "^18"}}', encoding="utf-8"
            )
            (repo / "web").mkdir()
            (repo / "web" / "package.json").write_text(
                '{"name": "web", "dependencies": {"express": "^4"}}', encoding="utf-8"
            )

            rules = _infer(
                repo,
                {
                    "package.json": parse_nodejs(repo / "package.json"),
                    "web/package.json": parse_nodejs(repo / "web/package.json"),
                },
            )

        components = _components(rules)
        self.assertEqual(components["root"], ".")
        self.assertEqual(components["web"], "web")
        runtimes = {(c.component_id, c.framework) for c in rules.runtime_candidates}
        # web's express dependency is not leaked up into root.
        self.assertIn(("web", "express"), runtimes)
        self.assertIn(("root", "react"), runtimes)


if __name__ == "__main__":
    unittest.main()
