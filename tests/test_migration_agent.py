from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MIGRATION_AGENT_TEST_FILES = [
    Path(__file__).parent / "migration_agent" / "test_domain_capabilities.py",
    Path(__file__).parent / "migration_agent" / "test_import_boundaries.py",
    Path(__file__).parent / "migration_agent" / "test_legacy_baseline.py",
]


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(tests)
    for path in MIGRATION_AGENT_TEST_FILES:
        module_name = f"_root_migration_agent_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load test module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
