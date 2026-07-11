# Semantic LLM Provider Design

## Goal

Connect the existing bounded semantic agent to an OpenAI-compatible chat completions model using the OpenAI Python SDK and local environment settings.

## Scope

In scope:

- Add the `openai` Python package as a project dependency.
- Load semantic model settings from environment variables:
  - `SEMANTIC_LLM_BASE_URL`
  - `SEMANTIC_LLM_MODEL`
  - `SEMANTIC_LLM_API_KEY`
  - `SEMANTIC_LLM_TIMEOUT_SECONDS`
- Implement an OpenAI SDK-backed `AgentDecisionProvider` for `run_semantic_agent(...)`.
- Convert `SemanticDecisionContext` into a bounded prompt that asks for exactly one existing action shape:
  - `ToolCallAction`
  - `ResolutionAction`
- Parse model output through the existing Pydantic action adapter path.
- Return structured provider failures without exposing API keys or raw secret values.
- Add focused unit tests that do not call a real model.

Out of scope:

- Implementing Application Topology Model, Kubernetes Intent Model, manifest rendering, validation, deployment, smoke testing, or repair loop.
- Sending entire repositories to the model.
- Letting the model edit repositories, install dependencies, choose arbitrary tools, or bypass semantic budgets.
- Adding another provider abstraction beyond the OpenAI-compatible SDK provider.
- Persisting final semantic output artifacts beyond the current `SemanticAgentRunResult`.

## Current State

The repository already has semantic task models, bounded semantic tools, a budget-enforcing tool session, a deterministic verifier, and `run_semantic_agent(...)`.

`run_semantic_agent(...)` currently accepts any provider that implements:

```python
def decide(self, context: SemanticDecisionContext) -> AgentAction:
    ...
```

Tests use `ScriptedFakeDecisionProvider`, so the agent loop can already validate tool calls, final resolutions, budget exhaustion, and verification rejection without a real LLM.

The missing part is a production provider that uses the values in `.env.example` to call an OpenAI-compatible model.

## Design

### Configuration

Create a small settings module for semantic LLM configuration.

The loader reads only from environment variables and returns a frozen model:

- `base_url: str`
- `model: str`
- `api_key: str`
- `timeout_seconds: float`

Validation rules:

- `base_url`, `model`, and `api_key` must be non-empty.
- `timeout_seconds` defaults to a conservative value when omitted.
- invalid timeout values raise a configuration error.
- string representations of configuration errors must not include the API key.

This project does not need to parse `.env.example` directly. The file documents the required environment names; the shell or user process should load actual values into the environment before running model-backed work.

### Provider

Create `OpenAIChatDecisionProvider` in the semantic package.

It will:

- construct `OpenAI(api_key=..., base_url=..., timeout=...)`;
- call `client.chat.completions.create(...)`;
- send one developer message with strict behavioral instructions;
- send one user message containing the serialized `SemanticDecisionContext`;
- request one JSON object in the assistant message content;
- parse that JSON into the existing `AgentAction` union;
- raise `ValueError` for malformed content so `run_semantic_agent(...)` returns `invalid_action`;
- allow SDK/network/API exceptions to be caught by `run_semantic_agent(...)` as `provider_error`.

The prompt instructs the model to:

- choose exactly one action per turn;
- use only `available_tools`;
- keep tool arguments minimal;
- cite only evidence refs present in `collected_evidence` or task-visible refs;
- use low or medium confidence only;
- use `insufficient_evidence` or `ambiguous` when the evidence does not justify a resolved candidate;
- never include secret values in candidates, summaries, or tool arguments.

### Safety

The provider receives only the bounded decision context, not the full repository.

The agent loop continues to enforce:

- allowed tools;
- tool budgets;
- component-scoped file access;
- semantic verifier acceptance;
- rejection of secret-like candidates.

The provider must not log request bodies, API keys, raw model responses, or source excerpts.

### Tests

Use `unittest` and avoid real network calls.

Tests cover:

- configuration loads expected values and rejects missing required values;
- configuration errors do not include the API key;
- provider sends the configured model and bounded messages to the SDK client;
- provider parses a tool-call action from model content;
- provider parses a resolution action from model content;
- provider rejects non-JSON or schema-invalid model output.

### Verification

Implementation must follow test-first order:

1. Write the focused failing test.
2. Run the targeted test and confirm the expected failure.
3. Implement the smallest code needed.
4. Run the targeted test.
5. Run the full suite.
6. Commit implementation changes after verification.

Required final verification:

```bash
git status --short
git diff --check
git diff --stat
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

## Success Criteria

- A caller can create an OpenAI SDK-backed semantic decision provider from environment variables.
- The existing semantic agent can use that provider without changing the agent loop contract.
- Missing or invalid configuration fails before any model call.
- Malformed model output is rejected instead of guessed.
- API keys and secret values are not printed, serialized, or included in exceptions created by this feature.
- Unit tests pass without contacting a real model.
