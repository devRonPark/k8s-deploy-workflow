# Resource Generation Hold Design

## Goal

Prevent the renderer from producing invalid Kubernetes YAML when required values are unresolved. Instead, the pipeline should withhold only the affected resource, record why it was withheld, and show infrastructure engineers a clear user-facing status: `생성 보류`.

The user-facing outcome is that sample repositories with unresolved ports or other required fields do not generate broken YAML such as `port.number: "None"`. Generated manifests should be valid enough for Kubernetes schema validation, while missing decisions remain visible as actionable follow-up items.

## Audience

Primary audience:

- Kubernetes infrastructure engineers reviewing generated manifests before deployment.
- Platform engineers using sample repository validation as a trust signal for the agent.

Secondary audience:

- Contributors maintaining renderer and validation behavior.

## Scope

In scope:

- Add a renderer-level resource generation hold concept for resources whose required inputs are missing or unresolved.
- Use the user-facing Korean term `생성 보류` in reports, CLI summaries, and documentation.
- Keep a machine-readable internal status such as `deferred` or `generation_held` if useful, but do not expose `deferred` as the main user-facing label.
- Record resource path, resource kind, component id, missing field, candidate values when available, evidence references when available, and a suggested profile field to resolve the hold.
- Make kubeconform validate only the YAML files that were actually generated.
- Ensure held resources are not counted as schema validation failures.
- Preserve honest validation: if generated YAML is invalid, keep reporting `fail`.
- Add focused tests for the current edge cases:
  - `jpetstore-like` must not render an Ingress with a string `"None"` service port.
  - `port-conflict-node` must not render an Ingress with a string `"None"` service port.
  - generated YAML for those samples must not fail kubeconform due to the withheld Ingress resource.

Out of scope:

- Automatically choosing one candidate port.
- Asking the LLM to pick operational values.
- Implementing an interactive question flow.
- Changing the reconciliation policy that creates unresolved questions.
- Installing or managing `kubectl`.
- Treating a partially generated manifest set as production deploy-ready.

## Current Problem

The renderer can emit an Ingress resource even when the backing service port is unresolved. In the sample repository validation run on 2026-07-13:

- `jpetstore-like` generated `root/ingress.yaml` with an invalid service port value.
- `port-conflict-node` generated `web/ingress.yaml` with an invalid service port value.
- kubeconform correctly failed both generated resources.

This is technically honest, but it creates a poor operator experience. The invalid YAML makes the agent look like it guessed badly, even though the safer behavior is to avoid generating that resource until a human supplies the missing decision.

## Design

### Resource Generation Hold

Before rendering each resource, the renderer checks the required inputs for that resource type.

For Ingress, required inputs include:

- component has a workload or service target that can receive traffic;
- ingress host is present when the profile requests Ingress rendering;
- service port is a concrete integer;
- service name can be derived from the component.

If a required input is missing or unresolved, the renderer does not write that resource file. It records a held-resource entry instead.

User-facing label:

```text
생성 보류
```

Example report entry:

```yaml
status: generation_held
display_status: 생성 보류
resource:
  component_id: web
  kind: Ingress
  intended_path: web/ingress.yaml
reason:
  code: unresolved_service_port
  message: 서비스 포트를 확정할 수 없습니다.
  missing_field: /components/web/service/port
candidates:
  - value: 8080
    source: dockerfile_expose
  - value: 8081
    source: compose_port
suggested_resolution:
  profile_path: components.web.service.port
  message: 배포 프로필에서 web 서비스 포트를 지정하세요.
```

The exact model shape can be refined during implementation, but the report must contain enough information for a Kubernetes engineer to decide the missing value without searching through all pipeline artifacts.

### User-Facing Terminology

Use these labels in user-facing output:

| Machine status | User-facing label |
|---|---|
| `pass` | 검증 통과 |
| `fail` | 검증 실패 |
| `skipped` | 검증 건너뜀 |
| `generation_held` or `deferred` | 생성 보류 |

`deferred` is acceptable as an internal enum only if it keeps implementation simple. It should not be the primary term shown in reports or documentation.

### Validation Semantics

Kubeconform runs only against files that exist under `12-generated-manifests/`.

Held resources are not kubeconform inputs and therefore cannot produce kubeconform failures. The validation report should make the distinction explicit:

- generated invalid YAML: `검증 실패`;
- missing external tool: `검증 건너뜀`;
- intentionally unwritten resource due to unresolved inputs: `생성 보류`.

The achieved level remains conservative. If any required resource is held, the pipeline must not claim that the application is fully deploy-ready. The generated subset can still reach schema-valid status for the files that exist.

### Report Placement

Record held resources in a stable artifact that operators already inspect.

Preferred placement:

- Add a `generation_holds` section to `13-validation-report.yaml`, because this is where users inspect whether generated manifests are usable.

Optional supporting placement:

- Include the same entries or a summary in the renderer output model if a renderer artifact already exists.
- Reference related unresolved questions from `10-unresolved-questions.yaml` instead of duplicating long explanations.

### Data Flow

```text
Intent Model + Profile
        │
        ▼
Renderer checks resource prerequisites
        │
        ├── prerequisites satisfied
        │       └── write YAML under 12-generated-manifests/
        │
        └── prerequisites missing
                └── record generation hold, write no YAML for that resource

Validator runs over generated YAML only
        │
        └── 13-validation-report.yaml includes validation stages + generation_holds
```

### Error Handling

The renderer should distinguish three cases:

1. Concrete invalid data type caused by a bug or bad profile: fail fast or emit validation failure.
2. Unknown or conflicting value from analysis: hold the affected resource and report `생성 보류`.
3. Optional feature not requested by profile: do not render it and do not report it as a hold.

This keeps `생성 보류` reserved for resources the system intended to generate but could not safely generate.

### Profile Resolution

Held-resource entries should point to the profile field that would unblock generation. The implementation should use existing profile concepts where possible and avoid broad profile schema expansion unless required.

For the port conflict case, the target resolution path should be component-specific, such as:

```text
components.web.service.port
```

If the existing profile schema cannot express that field yet, the implementation plan should include the smallest schema extension needed to support explicit service port resolution.

## Tests

Use `unittest`.

Required behavior tests:

- Renderer unit test: an Ingress with unresolved service port is held and no YAML file is written.
- Renderer unit test: a valid Ingress still renders normally.
- Validation/report test: held resources appear as `생성 보류` or equivalent display status and do not mark kubeconform as failed.
- Acceptance test: `tests/fixtures/repos/port-conflict-node` records a service port question and holds the Ingress instead of rendering `"None"`.
- Acceptance test: `tests/fixtures/repos/jpetstore-like` holds the Ingress if the service port cannot be resolved.
- Regression check: generated manifest files must not contain `number: None`, `number: "None"`, or `__UNRESOLVED__` unless an explicit placeholder mode is requested.

Verification commands:

```bash
python3 scripts/ensure_kubeconform.py --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
python3 scripts/validate_context_paths.py .
```

Sample validation should also rerun the 5 fixture repositories with kubeconform available and confirm that kubeconform is not skipped.

## Success Criteria

- The renderer does not write Kubernetes YAML with unresolved required fields.
- User-facing reports use `생성 보류` instead of exposing `deferred` as the main term.
- Kubeconform validates generated YAML only and does not fail because a held resource was intentionally not written.
- Operators can see which resource was held, why, which candidates exist, and which profile field should resolve it.
- The current `jpetstore-like` and `port-conflict-node` invalid Ingress cases become generation holds rather than kubeconform schema failures caused by `"None"` ports.
- The system still reports real invalid generated YAML as `검증 실패`.
