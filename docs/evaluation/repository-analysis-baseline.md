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
- local corpus version: `2026-07-14.1`
- implementation starting point: `f756f3df2d9b0aaeb460d75d1e3c26cf0435c1ee`

## Four-repository result

| Metric | Current | Gate |
|---|---:|---:|
| Core field accountability | 37.50% | 100% |
| Clear core field resolution | 42.86% | 90% |
| Clear extended field resolution | 6.67% | 80% |
| Auto-confirmed accuracy | 90.91% | 90% |
| Precise evidence-reference accuracy | 0.00% | 100% |
| Auto-confirmed fields without precise evidence | 11 | 0 |

Overall quality gate: **fail**.

Per-repository correct fields out of the ten sampled expert fields:

- `public-fastapi-fullstack`: 4/10
- `public-spring-petclinic`: 2/10
- `internal-gradle-service`: 0/10
- `internal-node-service`: 4/10

The high auto-confirmed accuracy does not mean the analysis is broadly good. It
means the old topology is usually right when it emits one of these sampled
values, while emitting too few required fields. The 37.50% accountability and
6.67% extended resolution rates expose that missing coverage.

## Fixed contract result

The committed normal, negative-finding, conflict, and Gradle coverage-gap cases
also fail the gate:

- Core field accountability: 42.86%
- Clear core field resolution: 60.00%
- Clear extended field resolution: 33.33%
- Auto-confirmed accuracy: 100.00%
- Precise evidence-reference accuracy: 0.00%
- Auto-confirmed fields without precise evidence: 4

The current path handles the straightforward Node command and port, but it does
not explicitly represent a proven Secret absence, does not preserve the two
runtime-port candidates as a conflict, and discovers `build.gradle` without
turning it into a component, dependency, framework, or port conclusion.

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
