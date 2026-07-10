# Phase 1 Deterministic Runtime Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the missing deterministic phase-1 analyzer data needed before LLM semantic analysis: runtime versions, port/command candidates, dependency edges, parser warning resilience, Compose override/volume/unsupported-key signals, and pydantic model validation.

**Architecture:** Keep the current deterministic chain intact: `scanner -> parsers -> evidence_builder -> rule_inference -> pipeline output 00~03`. Parsers extract raw facts without semantic finalization; Evidence Builder records observed facts; Rule Inference promotes candidates with provenance but does not reconcile final intent. Pydantic conversion is last so behavioral changes are already covered by tests before model enforcement changes.

**Tech Stack:** Python 3.11+, `unittest`, `PyYAML`, `tomllib`, pydantic v2 for final model conversion.

## Global Constraints

- **P1 Parser before LLM**: 파일 탐지·파싱·Evidence 생성에 LLM 사용 금지. LLM은 Repository 전체가 아니라 Evidence Bundle만 본다.
- **P2 Intermediate model before YAML**: repository_snapshot → artifact_inventory → evidence_model → rule_inference/semantic_analysis → reconciliation → component_model → runtime_model → dependency_model → kubernetes_intent 체인을 반드시 거친다. Repository → YAML 직행 금지.
- **P5 Ask instead of guess**: 확인 불가 값은 `unresolved` + 질문 생성. 기본값으로 조용히 채우지 않는다.
- **P6 모든 추출·해석 필드는 `value / source / confidence(high|medium|low|none) / classification / evidence_refs`를 갖는다.**
- **P9 Secret 값은 LLM으로도, 산출물로도 흐르지 않는다.** 이름·출처·분류 근거만 기록. placeholder 값은 `__REPLACE_ME__` 고정.
- **P10 재현성**: 동일 commit + 동일 Profile + 동일 rules_version → 동일 산출물.
- Work on branch `mvp-preanalysis-phase1`.
- Use TDD: failing test first, verify RED, implement minimal GREEN, run full suite, commit each task.
- Verification command for every task: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`.

---

## File Structure

- Modify `src/preanalyzer/models/rule_inference.py`: add `RuntimeVersionCandidate`, `RuntimePortCandidate`, `RuntimeCommandCandidate`, `DependencyEdgeCandidate`, and append corresponding lists to `RuleInferenceSet`.
- Modify `src/preanalyzer/analyzer/rule_inference.py`: promote observed facts into runtime version, port, command, dependency, and env classification candidates.
- Modify `src/preanalyzer/analyzer/parsers/dockerfile.py`: preserve base image facts already present; no structural split needed.
- Modify `src/preanalyzer/analyzer/parsers/compose.py`: add override merge helper, unsupported key warnings, named volume records.
- Modify `src/preanalyzer/analyzer/parsers/maven.py`, `nodejs.py`, `python_pkg.py`: add warning-returning parse wrappers or warning fields while keeping current `parse(...)` API compatible.
- Modify `src/preanalyzer/analyzer/evidence_builder.py`: record package runtime hints, Compose volume signals, parser warnings, and sanitized env dependency signals.
- Modify `src/preanalyzer/models/*.py`: convert dataclasses to pydantic v2 models in the final task.
- Modify `src/preanalyzer/pipeline.py`: call new parser APIs where needed, keep output filenames unchanged.
- Add/modify tests:
  - `tests/unit/test_rule_runtime_candidates.py`
  - `tests/unit/test_rule_dependency_edges.py`
  - `tests/unit/test_parser_warnings.py`
  - `tests/unit/test_compose_parser_extended.py`
  - `tests/unit/test_pydantic_models.py`
  - `tests/acceptance/test_phase1_deterministic_outputs.py`

## Task 1: Runtime Version, Port, And Command Candidates

**Files:**
- Modify: `src/preanalyzer/models/rule_inference.py`
- Modify: `src/preanalyzer/analyzer/rule_inference.py`
- Modify: `src/preanalyzer/analyzer/evidence_builder.py`
- Test: `tests/unit/test_rule_runtime_candidates.py`
- Test: `tests/acceptance/test_phase1_deterministic_outputs.py`

**Interfaces:**
- Consumes: `EvidenceModel` facts:
  - `dockerfile_base_image`
  - `dockerfile_expose`
  - `dockerfile_cmd`
  - `package_dependency`
- Produces:
  - `RuntimeVersionCandidate(component_id: str, language: str, version: str, source: str, confidence: str, evidence_refs: list[str])`
  - `RuntimePortCandidate(component_id: str, port: int, source: str, confidence: str, evidence_refs: list[str])`
  - `RuntimeCommandCandidate(component_id: str, command: str, source: str, confidence: str, evidence_refs: list[str])`
  - `RuleInferenceSet.runtime_version_candidates`
  - `RuleInferenceSet.runtime_port_candidates`
  - `RuleInferenceSet.runtime_command_candidates`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_rule_runtime_candidates.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_TIME


def rules_for_fastapi():
    repo = FIXTURES / "fastapi-fullstack-like"
    inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
    evidence = build_evidence(
        inventory,
        {
            "backend/Dockerfile": parse_dockerfile(repo / "backend" / "Dockerfile"),
            "backend/pyproject.toml": parse_pyproject(repo / "backend" / "pyproject.toml"),
            "frontend/Dockerfile": parse_dockerfile(repo / "frontend" / "Dockerfile"),
            "frontend/package.json": parse_nodejs(repo / "frontend" / "package.json"),
        },
    )
    return infer(evidence)


class RuleRuntimeCandidateTests(unittest.TestCase):
    def test_runtime_versions_promoted_from_dockerfile_base_images(self):
        rules = rules_for_fastapi()

        self.assertIn(
            {
                "component_id": "backend",
                "language": "python",
                "version": "3.11",
                "source": "dockerfile_from",
                "confidence": "high",
                "evidence_refs": ["F0005"],
            },
            [candidate.model_dump() for candidate in rules.runtime_version_candidates],
        )
        self.assertIn(
            {
                "component_id": "frontend",
                "language": "nodejs",
                "version": "20",
                "source": "dockerfile_from",
                "confidence": "high",
                "evidence_refs": ["F0008"],
            },
            [candidate.model_dump() for candidate in rules.runtime_version_candidates],
        )

    def test_ports_and_commands_promoted_from_dockerfile(self):
        rules = rules_for_fastapi()

        self.assertIn(
            {
                "component_id": "backend",
                "port": 8000,
                "source": "dockerfile_expose",
                "confidence": "high",
                "evidence_refs": ["F0006"],
            },
            [candidate.model_dump() for candidate in rules.runtime_port_candidates],
        )
        self.assertIn(
            {
                "component_id": "backend",
                "command": "[\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",
                "source": "dockerfile_cmd",
                "confidence": "high",
                "evidence_refs": ["F0007"],
            },
            [candidate.model_dump() for candidate in rules.runtime_command_candidates],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_rule_runtime_candidates -v
```

Expected: FAIL with `AttributeError: 'RuleInferenceSet' object has no attribute 'runtime_version_candidates'`.

- [ ] **Step 3: Add candidate models**

Modify `src/preanalyzer/models/rule_inference.py` by adding:

```python
@dataclass(frozen=True)
class RuntimeVersionCandidate:
    component_id: str
    language: str
    version: str
    source: str
    confidence: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RuntimePortCandidate:
    component_id: str
    port: int
    source: str
    confidence: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeCommandCandidate:
    component_id: str
    command: str
    source: str
    confidence: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)
```

Modify `RuleInferenceSet`:

```python
@dataclass(frozen=True)
class RuleInferenceSet:
    component_candidates: list[ComponentCandidate] = field(default_factory=list)
    role_candidates: list[RoleCandidate] = field(default_factory=list)
    runtime_candidates: list[RuntimeCandidate] = field(default_factory=list)
    runtime_version_candidates: list[RuntimeVersionCandidate] = field(default_factory=list)
    runtime_port_candidates: list[RuntimePortCandidate] = field(default_factory=list)
    runtime_command_candidates: list[RuntimeCommandCandidate] = field(default_factory=list)
    env_classification: EnvClassification = field(default_factory=EnvClassification)

    def model_dump(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Implement minimal inference**

Modify imports in `src/preanalyzer/analyzer/rule_inference.py`:

```python
from preanalyzer.models.rule_inference import (
    ComponentCandidate,
    EnvClassification,
    RoleCandidate,
    RuleInferenceSet,
    RuntimeCandidate,
    RuntimeCommandCandidate,
    RuntimePortCandidate,
    RuntimeVersionCandidate,
    SecretCandidate,
)
```

Modify `infer(...)`:

```python
    return RuleInferenceSet(
        component_candidates=component_candidates,
        role_candidates=_role_candidates(evidence),
        runtime_candidates=_runtime_candidates(evidence, component_candidates, root_by_component),
        runtime_version_candidates=_runtime_version_candidates(evidence, component_candidates),
        runtime_port_candidates=_runtime_port_candidates(evidence, component_candidates),
        runtime_command_candidates=_runtime_command_candidates(evidence, component_candidates),
        env_classification=EnvClassification(secret_candidates=_secret_candidates(evidence)),
    )
```

Add helpers:

```python
def _runtime_version_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimeVersionCandidate]:
    candidates: list[RuntimeVersionCandidate] = []
    for fact in evidence.facts_by_type("dockerfile_base_image"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        parsed = _runtime_from_image(str(fact.value))
        if component_id is not None and parsed is not None:
            language, version = parsed
            candidates.append(
                RuntimeVersionCandidate(component_id, language, version, fact.source, "high", [fact.evidence_id])
            )
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.language))


def _runtime_port_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimePortCandidate]:
    candidates = []
    for fact in evidence.facts_by_type("dockerfile_expose"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        if component_id is not None:
            candidates.append(RuntimePortCandidate(component_id, int(fact.value), fact.source, "high", [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.port))


def _runtime_command_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimeCommandCandidate]:
    candidates = []
    for fact in evidence.facts_by_type("dockerfile_cmd"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        if component_id is not None:
            candidates.append(RuntimeCommandCandidate(component_id, str(fact.value), fact.source, "high", [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: candidate.component_id)


def _component_for_artifact(artifact_ref: str, component_candidates: list[ComponentCandidate]) -> str | None:
    for candidate in component_candidates:
        root_path = candidate.root_path
        if root_path in {None, "."} and "/" not in artifact_ref:
            return candidate.component_id
        if root_path and root_path != "." and artifact_ref.startswith(f"{root_path}/"):
            return candidate.component_id
    return None


def _runtime_from_image(image: str) -> tuple[str, str] | None:
    repository, _, tag = image.partition(":")
    if not tag:
        return None
    language = {"python": "python", "node": "nodejs", "eclipse-temurin": "java", "openjdk": "java"}.get(repository.split("/")[-1])
    if language is None:
        return None
    version = tag.split("-", 1)[0]
    if version:
        return language, version
    return None
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_rule_runtime_candidates -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

Commit:

```bash
git add src/preanalyzer/models/rule_inference.py src/preanalyzer/analyzer/rule_inference.py tests/unit/test_rule_runtime_candidates.py
git commit -m "feat: promote runtime version port and command candidates"
```

## Task 2: Dependency Edge Candidates

**Files:**
- Modify: `src/preanalyzer/models/rule_inference.py`
- Modify: `src/preanalyzer/analyzer/rule_inference.py`
- Test: `tests/unit/test_rule_dependency_edges.py`
- Test: `tests/acceptance/test_phase1_deterministic_outputs.py`

**Interfaces:**
- Consumes:
  - `compose_depends_on`
  - `compose_environment` with `DATABASE_URL`
- Produces:
  - `DependencyEdgeCandidate(source_component: str, target: str, dependency_type: str, source: str, confidence: str, evidence_refs: list[str])`
  - `RuleInferenceSet.dependency_edge_candidates`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_rule_dependency_edges.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_TIME


class RuleDependencyEdgeTests(unittest.TestCase):
    def test_depends_on_becomes_internal_dependency_edge(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
        evidence = build_evidence(inventory, {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")})
        rules = infer(evidence)

        self.assertIn(
            {
                "source_component": "backend",
                "target": "db",
                "dependency_type": "internal",
                "source": "compose_depends_on",
                "confidence": "high",
                "evidence_refs": ["F0009"],
            },
            [candidate.model_dump() for candidate in rules.dependency_edge_candidates],
        )

    def test_database_url_becomes_database_dependency_signal(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
        evidence = build_evidence(inventory, {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")})
        rules = infer(evidence)

        self.assertIn(
            {
                "source_component": "backend",
                "target": "db",
                "dependency_type": "database",
                "source": "compose_environment",
                "confidence": "medium",
                "evidence_refs": ["F0011"],
            },
            [candidate.model_dump() for candidate in rules.dependency_edge_candidates],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_rule_dependency_edges -v
```

Expected: FAIL with `AttributeError: 'RuleInferenceSet' object has no attribute 'dependency_edge_candidates'`.

- [ ] **Step 3: Add model**

Modify `src/preanalyzer/models/rule_inference.py`:

```python
@dataclass(frozen=True)
class DependencyEdgeCandidate:
    source_component: str
    target: str
    dependency_type: str
    source: str
    confidence: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)
```

Add to `RuleInferenceSet`:

```python
    dependency_edge_candidates: list[DependencyEdgeCandidate] = field(default_factory=list)
```

- [ ] **Step 4: Implement inference**

Modify imports in `src/preanalyzer/analyzer/rule_inference.py` to include `DependencyEdgeCandidate`.

Add to `infer(...)`:

```python
        dependency_edge_candidates=_dependency_edge_candidates(evidence),
```

Add helpers:

```python
def _dependency_edge_candidates(evidence: EvidenceModel) -> list[DependencyEdgeCandidate]:
    candidates: list[DependencyEdgeCandidate] = []
    compose_services = {fact.value["service"] for fact in evidence.facts_by_type("compose_service")}
    for fact in evidence.facts_by_type("compose_depends_on"):
        candidates.append(
            DependencyEdgeCandidate(
                source_component=fact.value["service"],
                target=fact.value["depends_on"],
                dependency_type="internal",
                source=fact.source,
                confidence="high",
                evidence_refs=[fact.evidence_id],
            )
        )
    for fact in evidence.facts_by_type("compose_environment"):
        name = fact.value["name"]
        value = str(fact.value.get("value", ""))
        if name.upper().endswith("DATABASE_URL"):
            target = _database_target(value, compose_services)
            if target is not None:
                candidates.append(
                    DependencyEdgeCandidate(
                        source_component=fact.value["service"],
                        target=target,
                        dependency_type="database",
                        source=fact.source,
                        confidence="medium",
                        evidence_refs=[fact.evidence_id],
                    )
                )
    return sorted(candidates, key=lambda c: (c.source_component, c.target, c.dependency_type))


def _database_target(value: str, compose_services: set[str]) -> str | None:
    for service in sorted(compose_services):
        if f"@{service}:" in value or f"//{service}:" in value:
            return service
    return None
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_rule_dependency_edges -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

Commit:

```bash
git add src/preanalyzer/models/rule_inference.py src/preanalyzer/analyzer/rule_inference.py tests/unit/test_rule_dependency_edges.py
git commit -m "feat: infer deterministic dependency edges"
```

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

## Task 4: Compose Override, Volume, And Unsupported-Key Signals

**Files:**
- Modify: `src/preanalyzer/analyzer/parsers/compose.py`
- Modify: `src/preanalyzer/analyzer/evidence_builder.py`
- Test: `tests/unit/test_compose_parser_extended.py`

**Interfaces:**
- Produces:
  - `parse_with_override(base_path: Path, override_path: Path | None) -> ParsedCompose`
  - `ComposeService.volumes: list[str]` already exists.
  - `ParsedCompose.warnings: list[str]` already exists.
  - Evidence facts:
    - `compose_volume`
    - `parse_warning` for unsupported keys

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compose_parser_extended.py`:

```python
from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse, parse_with_override


class ComposeParserExtendedTests(unittest.TestCase):
    def test_override_file_merges_service_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            base.write_text("services:\n  api:\n    image: old/api\n    ports:\n      - \"8080:80\"\n", encoding="utf-8")
            override.write_text("services:\n  api:\n    image: new/api\n", encoding="utf-8")

            parsed = parse_with_override(base, override)

        self.assertEqual(parsed.service("api").image, "new/api")
        self.assertEqual(parsed.service("api").ports[0].container_port, 80)

    def test_unsupported_keys_warned_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text("services:\n  api:\n    image: api\n    network_mode: host\n", encoding="utf-8")

            parsed = parse(compose)

        self.assertEqual(parsed.warnings, ["api: unsupported key network_mode"])

    def test_named_volume_recorded_as_evidence_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text("services:\n  db:\n    image: postgres:16\n    volumes:\n      - pgdata:/var/lib/postgresql/data\nvolumes:\n  pgdata: {}\n", encoding="utf-8")

            parsed = parse(compose)
            evidence = build_evidence(inventory=_empty_inventory(), parsed_artifacts={"docker-compose.yml": parsed})

        self.assertIn(
            {
                "fact_type": "compose_volume",
                "artifact_ref": "docker-compose.yml",
                "source": "compose_volumes",
                "classification": "observed_fact",
                "value": {"service": "db", "volume": "pgdata:/var/lib/postgresql/data"},
            },
            [_without_id(fact.model_dump()) for fact in evidence.facts],
        )


def _empty_inventory():
    from preanalyzer.models.inventory import ArtifactInventory
    return ArtifactInventory()


def _without_id(value):
    value = dict(value)
    value.pop("evidence_id")
    return value


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_compose_parser_extended -v
```

Expected: FAIL with import error for `parse_with_override` and missing `compose_volume` fact.

- [ ] **Step 3: Implement override merge and warnings**

Modify `src/preanalyzer/analyzer/parsers/compose.py`:

```python
SUPPORTED_SERVICE_KEYS = {
    "image",
    "build",
    "ports",
    "environment",
    "volumes",
    "depends_on",
    "labels",
}


def parse_with_override(base_path: Path, override_path: Path | None) -> ParsedCompose:
    base = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    if override_path is None:
        document = base
    else:
        override = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
        document = _merge_compose_documents(base, override)
    return _parse_document(base_path, document)


def parse(path: Path) -> ParsedCompose:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _parse_document(path, document)


def _parse_document(path: Path, document: dict) -> ParsedCompose:
    raw_services = document.get("services") or {}
    warnings = []
    services = []
    for name, value in sorted(raw_services.items()):
        raw = value or {}
        warnings.extend(f"{name}: unsupported key {key}" for key in sorted(set(raw) - SUPPORTED_SERVICE_KEYS))
        services.append(_parse_service(name, raw))
    return ParsedCompose(path=path.as_posix(), services=services, warnings=warnings)


def _merge_compose_documents(base: dict, override: dict) -> dict:
    merged = dict(base)
    merged_services = {name: dict(value or {}) for name, value in (base.get("services") or {}).items()}
    for name, value in (override.get("services") or {}).items():
        current = dict(merged_services.get(name, {}))
        current.update(value or {})
        merged_services[name] = current
    merged["services"] = merged_services
    return merged
```

- [ ] **Step 4: Record Compose volume and warning facts**

Modify `_append_compose_facts(...)` in `src/preanalyzer/analyzer/evidence_builder.py`:

```python
        for volume in service.volumes:
            append("compose_volume", artifact_ref, "compose_volumes", {"service": service.name, "volume": volume})
    for warning in parsed.warnings:
        append("parse_warning", artifact_ref, "compose_parser", warning)
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_compose_parser_extended -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

Commit:

```bash
git add src/preanalyzer/analyzer/parsers/compose.py src/preanalyzer/analyzer/evidence_builder.py tests/unit/test_compose_parser_extended.py
git commit -m "feat: capture compose override volume and warning signals"
```

## Task 5: Pydantic Model Conversion

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/preanalyzer/models/fields.py`
- Modify: `src/preanalyzer/models/snapshot.py`
- Modify: `src/preanalyzer/models/inventory.py`
- Modify: `src/preanalyzer/models/evidence.py`
- Modify: `src/preanalyzer/models/rule_inference.py`
- Test: `tests/unit/test_pydantic_models.py`

**Interfaces:**
- Preserve every current `.model_dump()` shape used in tests and YAML outputs.
- Add pydantic v2 validation for:
  - `Tracked(value != None)` requires `source != None` and `confidence != "none"`.
  - `EvidenceFact.classification == "observed_fact"` for phase-1 facts.
  - `RuleInferenceSet.model_json_schema()` exists.

- [ ] **Step 1: Verify dependency availability**

Run:

```bash
python3 -c "import pydantic; print(pydantic.__version__)"
```

Expected: prints a pydantic v2 version. If import fails, run dependency installation for the project environment before writing model code:

```bash
python3 -m pip install -e .
```

If network or permissions block dependency installation, stop and report that pydantic conversion is blocked by missing dependency installation.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_pydantic_models.py`:

```python
import unittest

from pydantic import ValidationError

from preanalyzer.models.evidence import EvidenceFact
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.rule_inference import RuleInferenceSet, RuntimeCandidate


class PydanticModelTests(unittest.TestCase):
    def test_tracked_value_requires_source_and_confidence(self):
        with self.assertRaises(ValidationError):
            Tracked(value=8080)

    def test_tracked_serialization_shape_is_unchanged(self):
        tracked = Tracked(value=8080, source="dockerfile_expose", confidence=Confidence.HIGH)

        self.assertEqual(
            tracked.model_dump(),
            {"value": 8080, "source": "dockerfile_expose", "confidence": "high", "evidence_refs": []},
        )

    def test_evidence_fact_rejects_non_observed_classification(self):
        with self.assertRaises(ValidationError):
            EvidenceFact(
                evidence_id="F0001",
                fact_type="artifact_presence",
                artifact_ref="Dockerfile",
                source="artifact_inventory",
                classification="rule_inference",
                value={"path": "Dockerfile"},
            )

    def test_rule_inference_schema_available(self):
        schema = RuleInferenceSet.model_json_schema()

        self.assertEqual(schema["title"], "RuleInferenceSet")

    def test_runtime_candidate_dump_shape_is_unchanged(self):
        candidate = RuntimeCandidate(
            component_id="root",
            language="nodejs",
            framework="express",
            build_tool="npm",
            build_strategy="dockerfile",
            source="package.json",
            confidence="high",
            evidence_refs=["F0006"],
        )

        self.assertEqual(
            candidate.model_dump(),
            {
                "component_id": "root",
                "language": "nodejs",
                "framework": "express",
                "build_tool": "npm",
                "build_strategy": "dockerfile",
                "source": "package.json",
                "confidence": "high",
                "evidence_refs": ["F0006"],
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_pydantic_models -v
```

Expected before conversion: FAIL because dataclass models do not raise pydantic `ValidationError` and do not expose `model_json_schema()`.

- [ ] **Step 4: Add dependency**

Modify `pyproject.toml`:

```toml
dependencies = [
  "PyYAML>=6.0",
  "pydantic>=2.8",
]
```

- [ ] **Step 5: Convert `Tracked`**

Replace `src/preanalyzer/models/fields.py` with:

```python
from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Tracked(BaseModel, Generic[T]):
    model_config = ConfigDict(use_enum_values=True)

    value: T | None = None
    source: str | None = None
    confidence: Confidence = Confidence.NONE
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_provenance(self):
        if self.value is not None and (self.source is None or self.confidence == Confidence.NONE):
            raise ValueError("tracked values require source and non-none confidence")
        return self
```

- [ ] **Step 6: Convert model modules**

For `snapshot.py`, `inventory.py`, `evidence.py`, and `rule_inference.py`, replace dataclass imports with pydantic imports and inherit from `BaseModel`. Example pattern:

```python
from pydantic import BaseModel, Field


class RepositorySnapshot(BaseModel):
    url: str | None
    ref: str | None
    commit_sha: str | None
    analyzed_at: str
    archived: bool
    default_branch: str | None
    analyzer_version: str
    rules_version: str
    file_count: int
    excluded_patterns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

For `EvidenceFact`, add:

```python
from pydantic import BaseModel, field_validator
from typing import Any


class EvidenceFact(BaseModel):
    evidence_id: str
    fact_type: str
    artifact_ref: str
    source: str
    classification: str
    value: Any

    @field_validator("classification")
    @classmethod
    def _classification_observed(cls, value: str) -> str:
        if value != "observed_fact":
            raise ValueError("phase-1 evidence facts must be observed_fact")
        return value
```

For list defaults in pydantic models, use `Field(default_factory=list)`.

- [ ] **Step 7: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_pydantic_models -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass and existing YAML output tests remain unchanged.

Commit:

```bash
git add pyproject.toml src/preanalyzer/models tests/unit/test_pydantic_models.py
git commit -m "refactor: enforce phase1 models with pydantic"
```

## Task 6: Final Phase Verification

**Files:**
- No source changes unless verification exposes a defect.

**Interfaces:**
- Verifies `run_phase1_analysis(...)` still writes:
  - `00-repository-snapshot.yaml`
  - `01-artifact-inventory.yaml`
  - `02-evidence-model.yaml`
  - `03-rule-inference.yaml`

- [ ] **Step 1: Run full suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Inspect generated sample outputs manually**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
from preanalyzer.pipeline import run_phase1_analysis

clock = lambda: datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)
fixtures = Path("tests/fixtures/repos")
with TemporaryDirectory() as tmp:
    for repo_name in ["jpetstore-like", "fastapi-fullstack-like", "node-express-like"]:
        out = Path(tmp) / repo_name
        run_phase1_analysis(fixtures / repo_name, out, f"fixture://{repo_name}", "fixture", clock)
        rules = yaml.safe_load((out / "03-rule-inference.yaml").read_text(encoding="utf-8"))["rule_inference"]
        print(repo_name)
        print("runtime_versions:", rules.get("runtime_version_candidates", []))
        print("ports:", rules.get("runtime_port_candidates", []))
        print("commands:", rules.get("runtime_command_candidates", []))
        print("dependencies:", rules.get("dependency_edge_candidates", []))
PY
```

Expected:
- `fastapi-fullstack-like` shows Python `3.11`, Node.js `20`, ports `8000` and `5173`, commands for backend/frontend, and `backend -> db` dependency candidates.
- `node-express-like` shows Node.js `20`, port `3000`, command `["node", "server.js"]`.
- No output contains `changethis`.

- [ ] **Step 3: Confirm git state**

Run:

```bash
git status --short
git log --oneline -10
```

Expected: clean worktree and rollback-sized commits on `mvp-preanalysis-phase1`.

## Self-Review

Spec coverage:
- runtime version + port/command 후보 승격: Task 1.
- dependency edge 후보 생성: Task 2.
- malformed parser warning 처리: Task 3.
- Compose override / volume / unsupported warning: Task 4.
- pydantic 모델 전환: Task 5.
- final phase verification: Task 6.

Placeholder scan:
- No banned placeholder terms or open-ended edge handling instructions remain.

Type consistency:
- `RuntimeVersionCandidate`, `RuntimePortCandidate`, `RuntimeCommandCandidate`, and `DependencyEdgeCandidate` are added to `RuleInferenceSet` and referenced by exact attribute names in tests and implementation steps.
- Existing `RuntimeCandidate` shape is preserved for backward compatibility.
