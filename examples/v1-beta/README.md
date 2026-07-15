# Repository Assessment Beta Example

Run the beta against one of the included fixtures:

```bash
repository-agent assess tests/fixtures/migration_agent/node-docker \
  --output .repository-agent/runs/node-docker
```

Inspect these generated files inside the output directory:

- `discovery.json`
- `repository-understanding.yaml`
- `repository-assessment.json`
- `repository-assessment.md`

Kubernetes manifests are not generated in v1.
