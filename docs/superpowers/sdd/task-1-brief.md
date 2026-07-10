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

