from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path


SRC = Path("src")


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


class ImportBoundaryTests(unittest.TestCase):
    def test_migration_agent_package_imports_without_legacy_agent_dependency(self) -> None:
        module = importlib.import_module("migration_agent")

        self.assertIsNotNone(module)
        for path in (SRC / "migration_agent").rglob("*.py"):
            self.assertNotIn("k8s_agent", imported_roots(path), str(path))

    def test_preanalyzer_does_not_depend_on_migration_agent(self) -> None:
        for path in (SRC / "preanalyzer").rglob("*.py"):
            self.assertNotIn("migration_agent", imported_roots(path), str(path))


if __name__ == "__main__":
    unittest.main()
