# src/k8sagent

Interactive Kubernetes agent orchestration layer.

## Owns

- Session lifecycle, repository acquisition, component selection, question/answer flow, manifest generation, validation reporting, and MVP interactive CLI.
- Agent-specific Intent/Topology/Validation models used after deterministic `preanalyzer` reconciliation.
- No-auth local OpenAI-compatible chat adapter for optional question phrasing, natural-language changesets, and validation repair proposals.

## Module Map

- `config.py`, `errors.py`, `procutil.py`: runtime settings, typed failures, subprocess execution with secret redaction.
- `repo.py`, `session.py`, `analysis.py`: repo checkout/copy, persisted session state machine, bridge into `preanalyzer`.
- `components.py`, `models/topology.py`, `models/intent.py`: candidate selection and intermediate agent models.
- `gaps.py`, `questions.py`, `changeset.py`: unresolved-field discovery, deterministic questions, typed path-based updates.
- `llm.py`, `corrections.py`: bounded LLM boundary. These return structured changesets/explanations only, never YAML.
- `render/`, `validate.py`: deterministic Python manifest renderers and validation aggregation.
- `cli.py`, `interactive.py`: non-interactive commands and the scripted MVP wizard.

## Invariants

- Import direction is `k8sagent -> preanalyzer`, not the reverse.
- Repository analysis remains deterministic. LLM calls cannot parse repositories, choose final values, or render manifests.
- The local LLM endpoint defaults to `http://192.168.30.167:30000/v1`, sends only `Content-Type: application/json`, discovers model IDs with `GET /models`, and does not send `Authorization`.
- Agent output lives under `k8s-agent-output/` inside the acquired repo and must stay excluded from future scans.
- Secret values are never stored, logged, sent to LLM, or rendered as Kubernetes Secret documents. Only `secretKeyRef` metadata is allowed.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/agent -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/acceptance -p "test_agent_workflow.py" -v
```
