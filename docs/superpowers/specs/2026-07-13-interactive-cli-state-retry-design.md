# Interactive CLI State Retry Design

## Summary

The interactive Kubernetes agent must keep its persisted session state aligned with what the user just did. When a user approves generation in `k8sagent start`, the session should record generated and validation progress instead of remaining at `intent_resolved`. When validation fails because of an environment or manifest problem, the same session should remain retryable rather than moving to a terminal-looking `validated` state that blocks another `validate` run.

## Background

Manual integration testing on 2026-07-13 used `tests/fixtures/repos/node-express-like` through two flows:

- Interactive wizard: `k8sagent start --no-llm`
- Session CLI: `analyze -> select --all -> answer -> generate --approve-plan -> validate`

Both flows produced manifests. With external schema download available, kubeconform passed and the aggregate result was `PARTIAL` because `kubectl` was not installed. With sandboxed network access, kubeconform failed while trying to download Kubernetes JSON schemas. That failure exposed a state policy bug: the session advanced to `validated`, so a second `validate <session-id>` was rejected with `run generate before validate`.

The interactive wizard exposed a separate persistence gap: after `approve`, it generated manifests and wrote a validation report, but the saved session still stayed at `intent_resolved` and did not record the user answers.

## Goals

- Make validation retryable after a `FAIL` result.
- Persist interactive wizard progress after approve.
- Treat `PARTIAL` as a completed validation attempt, not a hard failure.
- Keep session behavior understandable for Kubernetes infrastructure engineers who need to fix local tooling, network access, or answers and rerun validation.
- Add automated coverage for the two user-facing flows that were manually tested.

## Non-Goals

- Do not add a new session state such as `validation_failed`.
- Do not install `kubectl` or kubeconform automatically.
- Do not change the validation aggregate values: `PASS`, `PARTIAL`, and `FAIL` remain the only report outcomes.
- Do not make `kubectl_dry_run` mandatory for MVP success.
- Do not change generated Kubernetes YAML semantics.
- Do not add a new CLI framework or dependency.

## User-Facing Behavior

### Session CLI Validation

`k8sagent validate <session-id>` writes `validation/report.yaml` for every completed validation attempt.

After the report is written:

- `PASS` advances the session to `validated`.
- `PARTIAL` advances the session to `validated`.
- `FAIL` leaves the session at `generated` so the user can run `validate <session-id>` again after fixing the environment or inputs.

The existing exit codes remain:

- `PASS`: `0`
- `FAIL`: `3`
- `PARTIAL`: `4`

This means a CI-style caller can still fail on non-zero exit codes, while an operator can retry the same session after a recoverable environment failure.

### Interactive Wizard Approve

When the user runs `k8sagent start --no-llm` and enters values such as namespace, registry, and image tag:

1. The wizard saves those answers in the session.
2. `approve` writes manifests.
3. The session advances to `generated`.
4. The wizard runs validation and writes `validation/report.yaml`.
5. The session advances according to the same validation aggregate policy used by `k8sagent validate`.

For example, if kubeconform passes but `kubectl` is not installed, the wizard prints `PARTIAL` and the session is persisted as `validated`.

If kubeconform fails because Kubernetes schemas cannot be downloaded, the wizard prints `FAIL`, writes the report, and leaves the session retryable at `generated`.

## State Policy

The current state enum remains unchanged.

The policy is:

| Event | Report aggregate | Persisted state |
|---|---:|---|
| Manifests written | n/a | `generated` |
| Validation report written | `PASS` | `validated` |
| Validation report written | `PARTIAL` | `validated` |
| Validation report written | `FAIL` | `generated` |

`validated -> generated` is already an allowed transition. That existing transition can support future approved repair cycles. This spec does not require a new reverse transition for `FAIL`, because the implementation should avoid advancing to `validated` in the first place.

## Error Handling

Validation command failures are not treated as process crashes if a structured `AgentValidationReport` is produced. The report is the source of truth.

Examples:

- kubeconform schema download failure: `FAIL`, report includes kubeconform failure detail, session remains `generated`.
- invalid rendered YAML: `FAIL`, report includes YAML syntax detail, session remains `generated`.
- missing `kubectl`: `PARTIAL`, report includes `kubectl_dry_run` skipped with `tool_not_found`, session becomes `validated`.
- missing kubeconform binary: `PARTIAL`, report includes kubeconform skipped with `tool_not_found`, session becomes `validated`.

Unexpected Python exceptions still return exit code `1` through the existing CLI error path and do not claim validation completion.

## Test Requirements

Add or update tests so the following behavior is covered without real network dependency:

- Session CLI `validate` with aggregate `FAIL` writes the report and leaves state at `generated`.
- The same session can run `validate` again after a failed validation attempt.
- Session CLI `validate` with aggregate `PARTIAL` advances state to `validated` and returns exit code `4`.
- Interactive wizard `approve` persists user answers.
- Interactive wizard `approve` persists `generated` before validation and final state according to aggregate policy.
- Existing non-interactive happy path tests still pass.

Manual smoke tests may still use the real project-managed kubeconform binary, but automated regression tests must use fake validation results or fake runners for deterministic behavior.

## Acceptance Criteria

- `k8sagent validate <session-id>` no longer blocks immediate retry after a `FAIL` validation result.
- `k8sagent start --no-llm` no longer leaves an approved run at `intent_resolved`.
- `PARTIAL` remains non-zero but is stored as a completed validation attempt.
- Reports remain under `k8s-agent-output/validation/report.yaml`.
- Existing session IDs, output directories, and manifest paths remain compatible.
- No secret values are added to session files, validation reports, or logs.
