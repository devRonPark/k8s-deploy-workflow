# evals

## Purpose / Owns

Agent-outcome evaluation. Measures whether the deterministic pipeline still
produces expected artifacts for each sample repo, and records a pass-rate so
agent-facing regressions are quantified.

```text
evals/run_evals.py         # runs the acceptance suite, writes the scorecard
evals/agent-results.json   # latest pass-rate scorecard (metric of record)
```

## Common Patterns

- Regenerate the scorecard after any pipeline change:

```bash
python3 evals/run_evals.py
```

- Add a task → append to `TASKS` in `evals/run_evals.py`, backed by an existing
  acceptance test so expectations never drift.

## Dependencies

- Depends on `tests/acceptance/` (see [tests/CLAUDE.md](../tests/CLAUDE.md)) and,
  transitively, `src/preanalyzer/pipeline.py`.
- Reuses the acceptance suite as ground truth — no independent assertions.

> Note: `agent-results.json` is a real, regenerable metric, not a hand-written
> number. Do not edit it by hand; run the harness. LLM-quality scoring waits for
> a real semantic executor to land.
