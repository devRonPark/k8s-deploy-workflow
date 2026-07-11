# TASK-09 Evaluation Report

## Scope

TASK-09 was evaluated only against the scripted Fake Provider baseline from TASK-08.

Actual OpenAI-compatible on-premise model evaluation was not run because the required environment variables were not configured.

## Baseline Result

- Provider: `fake`
- Model: `scripted-fake`
- Fixtures: 11
- Repetitions: 3
- Repeat consistency: 1.0
- Exact command accuracy: 0.636364
- Evidence reference accuracy: 0.909091
- Hallucinated candidate rate: 0.181818
- Budget completion rate: 1.0
- Schema success after retry: 1.0
- MVP passed: false

## Observed Failure Types

- Ambiguous runtime command handling did not produce an accepted ambiguous result in the Fake baseline.
- Some deterministic direct-command fixtures do not expose a final resolved command through the semantic evaluation result shape.
- The hallucinated-command rejection fixture correctly remains rejected, but it counts against command accuracy in the current aggregate.

## Optimization Decision

No prompt, tool description, decision context, or domain-tool changes were retained.

The TASK-09 rules require a baseline, a single change, re-evaluation, and a metric comparison. The available Fake baseline is useful for harness validation but is not evidence that an on-premise model misunderstands the prompt or tool contract. Changing prompts without actual model results would be speculative.

## Next Priority

Run the same harness with real `openai_compatible` settings before making prompt or tool-contract changes. If real model results show the same failure pattern, prioritize ambiguous/insufficient resolution rules before adding tools or increasing budgets.
