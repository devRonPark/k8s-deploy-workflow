# Task 6 - Final Review Fixes Report

Fixes two Important findings from the whole-branch review of "Phase 1 Deterministic
Runtime Gaps". Branch `mvp-preanalysis-phase1`.

## Fix 1: Wire compose override merging into the pipeline

### Problem
`parse_with_override` existed in `compose.py` but was never called by the pipeline.
`_parse_inventory` parsed every entry in `inventory.compose_files` independently via
`parse_compose`, so a base + override pair became two independent `ParsedCompose`
objects and produced duplicate/split compose facts.

### Implementation
File: `src/preanalyzer/pipeline.py`

- Added import `parse_with_override`.
- Replaced the flat compose loop with a call to a new `_pair_compose_files(...)`
  helper that returns a sorted list of `(base_path, override_path | None)` tuples.
- Loop: when `override_path is None` -> `parse_compose(repo / base_path)` (today's
  behavior). Otherwise -> `parse_with_override(repo / base_path, repo / override_path)`
  and the merged result is recorded under the BASE path only. The override path is
  never added to `parsed`, so `evidence_builder` sees exactly one merged
  `ParsedCompose` per directory.

### Pairing logic (`_pair_compose_files`)
- Group `inventory.compose_files` by `Path(item["path"]).parent`.
- Classify each filename (case-insensitively) into base / override / other:
  - Base: `compose.yaml`, `compose.yml`, `docker-compose.yaml`, `docker-compose.yml`
  - Override: `docker-compose.override.yaml`, `docker-compose.override.yml`
- A directory with exactly one base AND exactly one override -> emit
  `(base, override)`. Every other case (no override, orphan override with no base,
  ambiguous multi-base directory, or any "other" compose name) -> emit `(path, None)`
  for independent parsing, matching today's behavior.
- Output sorted by base path for deterministic ordering.

### evidence_builder.py — read, not touched
Confirmed `artifact_presence` facts are built from `_inventory_items(inventory)`
(inventory-derived), independent of `parsed_artifacts`. So an override file still
appears as present in the inventory facts even though it is no longer double-parsed
into its own service/build-context/depends-on facts. No change needed there. The new
integration test asserts `docker-compose.override.yml` is still present in
`artifact_presence` facts to lock this in.

### New test
`tests/unit/test_pipeline_compose_override.py` (integration-level, `TemporaryDirectory`
temp repo, not a fixture). Builds a base `docker-compose.yml` (`api`, `image: old/api`,
port `8080:80`) plus a `docker-compose.override.yml` overriding `api.image` to
`new/api`, runs `run_phase1_analysis`, and asserts:
1. Exactly ONE `compose_service` fact for `api` (no duplication).
2. Exactly one `compose_image` fact and the override won (`new/api`, never `old/api`).
3. `docker-compose.override.yml` still present via `artifact_presence`.
4. Merged service keeps the base port (container_port 80).
5. Output files written; `03-rule-inference.yaml` contains `rule_inference`.

### Existing fixtures unaffected
`find tests/fixtures/repos -iname '*compose*'` -> only
`fastapi-fullstack-like/docker-compose.yml` (single base, no override). So
`_pair_compose_files` emits `(docker-compose.yml, None)` -> `parse_compose`, the exact
old code path. Task 6 dependency-edge check reproduces the known-good values:
- `jpetstore-like`: []
- `fastapi-fullstack-like`: backend->db `database` (medium) + backend->db `internal`
  (high) = 2 entries
- `node-express-like`: []
The acceptance test `test_phase1_deterministic_outputs` also still passes.

## Fix 2: Restore `Tracked` generic parameterization

### Problem
`Tracked` had been reduced to a non-generic dataclass with `value: Any`, but
`dockerfile.py`/`maven.py` annotate fields as `Tracked[int]`/`Tracked[str]`. This only
survived because those files use `from __future__ import annotations`; any
`typing.get_type_hints()` resolution would raise
`TypeError: type 'Tracked' is not subscriptable`.

### Approach
File: `src/preanalyzer/models/fields.py`. Made `Tracked` a generic pydantic dataclass:
- Added `T = TypeVar("T")`.
- `class Tracked(Generic[T])` (still `@dataclass(frozen=True, config=...use_enum_values)`).
- Changed `value: Any = None` -> `value: T | None = None`.
- Dropped now-unused `Any` import; added `Generic, TypeVar`.

Positional construction is preserved (field order unchanged), so
`Tracked(image, "dockerfile_from", Confidence.HIGH)` calls in the untouched parser
files keep working.

### Empirical verification
Standalone prototype confirmed all four required properties:

```
positional: Tracked(value=8080, source='dockerfile_expose', confidence='high', evidence_refs=[])
positional str: Tracked(value='jar', source='pom.xml', confidence='high', evidence_refs=[])
subscript int: __main__.Tracked[int]
subscript str: __main__.Tracked[str]
dump: {'value': 8080, 'source': 'dockerfile_expose', 'confidence': 'high', 'evidence_refs': []}
validation raised: ValidationError
hints: {'expose_ports': list[__main__.Tracked[int]], 'packaging': __main__.Tracked[str]}
ALL GOOD
```

(i) positional construction works, (ii) `Tracked[int]`/`Tracked[str]` are subscriptable
and do not raise, (iii) `model_dump()` shape is byte-identical to the tested shape, and
(iv) `typing.get_type_hints()` on a class using `Tracked[int]`/`Tracked[str]` field
annotations (with no `from __future__ import annotations`) resolves cleanly.

Re-verified against the real installed module:

```
subscript int: preanalyzer.models.fields.Tracked[int]
positional: Tracked(value=8080, source='dockerfile_expose', confidence='high', evidence_refs=[])
dump: {'value': 8080, 'source': 'dockerfile_expose', 'confidence': 'high', 'evidence_refs': []}
```

`tests/unit/test_pydantic_models.py` (serialization shape + validation-error tests)
still passes unchanged.

## Full test suite

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```
Result: `Ran 50 tests ... OK` (49 pre-existing + 1 new integration test).

## Scope

Touched only `src/preanalyzer/pipeline.py`, `src/preanalyzer/models/fields.py`, and the
new test file. `dockerfile.py`, `maven.py`, `scanner.py`, `evidence_builder.py`, and
`compose.py` were read where needed but not modified. Neither Minor finding was
addressed (deferred as intended).

## Concerns
None.
