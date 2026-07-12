# tests

## Purpose / Owns

`tests/` owns verification for the preanalyzer. `unittest` only — do not migrate
to pytest. Layout:

```text
tests/unit/                     # per-module deterministic tests
tests/acceptance/               # fixture-repo end-to-end workflows
tests/fixtures/repos/           # sample repos: jpetstore-like, fastapi-fullstack-like, node-express-like
```

Related: [src/CLAUDE.md](../src/CLAUDE.md) · [architecture.md](../docs/architecture.md).

## Common Patterns

- Model change: add valid + invalid + serialization round-trip cases in `tests/unit/`.
- Parser change: also cover the fixture path via `tests/acceptance/test_sample_repos_scanner.py`.
- Run one module vs. the whole suite:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit -p "test_scanner.py" -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

## Dependencies

- Depends on `src/preanalyzer/` (imported via `PYTHONPATH=src`) and the sample
  repos in `tests/fixtures/repos/`.
- Acceptance tests depend on `src/preanalyzer/pipeline.py` producing `00~03-*.yaml`.

> Note: acceptance tests assert exact artifact inventories, so editing a fixture's
> real build files (`tests/fixtures/repos/jpetstore-like/pom.xml`) changes expected
> output. A fixture README is not scanned as an artifact — safe to edit freely.
