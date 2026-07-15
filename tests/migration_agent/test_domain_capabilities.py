from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


EXTRA_TEST_FILES = [
    Path(__file__).parent / "adapters" / "test_preanalyzer_adapter.py",
    Path(__file__).parent / "domain" / "test_understanding_models.py",
    Path(__file__).parent / "capabilities" / "test_analysis_builder.py",
]


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(tests)
    for path in EXTRA_TEST_FILES:
        module_name = f"_migration_agent_{path.parent.name}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load test module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
