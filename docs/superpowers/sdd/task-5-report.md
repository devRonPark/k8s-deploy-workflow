# Task 5 Report: Pydantic Model Conversion

## Design option chosen

**Option B (hybrid): pydantic dataclasses for positional-constructed classes, `BaseModel` for keyword-only ones.**

- `pydantic.dataclasses.dataclass(frozen=True)` for: `Tracked` (fields.py) and the 8 candidate
  classes + `EnvClassification` (rule_inference.py).
- `pydantic.BaseModel` for: `RepositorySnapshot`, `ArtifactInventory`, `EvidenceFact`,
  `EvidenceModel`, and `RuleInferenceSet`.

Result: **zero changes to `src/preanalyzer/analyzer/rule_inference.py`** and zero changes to the
out-of-scope parser files, because pydantic dataclasses preserve positional construction.

### Why (empirical justification)

A throwaway probe (`.venv/bin/python3`, pydantic 2.13.4) confirmed:

1. `@pydantic.dataclasses.dataclass(frozen=True)` supports **positional** construction
   (`RuntimeCandidate("root","nodejs",...)`) exactly like a stdlib dataclass, AND a
   `__post_init__` raising `ValueError` surfaces as a **`pydantic.ValidationError`** (satisfies the
   `Tracked(value=8080)` test).
2. Pydantic dataclasses have no free `.model_dump()`, so each carries a manual
   `model_dump(self) -> dict` implemented via `TypeAdapter(type(self)).dump_python(self)` — the same
   shape of change as the previous `asdict()`-based methods. Output dict matches field order and
   values exactly (including `confidence` serialized to plain `"high"` via
   `ConfigDict(use_enum_values=True)`).
3. A `BaseModel` (`RuleInferenceSet`) with **list fields typed as pydantic dataclasses** both
   generates a correct `.model_json_schema()` (title `"RuleInferenceSet"`) and serializes nested
   pydantic-dataclass fields to plain dicts of the exact current shape via native `.model_dump()`.

### The forcing constraint the brief/parent underestimated

`Tracked` is **not** dead code. It is constructed **positionally** in the out-of-scope parsers
`analyzer/parsers/dockerfile.py` and `analyzer/parsers/maven.py`
(e.g. `Tracked(int(port_text), "dockerfile_expose", Confidence.HIGH)`), and those parsers are
exercised by `test_parsers.py`, `test_parser_warnings.py`, `test_evidence_builder.py`, etc.
Converting `Tracked` to a plain `BaseModel` (brief Step 5) would break every positional call at
import/runtime. Since parsers are out of scope, `Tracked` **must** stay positional-compatible →
pydantic dataclass is the only viable choice for it. Given that, using pydantic dataclasses for the
equally-positional candidate classes is the consistent, lowest-touch continuation (Option B),
avoiding out-of-scope analyzer edits entirely.

`Tracked` also loses its `Generic[T]` parameter (now `value: Any`). This is safe: the parser
annotations `Tracked[str]` / `Tracked[int]` live under `from __future__ import annotations`, so they
are stringized and never evaluated at runtime, and no code resolves those hints. Verified by running
the full parser test suite green after the change.

## What was implemented per file

- **fields.py**: `Tracked` → `@pydantic.dataclasses.dataclass(frozen=True, config=ConfigDict(use_enum_values=True))`.
  Kept `__post_init__` provenance validator (now raises `ValidationError`); added
  `model_dump` via `TypeAdapter`. `Confidence` enum unchanged. Dropped `Generic[T]` (see above).
- **snapshot.py**: `RepositorySnapshot` → `BaseModel` (`ConfigDict(frozen=True)`), list fields via
  `Field(default_factory=list)`. Native `.model_dump()`.
- **inventory.py**: `ArtifactInventory` → `BaseModel` (frozen), all list fields `Field(default_factory=list)`.
  `ArtifactItem` alias unchanged.
- **evidence.py**: `EvidenceFact` → `BaseModel` (frozen) with `field_validator("classification")`
  rejecting anything other than `"observed_fact"`. `EvidenceModel` → `BaseModel` (frozen), keeps
  `facts_by_type()` method.
- **rule_inference.py**: 8 candidate classes + `EnvClassification` → `@pydantic.dataclasses.dataclass(frozen=True)`
  each with `classification: str = "rule_inference"` preserved as the LAST field and a `model_dump`
  via a shared `_dump()` helper. `RuleInferenceSet` → `BaseModel` (for `.model_json_schema()`), all
  candidate-list fields via `Field(default_factory=list)`, `env_classification` via
  `Field(default_factory=EnvClassification)`.
- **pyproject.toml**: added `"pydantic>=2.8"` to `dependencies`.

## What was tested and results

- Focused new test `tests/unit/test_pydantic_models.py`: **5/5 pass**.
- Full suite `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`:
  **49/49 pass** (44 pre-existing + 5 new), pristine output.

## TDD Evidence

**RED** (`python3 -m unittest tests.unit.test_pydantic_models -v`, before impl):
```
ERROR test_rule_inference_schema_available -> AttributeError: 'RuleInferenceSet' has no attribute 'model_json_schema'
ERROR test_tracked_value_requires_source_and_confidence -> ValueError (not pydantic ValidationError)
FAIL  test_evidence_fact_rejects_non_observed_classification -> ValidationError not raised
Ran 5 tests ... FAILED (failures=1, errors=2)
```

**GREEN** (same command, after impl): `Ran 5 tests ... OK`. Full suite: `Ran 49 tests ... OK`.

## Files changed

- `pyproject.toml`
- `src/preanalyzer/models/fields.py`
- `src/preanalyzer/models/snapshot.py`
- `src/preanalyzer/models/inventory.py`
- `src/preanalyzer/models/evidence.py`
- `src/preanalyzer/models/rule_inference.py`
- `tests/unit/test_pydantic_models.py` (new)

**`analyzer/rule_inference.py` was NOT touched** (Option B made Option A's call-site edits
unnecessary). No parser files touched.

## Self-review findings

- All 49 tests pass, not just the new 5 — verified with full `discover` run.
- `classification: str = "rule_inference"` preserved (name/type/default/last-field position) on all 8
  candidate classes; NOT added to `EnvClassification` or `RuleInferenceSet` (containers), matching
  the prior task's deliberate choice.
- Existing `model_dump()` shapes preserved exactly, including nested `RuleInferenceSet` dumps and
  `confidence` → `"high"` string coercion; asserted by existing `test_rule_inference.py` /
  `test_rule_runtime_candidates.py`.
- `EvidenceFact.classification` still defaults to `"observed_fact"` at every `evidence_builder.append()`
  call site (unchanged); validator does not break the 44 existing tests.
- One necessary test adaptation: the brief's `test_runtime_candidate_dump_shape_is_unchanged`
  expected dict omitted `classification`; the real class includes it (matching existing suite
  assertions), so I added `"classification": "rule_inference"` to that expected dict.
- `git diff --name-only` confirms scope is exactly the model files + pyproject + new test.

## Concerns

- Added `frozen=True` (`ConfigDict`/dataclass) to preserve the original frozen-dataclass immutability
  and hashability semantics. No code mutates these instances post-construction (all construction is
  build-and-return), so this is parity-preserving, but it is a slightly stricter contract than a bare
  `BaseModel`.
- `Tracked` is no longer generic (`value: Any`). Functionally equivalent given stringized parser
  annotations, but any future tooling that resolves `Tracked[int]` via `get_type_hints()` would need
  `Tracked` re-genericized. Not an issue for the current codebase.
