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

