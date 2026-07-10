# Hardening Readiness Design

## Goal

Bring the hardening task documentation and README in line with the current code, and add focused regression tests for the remaining verification gaps.

## Scope

This work is a readiness and verification pass, not a new feature milestone.

In scope:

- Update README implementation status so users can distinguish completed Phase 1 behavior, partial semantic-analysis support, and unimplemented manifest-generation work.
- Update `docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md` with a current-code status section or checklist changes that reflect what is implemented, partially implemented, and still open.
- Add regression tests for cases that were identified as insufficiently proven:
  - secret-bearing values must not appear in parser warnings, pipeline warning messages, semantic tool results, or serialized Phase 1 output;
  - Compose override behavior for `command`, `entrypoint`, `healthcheck.test`, `secrets`, and `configs` must stay compatible with the implemented merge policy;
  - semantic budget status must remain available from the budget-enforcing session wrapper.
- Preserve deterministic output behavior and secret-safety rules.

Out of scope:

- Implementing Gradle multi-project, Maven module, or workspace-based component discovery beyond what currently exists.
- Adding a new parser-status output schema beyond the existing `EvidenceModel.warnings`.
- Implementing an LLM executor, semantic orchestrator, or final semantic output artifact.
- Implementing Kubernetes intent, template rendering, validation, deployment, or repair stages.
- Changing public output field names unless a test demonstrates the existing field leaks data or misstates behavior.

## Current State

The repository already contains hardening work for repository-boundary scanning, environment-value sanitization, snapshot modes, parser warning isolation, Compose port parsing, component ownership, semantic tools, verifier logic, semantic budget enforcement, and requirements parsing.

The README is behind the code. It describes Step 7 and later as entirely unstarted, even though semantic task building, constrained semantic tools, deterministic verification, and a budget-enforcing tool session now exist. At the same time, there is still no LLM executor or Kubernetes manifest generation, so the README must avoid presenting semantic analysis as end-to-end complete.

The hardening task document mixes original unchecked task lists with later milestone checkmarks. It needs a current-code assessment so a reader does not have to infer status from commit history and tests.

## Design

### Documentation Updates

README will keep the Phase 1 pipeline boundary clear:

```text
repository_snapshot -> artifact_inventory -> evidence_model -> rule_inference
```

It will add a separate section for semantic-analysis support:

- implemented: task models, runtime-command task builder, constrained read/search/inspect tools, deterministic verifier, budget ledger wrapper;
- not implemented: LLM executor/orchestrator, persisted semantic output artifact, topology model, Kubernetes intent, manifest rendering.

The fixed test-count sentence will be replaced with wording that points to the test command rather than a hard-coded number.

The hardening task file will get a concise status summary near the top:

- Completed or materially addressed: TASK-001, TASK-002, TASK-003, TASK-005, TASK-006, TASK-008, TASK-009, TASK-010, and major parts of TASK-004, TASK-007, TASK-012, TASK-013, TASK-014.
- Partially addressed: TASK-004, TASK-007, TASK-012, TASK-013, TASK-014.
- Still open: TASK-011 until this work updates README, plus the out-of-scope feature expansions listed above.

### Regression Tests

Add a focused test module for hardening readiness rather than scattering every assertion across existing files.

The tests will use existing public APIs:

- `run_phase1_analysis(...)` for end-to-end output checks;
- `parse_with_override(...)` for Compose merge checks;
- `build_semantic_tool_context(...)`, `execute_semantic_tool(...)`, and `SemanticToolSession` for semantic tool and budget checks.

The tests will not add dependencies and will stay on `unittest`.

### Error Handling

No new user-facing error modes are required. New tests should confirm existing errors are non-leaking and structured. If a test exposes raw host paths or secret values in output, production code will be changed minimally to sanitize that path or value.

### Verification

Each implementation task must follow test-first order:

1. Add one failing regression test.
2. Run the targeted test and confirm the expected failure.
3. Implement the smallest change needed.
4. Run the targeted test.
5. Run the full suite.
6. Commit the task.

Required final verification:

```bash
git status --short
git diff --check
git diff --stat
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

## Success Criteria

- README describes current implemented and unimplemented stages without overstating semantic or Kubernetes readiness.
- The hardening task document has an explicit current-code status summary.
- New regression tests cover secret leakage through warnings/tool results and Compose merge behavior for the previously weakly verified fields.
- Full test suite passes.
- No `.venv`, cache, generated output, or unrelated formatting changes are committed.
