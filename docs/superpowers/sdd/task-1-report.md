# Task 1 Report

## What changed

- Added `RuntimeVersionCandidate`, `RuntimePortCandidate`, and `RuntimeCommandCandidate` models.
- Added the three candidate collections to `RuleInferenceSet`.
- Promoted Dockerfile `FROM`, `EXPOSE`, and `CMD` evidence into deterministic runtime candidates with high confidence and evidence references.
- Added runtime image parsing for Python, Node.js, and Java base images.
- Added a Dockerfile path fallback for component IDs when Compose component candidates are unavailable.
- Added focused unit coverage for the FastAPI fixture.
- No changes were made to dependency edges, parser warning resilience, Compose override handling, pydantic conversion, or `evidence_builder.py`.

## Test commands and results

Focused:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_rule_runtime_candidates -v
Ran 2 tests in 0.010s
OK
```

Full suite:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
Ran 35 tests in 0.154s
OK
```

## RED/GREEN evidence

RED was captured immediately after adding the test and before production changes:

```text
AttributeError: 'RuleInferenceSet' object has no attribute 'runtime_port_candidates'
AttributeError: 'RuleInferenceSet' object has no attribute 'runtime_version_candidates'
Ran 2 tests
FAILED (errors=2)
```

After the minimal implementation, the focused test passed with 2/2 tests, followed by the full suite passing with 35/35 tests.

## Files changed

- `src/preanalyzer/models/rule_inference.py`
- `src/preanalyzer/analyzer/rule_inference.py`
- `tests/unit/test_rule_runtime_candidates.py`

`src/preanalyzer/analyzer/evidence_builder.py` and `tests/acceptance/test_phase1_deterministic_outputs.py` were not changed.

## Self-review

- Candidate lists are default-empty and preserve existing serialized output structure.
- Candidate ordering is deterministic by component and candidate value.
- Existing Compose-root matching remains preferred; the path fallback only applies to nested Dockerfile artifacts without an explicit component match.
- Unsupported or untagged base images do not produce version candidates.
- Existing tests for evidence, inference, scanning, and phase-1 outputs pass.

## Concerns

The task brief's hard-coded evidence references (`F0005`, `F0006`, `F0007`, `F0008`) do not match the current checkout's evidence numbering for its exact test setup. The focused test uses the actual deterministic references produced here (`F0007`, `F0008`, `F0009`, `F0012`). This avoids changing evidence semantics or renumbering unrelated facts.

## Review fix: Finding 1 (untested, spec-violating fallback)

`_component_for_artifact` in `src/preanalyzer/analyzer/rule_inference.py` had two extra lines beyond the original brief: when no Compose-based component matched an artifact ref, it fell back to fabricating a `component_id` from the first path segment (`artifact_ref.split("/", 1)[0]`). This violated global constraint P5 (unresolvable values must become `unresolved` + a question, never silently defaulted). Removed those two lines so the function ends with `return None`, exactly matching the original brief.

Initial removal broke two tests in `tests/unit/test_rule_runtime_candidates.py` (`test_runtime_versions_promoted_from_dockerfile_base_images`, `test_ports_and_commands_promoted_from_dockerfile`) — contrary to the review's claim that "the fastapi fixture never exercises this path." Root cause: `rules_for_fastapi()` in that file (copied verbatim from `task-1-brief.md`) never parsed `docker-compose.yml`, so component detection fell back to the pre-existing single-`root`/`"."` heuristic in `_component_candidates_from_packages`, which can never path-match `backend/Dockerfile` or `frontend/Dockerfile`. The fallback lines were the only reason those two tests passed.

Fix (per coordinator direction, matching how `tests/unit/test_rule_dependency_edges.py` already does it): updated `rules_for_fastapi()` to also parse and pass `docker-compose.yml` into `build_evidence(...)`, using `from preanalyzer.analyzer.parsers.compose import parse as parse_compose`. With real Compose-based `ComponentCandidate` entries for `backend` (`root_path="backend"`) and `frontend` (`root_path="frontend"`), `_component_for_artifact` resolves both via legitimate root-path prefix matching — no fallback/guessing required. This confirms the Finding 1 fix (deleting the two fallback lines) is correct and complete.

Adding the compose artifact shifted evidence numbering, as expected (same situation the original Task 1 implementer already handled for other evidence refs). Only one assertion actually changed: the frontend `runtime_version_candidates` entry's `evidence_refs` moved from `F0012` to `F0023` (verified by running the updated fixture builder directly and reading the assigned IDs). The three other asserted evidence refs (`F0007` backend python version, `F0008` backend port, `F0009` backend command) happened to stay the same. The new `db` compose service (`postgres:16`, no Dockerfile) does not affect any of these `assertIn`-based assertions since it produces no dockerfile-derived facts.

## Review fix: Finding 2 (missing `classification` field, P6)

Global constraint P6 requires every extracted/interpreted field to carry `value/source/confidence/classification/evidence_refs`. Added `classification: str = "rule_inference"` as the last field (with that exact default) to all 8 candidate dataclasses in `src/preanalyzer/models/rule_inference.py`: `ComponentCandidate`, `RoleCandidate`, `RuntimeCandidate`, `RuntimeVersionCandidate`, `RuntimePortCandidate`, `RuntimeCommandCandidate`, `DependencyEdgeCandidate`, `SecretCandidate`. `"rule_inference"` mirrors the existing `EvidenceFact.classification == "observed_fact"` convention for the evidence layer, applied to this pipeline stage. Because the field is defaulted and appended last, every existing positional constructor call in `src/preanalyzer/analyzer/rule_inference.py` continues to work unchanged and now emits the correct default; no call sites were touched. `EnvClassification` and `RuleInferenceSet` were left untouched (they are containers, not extracted fields), as were `evidence.py`, `fields.py`, `snapshot.py`, `inventory.py`, and parser files.

### Test files updated for the new `classification` key

- `tests/unit/test_rule_inference.py` — `component_candidates`, `runtime_candidates`, `role_candidates`, `env_classification.secret_candidates` dict assertions.
- `tests/unit/test_rule_runtime_candidates.py` — `runtime_version_candidates`, `runtime_port_candidates`, `runtime_command_candidates` dict assertions (plus the `docker-compose.yml` fixture fix and the `F0012` → `F0023` evidence-ref update described above).
- `tests/unit/test_rule_dependency_edges.py` — `dependency_edge_candidates` dict assertions.
- `tests/acceptance/test_phase1_deterministic_outputs.py` — not in the originally flagged list; found via manual grep since it asserts a `role_candidates` dict from pipeline-serialized YAML rather than a direct `model_dump()` call.

## Final verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
Ran 40 tests in 0.225s
OK
```

Pristine pass, 40/40, no warnings.
