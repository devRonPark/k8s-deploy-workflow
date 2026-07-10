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
