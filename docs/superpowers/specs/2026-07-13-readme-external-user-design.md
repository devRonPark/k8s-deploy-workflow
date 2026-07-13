# README External User Design

## Goal

Revise `README.md` so a person who forks or clones this repository can quickly understand what the tool is, install it, run it against a sample repository, run it against their own repository, and understand realistic use cases and limits.

The README should be user-first. Internal architecture and development status remain available, but they should not be the first thing a new external user has to parse.

## Audience

Primary audience:

- External users evaluating the repository from GitHub.
- Users who want to try the workflow on an existing application repository before deciding whether to integrate it.

Secondary audience:

- Contributors who need links to architecture, tests, and implementation status after the first-run path is clear.

## Language And Tone

Use Korean as the main explanatory language.

Keep section headings, shell commands, output paths, and environment variable names easy for non-Korean readers to scan. Avoid marketing language and avoid claiming this is a full deployment automation product.

## Required README Shape

The README should be reorganized around this order:

1. `What is this?`
2. `When to use it`
3. `Quick Start`
4. `Run on your repository`
5. `What to inspect first`
6. `Current status and limitations`
7. `Development`
8. `Project structure`

Architecture principles can remain, but they should move below the user-facing introduction and Quick Start content.

## Product Description

Describe the project as a Kubernetes manifest pre-analysis workflow, not as a fully autonomous Kubernetes deployment system.

The first section should explain:

- It reads an application repository and extracts deployment-relevant evidence.
- It produces intermediate models, Kubernetes intent, rendered manifests, validation reports, and follow-up questions.
- It does not jump directly from repository contents to free-form YAML.
- Unknown or conflicting values stay visible as questions or unresolved fields instead of being silently guessed.

## LLM Integration

The official README path must not require an LLM for the first sample run.

The README should describe the deterministic/default path first, then add a clear section for users who want to enable an OpenAI-compatible semantic LLM provider. The LLM-backed path is an optional enhancement for bounded semantic interpretation tasks, not a prerequisite for trying the tool.

The LLM section should include these environment variables:

```bash
export SEMANTIC_LLM_BASE_URL="https://your-llm.example/v1"
export SEMANTIC_LLM_MODEL="your-model"
export SEMANTIC_LLM_API_KEY="your-key"
export SEMANTIC_LLM_TIMEOUT_SECONDS="30"
```

The README must warn users not to commit real API keys or tokens.

The README should tell users to check the endpoint's real model id before running LLM-backed analysis:

```bash
curl "$SEMANTIC_LLM_BASE_URL/models"
```

Users should set `SEMANTIC_LLM_MODEL` to a model id returned by that endpoint instead of guessing one.

Current code requires `SEMANTIC_LLM_API_KEY` to be non-empty. If a local OpenAI-compatible endpoint does not require authentication, the README should instruct users to provide a non-secret placeholder value such as `none`, while making clear that this is only for unauthenticated local endpoints that tolerate a placeholder key.

The LLM-enabled command example should use:

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --semantic-mode openai_compatible \
  --out out/node-express-like-llm
```

## Installation Design

Quick Start should use the repository-local virtual environment path already used by the project:

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 -e .
```

The README should also mention that standard `venv` plus editable install is acceptable if `uv` is unavailable, but it should not expand into a long alternative setup guide.

Manifest validation setup should remain explicit:

```bash
python3 scripts/ensure_kubeconform.py --check
```

The README must explain that `kubeconform: skipped` in `13-validation-report.yaml` means Kubernetes schema validation did not complete.

## Quick Start Design

The first runnable example should analyze an included sample repository without requiring external LLM setup:

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --no-llm \
  --out out/node-express-like
```

The README should tell users that the command prints an achieved validation level and writes analysis files under the output directory.

## Run On Your Repository Design

After the sample run, show the same flow for a user repository:

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  ./my-repo \
  --no-llm \
  --out out/my-repo
```

The README should clarify that providing a deployment profile is useful when environment-specific values such as namespace, registry, ingress host, or image tags need to be supplied.

## Outputs To Highlight

Do not force external users to understand all numbered outputs immediately. Highlight the first files they should inspect:

- `06-component-model.yaml`: detected deployable components and component boundaries.
- `10-unresolved-questions.yaml`: values the workflow could not safely decide.
- `11-deployment-profile.template.yaml`: a template for user-supplied deployment settings.
- `12-rendered-manifests.yaml`: rendered Kubernetes resources from the intent model and templates.
- `13-validation-report.yaml`: YAML, kubeconform, and kubectl validation status.

The README may mention that the full output sequence runs from `00-repository-snapshot.yaml` through `15-smoke-test-plan.yaml`, but that should be secondary.

## Use Cases

Include a short `When to use it` section with practical cases:

- Preparing an existing Node, Python/FastAPI, Java/Spring, or Compose-backed application for Kubernetes migration.
- Extracting deployment inputs such as runtime command, ports, environment variable names, volumes, and service dependencies from repository evidence.
- Separating ConfigMap and Secret candidates without exposing secret values.
- Producing CI artifacts that show how far manifest validation reached.
- Giving platform or DevOps engineers a reviewable starting point before final environment decisions are applied.

## Limitations

The README must make these limits explicit:

- This is not yet a one-command production deployment tool.
- Step 13-15 deploy check, smoke test execution, and repair loop automation are not fully implemented.
- If enabled, the LLM is bounded to semantic interpretation tasks and must not be described as directly writing final free-form Kubernetes YAML.
- Missing values are not invented; users should expect unresolved questions and profile edits.
- Kubernetes schema validation is incomplete when `kubeconform` is skipped.

## Development Section

Move contributor-focused content after the external-user flow:

- Test command.
- Project structure.
- Links to `docs/pipeline-details.md`, `docs/architecture.md`, and the full workflow design.
- Current implementation status summary.

The implementation status should stay factual: Step 12 MVP flow is connected; Step 13-15 automation remains incomplete.

## Acceptance Criteria

The README update is acceptable when:

- A new external user can identify the tool's purpose from the first section.
- Installation includes all project dependencies through editable install rather than a partial manual dependency list.
- Quick Start can be run without external LLM setup.
- A separate LLM integration section explains `--semantic-mode openai_compatible`, required `SEMANTIC_LLM_*` settings, and the unauthenticated local endpoint placeholder case.
- A sample repository command and a user repository command are both present.
- The main output files and practical use cases are easy to find.
- Limitations prevent readers from mistaking the project for finished production deployment automation.
- Existing architecture invariants are preserved: deterministic first, intermediate models before YAML, evidence before conclusions, secret safety, and bounded semantic agent.
