# Repository analysis engineering baseline

## Status

This is a provisional engineering baseline, not `Demo Go` evidence. The scorecard
ran the current deterministic Phase 1 and Application Topology path against four
repositories at fixed commits. The two internal repositories are shown only by
alias; their URL, revision, source paths, and expert truth remain local.

The expert truth still needs independent review by the two Platform Engineers,
and the manual-versus-Agent timing template is intentionally `pending`. Until
those reviews and measurements are complete, these numbers must not be presented
as an unbiased final evaluation.

## Fixed evaluation inputs

- `public-fastapi-fullstack`: public Python/Node/Compose repository
- `public-spring-petclinic`: public Java/Maven/Gradle/Compose repository
- `internal-gradle-service`: private Gradle/Spring repository
- `internal-node-service`: private Node/TypeScript/Docker repository
- local corpus version: `2026-07-14.2`
- implementation starting point: `f756f3df2d9b0aaeb460d75d1e3c26cf0435c1ee`

## Four-repository result

| Metric | Current | Gate |
|---|---:|---:|
| Core field accountability | 25.00% | 100% |
| Clear core field resolution | 28.57% | 90% |
| Clear extended field resolution | 6.67% | 80% |
| Extended auto-confirmed accuracy | 50.00% | 90% |
| Precise evidence-reference accuracy | 0.00% | 100% |
| Auto-confirmed fields without precise evidence/provenance | 8 | 0 |

Overall quality gate: **fail**.

Per-repository correct fields out of the ten sampled expert fields:

- `public-fastapi-fullstack`: 3/10
- `public-spring-petclinic`: 1/10
- `internal-gradle-service`: 0/10
- `internal-node-service`: 3/10

The old topology emits too few required fields, and only half of its sampled
extended auto-confirmed values are correct. The 25.00% accountability and 6.67%
extended resolution rates expose the missing coverage without allowing correct
core values to inflate extended accuracy.

## Fixed contract result

The committed normal, negative-finding, conflict, and Gradle coverage-gap cases
also fail the gate:

- Core field accountability: 46.15%
- Clear core field resolution: 54.55%
- Clear extended field resolution: 25.00%
- Extended auto-confirmed accuracy: 100.00%
- Precise evidence-reference accuracy: 0.00%
- Auto-confirmed fields without precise evidence/provenance: 7

The current path handles straightforward Node, Maven, and Python command/port
facts, but it does not explicitly represent a proven Secret absence, preserve
the two runtime-port candidates as a conflict, or turn Gradle, Kubernetes, and
Kustomize discoveries into accountable topology conclusions.

## Reproduction and privacy

The public registry and contract data live under
`tests/fixtures/evaluation/repository_analysis/`. A local four-repository corpus
must be built with the private truth paths supplied through the environment
contracts in `repository-registry.yaml`, locked before scoring, and run with:

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.evaluation.repository_analysis \
  --corpus <local-corpus.yaml> \
  --lock <local-corpus.lock.json> \
  --repository <case-id>=<fixed-checkout> \
  --output-dir <report-dir>
```

Repeat `--repository` for all four cases. The command exits non-zero when the
quality gate fails, while still writing JSON and Markdown reports.
