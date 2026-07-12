# src — Preanalyzer

## Purpose / Owns

`src/preanalyzer/` owns the deterministic Phase-1 pipeline: it turns a repository
snapshot into evidence-backed candidate models, with **no LLM in the loop**.
Full architecture: [architecture.md](../docs/architecture.md).

Module map (load only what a task touches):

```text
src/preanalyzer/analyzer/scanner.py          # Step 0-1: snapshot + artifact inventory
src/preanalyzer/analyzer/parsers/            # Step 2: Dockerfile/compose/maven/node/python
src/preanalyzer/analyzer/evidence_builder.py # parsed data -> evidence
src/preanalyzer/analyzer/rule_inference.py   # evidence -> candidates
src/preanalyzer/models/                      # Pydantic v2 contracts
src/preanalyzer/pipeline.py                  # orchestration + YAML output
```

## Common Patterns

- Add an artifact type: extend a parser under `src/preanalyzer/analyzer/parsers/`,
  then wire evidence in `src/preanalyzer/analyzer/evidence_builder.py`.
- New candidate: emit from `src/preanalyzer/analyzer/rule_inference.py`, add its
  Pydantic model in `src/preanalyzer/models/`, keep YAML field order stable.
- Verify a change:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

## Dependencies

- Depends on nothing outside `src/`; consumed by `tests/` (see [tests/CLAUDE.md](../tests/CLAUDE.md)).
- Internal flow: `scanner → parsers → evidence_builder → rule_inference → pipeline`.
- The bounded semantic agent under `src/preanalyzer/semantic/` depends on
  `src/preanalyzer/models/semantic.py`; deterministic code decides when it runs.

> Note: never add a repository→YAML shortcut, and never let an LLM candidate
> override a high-confidence deterministic one. Secret values must never reach
> prompts, logs, or output. These invariants are load-bearing — see AGENTS.md.
