## Task 3: Parser Warning Resilience For Malformed Files

**Files:**
- Modify: `src/preanalyzer/analyzer/parsers/maven.py`
- Modify: `src/preanalyzer/analyzer/parsers/nodejs.py`
- Modify: `src/preanalyzer/analyzer/parsers/python_pkg.py`
- Modify: `src/preanalyzer/pipeline.py`
- Test: `tests/unit/test_parser_warnings.py`

**Interfaces:**
- Produces:
  - `ParseWarning(path: str, parser: str, message: str)`
  - `try_parse(path: Path) -> ParsedX | ParseWarning` in each package parser module.
- Existing `parse(path: Path) -> ParsedX` remains strict and continues to be used by existing unit tests.
- `pipeline.run_phase1_analysis(...)` must skip `ParseWarning` artifacts and write warnings into `02-evidence-model.yaml`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_parser_warnings.py`:

```python
from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.parsers.maven import ParseWarning as MavenWarning, try_parse as try_parse_maven
from preanalyzer.analyzer.parsers.nodejs import ParseWarning as NodeWarning, try_parse as try_parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import ParseWarning as PythonWarning, try_parse_pyproject


class ParserWarningTests(unittest.TestCase):
    def test_malformed_maven_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pom.xml"
            path.write_text("<project>", encoding="utf-8")
            result = try_parse_maven(path)

        self.assertIsInstance(result, MavenWarning)
        self.assertEqual(result.path, str(path))
        self.assertEqual(result.parser, "maven")

    def test_malformed_package_json_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            path.write_text("{", encoding="utf-8")
            result = try_parse_nodejs(path)

        self.assertIsInstance(result, NodeWarning)
        self.assertEqual(result.parser, "nodejs")

    def test_malformed_pyproject_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text("[project", encoding="utf-8")
            result = try_parse_pyproject(path)

        self.assertIsInstance(result, PythonWarning)
        self.assertEqual(result.parser, "python_pyproject")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_parser_warnings -v
```

Expected: FAIL with import error for `try_parse`.

- [ ] **Step 3: Implement warning dataclasses and wrappers**

In each parser module, add a module-local warning dataclass. Example for `nodejs.py`:

```python
@dataclass(frozen=True)
class ParseWarning:
    path: str
    parser: str
    message: str


def try_parse(path: Path) -> ParsedNodePackage | ParseWarning:
    try:
        return parse(path)
    except Exception as exc:
        return ParseWarning(path=str(path), parser="nodejs", message=str(exc))
```

For `maven.py`, use `parser="maven"`. For `python_pkg.py`, add:

```python
@dataclass(frozen=True)
class ParseWarning:
    path: str
    parser: str
    message: str


def try_parse_pyproject(path: Path) -> ParsedPythonPackage | ParseWarning:
    try:
        return parse_pyproject(path)
    except Exception as exc:
        return ParseWarning(path=str(path), parser="python_pyproject", message=str(exc))


def try_parse_requirements(path: Path) -> ParsedPythonPackage | ParseWarning:
    try:
        return parse_requirements(path)
    except Exception as exc:
        return ParseWarning(path=str(path), parser="python_requirements", message=str(exc))
```

- [ ] **Step 4: Feed parser warnings through pipeline**

Modify `src/preanalyzer/pipeline.py`:

```python
def _parse_inventory(repo: Path, inventory: ArtifactInventory) -> tuple[dict[str, object], list[dict[str, str]]]:
    parsed: dict[str, object] = {}
    warnings: list[dict[str, str]] = []
    ...
    result = try_parse_nodejs(repo / path)
    if _is_parse_warning(result):
        warnings.append({"path": path, "parser": result.parser, "message": result.message})
    else:
        parsed[path] = result
    ...
    return parsed, warnings


def _is_parse_warning(value: object) -> bool:
    return all(hasattr(value, attr) for attr in ["path", "parser", "message"])
```

Modify `run_phase1_analysis(...)`:

```python
    parsed_artifacts, parse_warnings = _parse_inventory(repo, inventory)
    evidence = build_evidence(inventory, parsed_artifacts)
    evidence = EvidenceModel(facts=evidence.facts, warnings=parse_warnings)
```

Import `EvidenceModel` is already present in `pipeline.py`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_parser_warnings -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

Commit:

```bash
git add src/preanalyzer/analyzer/parsers/maven.py src/preanalyzer/analyzer/parsers/nodejs.py src/preanalyzer/analyzer/parsers/python_pkg.py src/preanalyzer/pipeline.py tests/unit/test_parser_warnings.py
git commit -m "feat: keep phase1 running on malformed package files"
```

