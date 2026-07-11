# Next Semantic Task Review

## MVP Judgment

Recommendation: do not expand to a new semantic task type yet.

The current `resolve_runtime_command` MVP should be reworked and re-evaluated before adding `resolve_runtime_port`, `resolve_component_role`, or `resolve_dependency_edge`.

Grounds:

- The Fake baseline ran across 11 fixtures with 3 repetitions and was repeat-consistent.
- The actual 20B-30B on-premise model evaluation was not run because endpoint environment variables were not configured.
- Fake baseline exact command accuracy was 0.636364, below the proposed 0.80 threshold.
- Fake baseline hallucinated candidate rate was 0.181818, above the proposed 0.05 threshold.
- Evidence reference accuracy was 0.909091, barely above the proposed 0.90 threshold.
- Budget completion and schema-after-retry rates were 1.0.

## Metrics Used

- Runtime command resolution rate: 0.363636
- Exact command accuracy: 0.636364
- Evidence reference accuracy: 0.909091
- Grounded candidate rate: 0.181818
- Hallucinated candidate rate: 0.181818
- Correct tool selection rate: 0.909091
- Average tool calls: 0.363636
- Average agent turns: 0.909091
- Budget completion rate: 1.0
- Schema success after retry: 1.0
- Correct insufficient evidence rate: 1.0
- Correct ambiguous rate: 0.0
- Repeat consistency rate: 1.0
- Provider error rate: 0.0

## Keep

- The bounded state machine.
- Per-task tool allowlists.
- Read-only source tools.
- Budget tracking.
- Deterministic verifier as the only acceptance gate.
- Separate audit output that does not overwrite rule inference.
- Evaluation harness separation from normal unit tests.

## Rework Before Expansion

- Make evaluation result extraction preserve accepted semantic command values without exposing prompts, reasoning, or secrets.
- Add clearer expected-status handling for `ambiguous`, rejected hallucination, and budget-exhausted cases.
- Run the harness against at least one configured 20B-class and one 30B-class OpenAI-compatible endpoint.
- Only then tune prompt, tool descriptions, or decision context based on measured model failures.

## Candidate Review

### resolve_runtime_port

- User value: high, because ports are directly needed for service exposure.
- Frequency: high in containerized apps.
- Deterministic gap rate: likely moderate; many ports are explicit in Dockerfile or Compose.
- Required tools: existing read/search tools may be enough initially.
- Model difficulty: low to medium.
- Grounding/verifiability: strong when ports appear in source or config.
- Hallucination risk: medium, because frameworks often imply default ports.
- Implementation cost: medium.
- Fixture cost: low.
- Contract reuse: high.

### resolve_component_role

- User value: medium to high for topology.
- Frequency: high.
- Deterministic gap rate: moderate.
- Required tools: likely needs broader semantic clues from package names and routes.
- Model difficulty: medium.
- Grounding/verifiability: weaker than ports; roles are interpretive.
- Hallucination risk: high.
- Implementation cost: medium to high.
- Fixture cost: medium.
- Contract reuse: medium.

### resolve_dependency_edge

- User value: high for topology and manifests.
- Frequency: high in multi-service apps.
- Deterministic gap rate: moderate to high.
- Required tools: source search plus config inspection.
- Model difficulty: medium to high.
- Grounding/verifiability: moderate when connection strings, clients, or service names are present.
- Hallucination risk: high if inferred from names alone.
- Implementation cost: high.
- Fixture cost: high.
- Contract reuse: medium.

## Recommendation

Next task: rework `resolve_runtime_command` evaluation and run real model evaluation before adding a new task type.

If real model evaluation later passes the runtime-command MVP, the next smallest extension should be `resolve_runtime_port`, because port values are concrete, easy to ground, and easier to verify than roles or dependency edges.

## Small Step Plan

1. Improve evaluation result extraction for accepted semantic command candidates.
2. Add explicit evaluation expectations for rejected, ambiguous, and budget-exhausted outcomes.
3. Run Fake baseline again and confirm the harness itself is measuring intended outcomes.
4. Run one 20B-class and one 30B-class OpenAI-compatible model with the same fixtures.
5. Revisit TASK-09 prompt/tool optimization only if real model failures identify a specific prompt or tool-contract issue.
6. Start `resolve_runtime_port` only after the runtime-command MVP passes or has a documented exception.

## Explicit Non-Goals

- Do not add a new semantic task type now.
- Do not relax verifier rules to improve metrics.
- Do not increase budgets before showing real model need.
- Do not add repository-wide context.
- Do not generate Kubernetes YAML from semantic output.
