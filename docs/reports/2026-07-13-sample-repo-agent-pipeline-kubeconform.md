# 2026-07-13 Kubeconform-Required Sample Repo Validation

## Summary

This report was produced after `kubeconform` became a required agent preflight.

- Preflight command: `python3 scripts/ensure_kubeconform.py --check`
- Sample command: current branch `run_analysis(...)` over 5 fixture repositories
- Kubeconform skipped status: none
- Output root: `/tmp/kubeconform-sample-repos-8aqbb_1_`

## Results

| Sample repo | Generated YAML | Kubeconform | Achieved level | Notes |
|---|---:|---|---:|---|
| `fastapi-fullstack-like` | 8 | pass | 1 | Summary: 8 resources found in 8 files - Valid: 8, Invalid: 0, Errors: 0, Skipped: 0 |
| `fastapi-shell-entrypoint` | 4 | pass | 1 | Summary: 4 resources found in 4 files - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0 |
| `jpetstore-like` | 3 | fail | 0 | `root/ingress.yaml`: `/spec/rules/0/http/paths/0/backend/service/port/number` rendered as string `None`; kubeconform expected null or integer. |
| `node-express-like` | 4 | pass | 1 | Summary: 4 resources found in 4 files - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0 |
| `port-conflict-node` | 3 | fail | 0 | `web/ingress.yaml`: `/spec/rules/0/http/paths/0/backend/service/port/number` rendered as string `None`; kubeconform expected null or integer. |

## Interpretation

`pass` means Kubernetes schema validation ran and accepted the generated YAML.
`fail` means Kubernetes schema validation ran and found schema issues.
`skipped` is not allowed in this required-preflight validation run.

## Follow-up Findings

- The initial sandboxed run failed all 5 repos because kubeconform could not download Kubernetes JSON schemas. After rerunning with approved outbound network access, schema loading succeeded.
- `fastapi-fullstack-like`, `fastapi-shell-entrypoint`, and `node-express-like` produced Kubernetes-schema-valid YAML.
- `jpetstore-like` and `port-conflict-node` produced invalid Ingress YAML because unresolved service ports were rendered as literal `None`.
