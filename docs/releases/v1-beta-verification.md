# v1 Beta Verification

Date: 2026-07-15

This report records the local verification commands for Repository Assessment Beta.
The beta produces repository assessment outputs only. Kubernetes manifests are not generated in v1.

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/migration_agent -v
repository-agent assess tests/fixtures/migration_agent/node-docker
repository-agent assess tests/fixtures/migration_agent/node-compose-conflict
repository-agent assess tests/fixtures/migration_agent/node-no-dockerfile
bash scripts/verify-v1-beta.sh
```

## Results

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/migration_agent -v`: 62 tests passed.
- `.venv/bin/repository-agent assess tests/fixtures/migration_agent/node-docker --output /tmp/repository-agent-node-docker-smoke`: exit code 0.
- `.venv/bin/repository-agent assess tests/fixtures/migration_agent/node-compose-conflict --output /tmp/repository-agent-node-conflict-smoke`: exit code 0.
- `.venv/bin/repository-agent assess tests/fixtures/migration_agent/node-no-dockerfile --output /tmp/repository-agent-node-no-dockerfile-smoke`: exit code 0.
- `bash scripts/verify-v1-beta.sh`: passed.
- `bash scripts/verify-v1-beta-real-repos.sh /tmp/repository-agent-v1-beta-real-repos`: passed.

## Fixed Real Repository Probes

These SHAs were fixed from `git ls-remote <repo> HEAD` on 2026-07-15.

| Repository | Fixed Commit SHA | v1 beta role | Result |
|---|---|---|---|
| `mybatis/jpetstore-6` | `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` | Single application validation | Passed: 1 component, execution complete, 3 unknown, 0 conflicts; coverage parsed 2, partial 1, unsupported 8, ignored 1 |
| `fastapi/full-stack-fastapi-template` | `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8` | Compose/monorepo-style validation | Passed: 9 components, execution conflicted, 89 unknown, 5 conflicts; coverage parsed 8, partial 2, unsupported 15, ignored 11 |
| `GoogleCloudPlatform/microservices-demo` | `9a4616e77f0f9cbcbecaf27d711c38890dda1404` | MSA Experimental | Passed: 21 components, execution partial, 101 unknown, 1 conflict; coverage parsed 97, partial 0, unsupported 34, ignored 43 |
| `spring-petclinic/spring-petclinic-microservices` | `305a1f13e4f961001d4e6cb50a9db51dc3fc5967` | MSA Experimental | Passed: 20 components, execution partial, 124 unknown, 0 conflicts; coverage parsed 18, partial 8, unsupported 2, ignored 4 |
| `dotnet/eShop` | `9b4f9434f46fdc5c1a6e9e936af2868340cdbc48` | Polyrepo Unsupported Scope probe | Passed: 25 components, execution partial, 157 unknown, 0 conflicts; coverage parsed 57, partial 5, unsupported 4, ignored 4 |

Expected probe behavior:

- MSA Experimental repositories must not crash solely because the repository has multiple services.
- Unknowns, Conflicts, and Coverage Limits must stay visible.
- Unsupported service relationships must remain explicit instead of guessed.
- Polyrepo probes must report unsupported or partial assessment state and must not invent one application shape.
- No probe may generate Kubernetes manifests, proposals, decisions, or validation artifacts.

## Required Scenarios

- `repository-agent assess tests/fixtures/migration_agent/node-docker`: command, port, and container strategy are resolved.
- `repository-agent assess tests/fixtures/migration_agent/node-compose-conflict`: port conflict remains visible and no effective port is invented.
- `repository-agent assess tests/fixtures/migration_agent/node-no-dockerfile`: container state is unknown and no Dockerfile proposal appears.

## Quality Gates

| Gate | Result | Evidence |
|---|---|---|
| Confirmed Fact evidence coverage | 100% | `RepositoryUnderstanding.validate_evidence_links` plus `test_repository_analysis.py::test_analyze_repository_writes_discovery_and_understanding` and existing builder evidence tests require every confirmed fact to reference known evidence. |
| False fixture facts | 0 | `test_v1_beta.py` checks clear Node + Docker, port conflict, and missing Dockerfile expected states from fixture literals. |
| Conflict auto-resolution | 0 | `test_v1_beta.py::test_port_conflict_is_preserved_without_effective_port` verifies conflict candidates `[8080, 8081]` and no effective port. |
| Hidden Unknowns | 0 | `test_assessment_views.py` and CLI/e2e tests assert Unknown counts and notable unknowns appear in JSON, Markdown, and console views. |
| Manifest files generated | 0 | Capability, CLI, e2e, local verification script, and real repo verification script reject `*manifest*`, `*proposal*`, `*decision*`, and `*validation*` output files. |
| `migration_agent -> k8s_agent` imports | 0 | `tests/migration_agent/test_import_boundaries.py` scans imports under `src/migration_agent`. |
| Same-input semantic stability | 100% | `test_v1_beta.py::test_same_input_outputs_are_semantically_stable` compares two `repository-understanding.yaml` and `repository-assessment.json` outputs for the same fixture. |
