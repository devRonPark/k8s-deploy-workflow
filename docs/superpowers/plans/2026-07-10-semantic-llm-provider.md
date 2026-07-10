# Semantic LLM Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OpenAI SDK-backed semantic decision provider that can drive the existing bounded semantic agent from environment configuration.

**Architecture:** Keep the current `run_semantic_agent(...)` contract unchanged. Add a small environment settings loader and a focused provider that converts `SemanticDecisionContext` into one OpenAI-compatible chat completion request, then parses the assistant JSON into the existing `AgentAction` union.

**Tech Stack:** Python 3.11+, `unittest`, pydantic v2, OpenAI Python SDK, existing semantic agent models.

## Global Constraints

- Preserve deterministic Phase 1 behavior; model integration belongs only in the semantic agent provider layer.
- Do not send entire repositories to the model.
- Do not expose `SEMANTIC_LLM_API_KEY` in errors, logs, tests, or serialized output.
- Do not let the model bypass allowed tools, component-scoped access, budgets, or deterministic verification.
- Use `unittest`; do not migrate to `pytest`.
- Use TDD for production code changes.
- Add the `openai` dependency because the user explicitly selected the SDK approach.
- Do not implement topology, Kubernetes intent, manifest rendering, validation, deployment, smoke testing, or repair loop.

---

## File Structure

- Modify `pyproject.toml`: add `openai>=1.0` to project dependencies.
- Create `src/preanalyzer/semantic/llm_config.py`: environment-backed semantic LLM settings and sanitized configuration errors.
- Create `src/preanalyzer/semantic/openai_provider.py`: OpenAI SDK-backed `AgentDecisionProvider` implementation.
- Modify `src/preanalyzer/semantic/__init__.py`: export the new provider and settings helpers if useful.
- Create `tests/unit/test_semantic_llm_config.py`: configuration loading tests.
- Create `tests/unit/test_openai_decision_provider.py`: SDK request and response parsing tests using a fake client.
- Optionally update `README.md`: document how to load semantic model environment variables and instantiate the provider if the public API needs explanation.

## Task 1: Environment Settings

**Files:**
- Create: `src/preanalyzer/semantic/llm_config.py`
- Test: `tests/unit/test_semantic_llm_config.py`

**Interfaces:**
- Produces: `SemanticLLMSettings`, `SemanticLLMConfigError`, `load_semantic_llm_settings(env: Mapping[str, str] | None = None) -> SemanticLLMSettings`
- Consumes: environment variable names from `.env.example`

- [ ] **Step 1: Write the failing tests**

Add tests that assert:

- all four environment values load into a frozen settings object;
- timeout defaults when omitted;
- missing `SEMANTIC_LLM_API_KEY` raises `SemanticLLMConfigError`;
- invalid timeout raises `SemanticLLMConfigError`;
- error text never includes the provided API key.

- [ ] **Step 2: Run targeted test and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_semantic_llm_config -v
```

Expected: fails because `preanalyzer.semantic.llm_config` does not exist.

- [ ] **Step 3: Implement minimal settings loader**

Implement a frozen pydantic settings model and a loader that reads from a supplied mapping or `os.environ`.

- [ ] **Step 4: Run targeted test and confirm pass**

Run the same targeted command.

- [ ] **Step 5: Run diff check**

Run:

```bash
git diff --check
```

## Task 2: OpenAI SDK Provider

**Files:**
- Create: `src/preanalyzer/semantic/openai_provider.py`
- Test: `tests/unit/test_openai_decision_provider.py`
- Modify: `pyproject.toml`
- Modify: `src/preanalyzer/semantic/__init__.py`

**Interfaces:**
- Consumes: `SemanticLLMSettings`
- Produces: `OpenAIChatDecisionProvider(settings: SemanticLLMSettings, client: object | None = None)`
- Produces: `OpenAIChatDecisionProvider.from_env(env: Mapping[str, str] | None = None) -> OpenAIChatDecisionProvider`
- Implements: `decide(context: SemanticDecisionContext) -> AgentAction`

- [ ] **Step 1: Write the failing provider tests**

Add tests that assert:

- provider sends `model`, `messages`, `response_format={"type": "json_object"}`, and `temperature=0`;
- provider parses `{"action_type":"tool_call",...}` content into `ToolCallAction`;
- provider parses `{"action_type":"resolution",...}` content into `ResolutionAction`;
- provider raises `ValueError` for non-JSON content;
- provider raises `ValueError` for schema-invalid JSON;
- request messages do not contain the API key.

- [ ] **Step 2: Run targeted test and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_openai_decision_provider -v
```

Expected: fails because `preanalyzer.semantic.openai_provider` does not exist.

- [ ] **Step 3: Add dependency**

Add `openai>=1.0` to `pyproject.toml`.

- [ ] **Step 4: Implement provider**

Use the SDK shape from the official OpenAI Python library:

```python
from openai import OpenAI

client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_seconds)
response = client.chat.completions.create(...)
```

Parse the first choice message content as JSON and validate it through the existing `AgentAction` adapter.

- [ ] **Step 5: Export provider**

Expose settings and provider imports from `src/preanalyzer/semantic/__init__.py`.

- [ ] **Step 6: Run targeted provider test**

Run the same targeted provider test command.

## Task 3: Integration Verification and Documentation

**Files:**
- Modify: `README.md` only if needed for user-facing usage.

**Interfaces:**
- Consumes: `run_semantic_agent(...)`, `OpenAIChatDecisionProvider.from_env(...)`
- Produces: documented model-backed semantic agent usage.

- [ ] **Step 1: Add README usage note if the public entry point is not discoverable**

Document that the user should load environment variables from their local secret file and create `OpenAIChatDecisionProvider.from_env()`.

- [ ] **Step 2: Run focused semantic tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_semantic_llm_config tests.unit.test_openai_decision_provider tests.unit.test_semantic_agent -v
```

- [ ] **Step 3: Run full verification**

Run:

```bash
git status --short
git diff --check
git diff --stat
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

- [ ] **Step 4: Commit implementation changes**

Commit only the model-provider implementation, tests, dependency metadata, and related docs. Do not commit `.venv`, caches, or local secret files.

Use:

```bash
git add pyproject.toml src/preanalyzer/semantic/llm_config.py src/preanalyzer/semantic/openai_provider.py src/preanalyzer/semantic/__init__.py tests/unit/test_semantic_llm_config.py tests/unit/test_openai_decision_provider.py README.md docs/superpowers/specs/2026-07-10-semantic-llm-provider-design.md docs/superpowers/plans/2026-07-10-semantic-llm-provider.md
git commit -m "feat: add semantic OpenAI provider"
```

## Plan Self-Review

- Spec coverage: configuration, SDK provider, response parsing, safety, dependency addition, and tests are covered.
- Placeholder scan: no placeholder work remains.
- Type consistency: provider uses the existing `SemanticDecisionContext -> AgentAction` contract and keeps `run_semantic_agent(...)` unchanged.
