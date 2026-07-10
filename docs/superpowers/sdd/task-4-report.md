# Task 4 Report: Compose Override, Volume, And Unsupported-Key Signals

## What I implemented

### `src/preanalyzer/analyzer/parsers/compose.py`

- Added `SUPPORTED_SERVICE_KEYS = {"image", "build", "ports", "environment", "volumes", "depends_on", "labels"}` exactly per the brief.
- Refactored `parse(path)`: it now only loads the YAML document and delegates to a new `_parse_document(path, document)` helper.
- Added `_parse_document(path, document)`: extracts the `sorted(raw_services.items())` iteration that previously lived directly in `parse()`, and additionally collects `f"{name}: unsupported key {key}"` warnings (sorted via `sorted(set(raw) - SUPPORTED_SERVICE_KEYS)`) for each service, feeding them into `ParsedCompose.warnings` (which was previously always `[]`).
- Added `parse_with_override(base_path, override_path)`: loads the base YAML, and if `override_path` is not `None`, loads the override YAML and merges it via `_merge_compose_documents`, then routes the merged (or base) document through the same `_parse_document` helper used by `parse()`.
- Added `_merge_compose_documents(base, override)`: per-service shallow dict merge of the raw YAML `services` mappings — this part of the brief's example needed no adaptation since it operates purely on raw dicts, before `_parse_service` runs.

**Adaptation notes vs. the brief's illustrative Step 3 code:**
- The brief's example already called `_parse_service(name, raw)` with a two-argument signature and assumed a `_parse_document` helper existed. On inspection, the *real* `_parse_service(name: str, raw: dict[str, Any]) -> ComposeService` signature actually matches the brief's call shape exactly (contrary to the task instructions' warning that the brief's assumed signature was "simpler than reality" — in this case it happened to already line up). The genuinely real adaptation needed was that `_parse_document` did not exist yet and had to be extracted from `parse()`'s body rather than being pre-existing, and that `parse()`'s prior single-shot logic (`services = [_parse_service(...) for name, value in sorted(...)]`, `warnings=[]`) had to be replaced by delegating through `_parse_document`, which now also computes warnings inline within the same sorted loop (avoiding a second pass over `raw_services`).
- `ComposeService` fields (`build_context` not `build`, `volumes: list[str]`, etc.) required no changes — they were already correct and used as-is by `_parse_service`.

### `src/preanalyzer/analyzer/evidence_builder.py`

In `_append_compose_facts(...)`:
- Added, inside the existing per-service loop (after the `compose_environment` block, same indentation level), a `for volume in service.volumes: append("compose_volume", artifact_ref, "compose_volumes", {"service": service.name, "volume": volume})`.
- Added, **after** the per-service loop (one indentation level out, so it runs once per artifact rather than once per service), `for warning in parsed.warnings: append("parse_warning", artifact_ref, "compose_parser", warning)`.
- Confirmed the `append(fact_type, artifact_ref, source, value)` helper's `value: Any` parameter already accepts bare strings elsewhere in this file (e.g. `append("maven_packaging", artifact_ref, "pom.xml", parsed.packaging.value)` where `.value` is a string), so passing the raw warning string directly (per the brief's literal call shape) matches existing convention — no dict wrapping needed.
- Classification: confirmed `EvidenceFact.classification` is always set to the literal `"observed_fact"` inside the `append(...)` closure itself (line 24 of the file) — no per-call site needs to set it, and no rule_inference/P6 concerns apply since these are evidence-layer facts, not rule candidates.

## Testing

Created `tests/unit/test_compose_parser_extended.py` using the brief's Step 1 test content verbatim (unmodified — it worked as-is against the real `ComposeService`/`ParsedCompose` API, including `parsed.service("api").ports[0].container_port`).

Three tests:
1. `test_override_file_merges_service_values` — override changes `image`, base's `ports` are preserved (per-service shallow merge).
2. `test_unsupported_keys_warned_not_dropped` — `network_mode: host` on service `api` produces `parsed.warnings == ["api: unsupported key network_mode"]`.
3. `test_named_volume_recorded_as_evidence_signal` — a named volume mount on service `db` produces a `compose_volume` evidence fact with the expected shape.

### TDD Evidence

**RED** — `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.unit.test_compose_parser_extended -v`:
```
ImportError: cannot import name 'parse_with_override' from 'preanalyzer.analyzer.parsers.compose'
...
FAILED (errors=1)
```

**GREEN** — same command after implementation:
```
test_named_volume_recorded_as_evidence_signal ... ok
test_override_file_merges_service_values ... ok
test_unsupported_keys_warned_not_dropped ... ok

Ran 3 tests in 0.002s
OK
```

**Full suite** — `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`:
```
Ran 44 tests in 0.189s
OK
```
All 44 tests pass (41 pre-existing + 3 new), including the existing `unit.test_parsers.ComposeParserTests` (3 tests) and `unit.test_evidence_builder` (5 tests), confirming no regressions.

## Files changed

- `src/preanalyzer/analyzer/parsers/compose.py` — modified (added `SUPPORTED_SERVICE_KEYS`, `parse_with_override`, `_parse_document`, `_merge_compose_documents`; refactored `parse`)
- `src/preanalyzer/analyzer/evidence_builder.py` — modified (`_append_compose_facts` now emits `compose_volume` and `parse_warning` facts)
- `tests/unit/test_compose_parser_extended.py` — new

## Self-review

- **Completeness**: All three brief interfaces delivered (`parse_with_override`, unsupported-key warnings, `compose_volume`/`parse_warning` evidence facts). Edge case covered: `override_path=None` falls back to parsing the base document unchanged (exercised implicitly since `parse()` now calls `_parse_document` the same way). Per-service warning sorting and service iteration sorting (`sorted(raw_services.items())`, `sorted(set(raw) - SUPPORTED_SERVICE_KEYS)`) satisfy P10 reproducibility.
- **Quality**: Style matches existing file conventions — dataclass patterns untouched, `append(...)` calls match the existing 4-arg convention used throughout `_append_compose_facts`, sorting idioms consistent with the rest of the file (e.g. `sorted(service.environment.items())`).
- **Discipline**: Changes confined to exactly the 3 files specified in the task. No changes to `rule_inference.py`, models, or other parser files.
- **Testing**: TDD followed strictly — test written first, RED verified (ImportError), minimal implementation added, GREEN verified, full suite run once before commit. No test modifications after GREEN. Output is pristine (`OK`, no warnings/skips).
- **P5 compliance**: Unsupported keys (e.g. `network_mode`) are recorded as `parse_warning` facts, not silently dropped, and the service is still fully parsed (its other supported fields, like `image`, are present) — verified by `test_unsupported_keys_warned_not_dropped`, which checks both parsing succeeds and the warning is recorded.

## Concerns

None identified. Implementation is a direct, minimal extension of existing patterns; no ambiguity remained after reading the real files, so no scope deviations from the brief were necessary beyond the trivial and expected extraction of `_parse_document`.
