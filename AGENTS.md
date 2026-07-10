# AGENTS.md

## Scope

This file guides **Codex CLI** when developing this repository.

Assume the `Superpowers` plugin is installed. Superpowers defines the development process; this file defines project-specific constraints and verification commands.

Priority:

1. Current user request
2. This `AGENTS.md`
3. Invoked Superpowers skill
4. Approved project docs, existing tests, and code
5. Codex defaults

Surface conflicts instead of resolving them silently.

## Superpowers

Before any response or action, apply `superpowers:using-superpowers` and read the current version of every relevant skill.

| Work | Required skill |
|---|---|
| New feature or behavior change | `superpowers:brainstorming` |
| Bug or failing test | `superpowers:systematic-debugging` |
| Approved multi-step work | `superpowers:writing-plans` |
| Plan execution | `superpowers:subagent-driven-development`, or `superpowers:executing-plans` without multi-agent |
| Feature, bug fix, refactor | `superpowers:test-driven-development` |
| Before success claims or commit | `superpowers:verification-before-completion` |
| Branch completion | `superpowers:finishing-a-development-branch` |

Do not implement before a required design is approved. Do not brainstorm again when an approved spec or plan already covers the request.

For non-trivial implementation, follow `superpowers:using-git-worktrees`. Detect the environment first:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
git branch --show-current
git status --short
```

Do not create a second worktree when already inside one. Treat detached HEAD as unable to branch, push, or open a PR unless the environment proves otherwise.

Multi-agent execution assumes:

```toml
[features]
multi_agent = true
```

Close completed implementer and reviewer agents.

Superpowers documents belong only in:

```text
docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
docs/superpowers/plans/YYYY-MM-DD-<topic>.md
```

Do not create task briefs, progress reports, task reports, review packages, or duplicate summaries unless explicitly requested. Reuse an existing spec or plan when possible.

## Planning-Only Documentation

When the user asks to write, revise, summarize, or create an implementation plan document, treat that as **planning-only documentation**, not implementation.

Planning-only documentation must stay concise and must not become an execution script unless the user explicitly asks for an agent-executable plan.

For planning-only documentation:

- Do not run unit tests, acceptance tests, the full test suite, application builds, linters, or code-generation commands.
- Do not follow RED-GREEN-REFACTOR.
- Do not create or modify production code or test code.
- Do not include full test code, production code patches, expected failure text, exact `git add` commands, commit commands, or prewritten commit messages.
- Do not include exhaustive predicted file-change lists. Mention only the owned area or component when it materially helps the reader.
- Do not include step-by-step implementation recipes at the level of individual code edits.
- Do not commit planning-only documentation unless the user explicitly asks for a commit.
- Verify only the document itself: check the requested file exists, skim the diff, and run `git diff --check` after edits.

A planning-only document should normally contain:

- goal and scope;
- assumptions and exclusions;
- short phases or work items;
- acceptance checks at the behavior level;
- risks or open questions.

Only use the full agent-executable planning format when the user asks for a Superpowers implementation plan, an agentic worker plan, or a plan that another coding agent should execute task-by-task.

## Working Principles

Follow the Karpathy-inspired rules:

- **Think before coding:** expose assumptions, ambiguity, and trade-offs.
- **Simplicity first:** implement the minimum required behavior.
- **Surgical changes:** every changed line must trace to the request or approved plan.
- **Goal-driven execution:** for implementation work, define success with tests and commands, then verify it. For planning-only documentation, define success by whether the document answers the requested planning question.

Do not refactor adjacent code, reformat whole files, rename unrelated symbols, or delete pre-existing dead code.

## Project Mission

This project analyzes source repositories and produces evidence-backed inputs for Kubernetes deployment.

The goal is not fast YAML generation. The goal is **traceable, reproducible intermediate models without guessing**.

```text
repository_snapshot
→ artifact_inventory
→ evidence_model
→ rule_inference
→ semantic resolution
→ application topology
→ kubernetes intent
→ template rendering
→ validation
```

Read `README.md` to identify the currently implemented boundary. Never treat a designed but unimplemented stage as complete.

## Architecture Invariants

### Deterministic First

- Detection, parsing, normalization, evidence construction, and rule inference stay deterministic.
- Do not use an LLM where an explicit artifact can be parsed.
- Identical snapshot, ref, rules version, profile, and injected clock must produce identical output.
- Sort filesystem-derived collections and serialized output deliberately.
- Inject time instead of reading the current clock inside deterministic logic.

### Intermediate Models Before YAML

- Never add a repository-to-YAML shortcut.
- Final manifests come from a Kubernetes Intent Model and validated templates.
- Free-form LLM YAML is never a final artifact.

### Evidence Before Conclusions

Preserve:

```text
value
source
confidence
classification
evidence_refs
```

Keep observed facts, rule inference, and LLM semantic inference distinct. Do not invent defaults for unknown values. Preserve conflicts and unresolved values explicitly. LLM candidates must not silently override high-confidence deterministic candidates.

### Secret Safety

Never send Secret values, passwords, tokens, credentials, or API keys to an LLM or write them to evidence, logs, fixtures, snapshots, or generated output. Keep only the minimum metadata needed for analysis. Secret-handling changes require a non-leak regression test.

### Bounded Semantic Agent

- Deterministic code decides whether to create a `SemanticTask`.
- One task resolves one `target_field`.
- Enforce `allowed_tools` and all budgets.
- Do not load the entire repository into model context.
- The agent must not edit the target repository or install dependencies.
- Semantic candidates use `classification: llm_semantic_inference`.
- LLM confidence is limited to `low` or `medium`.
- A Deterministic Verifier decides acceptance.
- Preserve `ambiguous`, `insufficient_evidence`, `budget_exhausted`, and `tool_error`.

## Context Loading

Keep context small:

1. Read `README.md`.
2. Read only the relevant approved spec, plan, or ADR.
3. Read the target module and its tests together.
4. Inspect only immediate upstream and downstream contracts.
5. Expand scope only when evidence requires it.

Do not recursively load all source files, fixtures, or `docs/`.

```text
src/preanalyzer/analyzer/scanner.py       snapshot and inventory
src/preanalyzer/analyzer/parsers/         artifact parsing
src/preanalyzer/analyzer/evidence_builder.py
                                          parsed data → evidence
src/preanalyzer/analyzer/rule_inference.py
                                          evidence → rule candidates
src/preanalyzer/models/                   Pydantic contracts
src/preanalyzer/pipeline.py               orchestration and YAML output
tests/unit/                               unit tests
tests/acceptance/                         fixture repository workflows
```

Do not move responsibilities between layers merely to make implementation easier.

## Python and Tests

- Target Python `>=3.11`.
- Follow existing naming, typing, and import style.
- Prefer `pathlib.Path`.
- Use existing Pydantic v2 patterns.
- Use `Field(default_factory=...)` for mutable defaults.
- Preserve frozen-model behavior where already used.
- Model changes require valid, invalid, and serialization round-trip tests.
- Do not rename public fields or change YAML ordering without an approved reason.
- Do not add dependencies when the standard library or existing dependencies suffice.
- Keep `unittest`; do not migrate tests to `pytest`.

Do not modify system Python. Create the project environment when needed:

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0"
```

For production code changes and test changes, follow true RED-GREEN-REFACTOR:

```text
write one failing test
→ run it and confirm the expected failure
→ write minimal production code
→ run the targeted test
→ refactor only while green
→ run the full suite
```

Targeted test:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src   .venv/bin/python3 -m unittest discover   -s tests/unit -p "test_<target>.py" -v
```

Full suite:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src   .venv/bin/python3 -m unittest discover -s tests -v
```

Parser changes also require the relevant fixture-based acceptance path.

These test rules do not apply to planning-only documentation. Do not run the test suite merely because a plan mentions future tests.

## Git and Safety

Without explicit approval, do not:

- push, merge, or create a PR
- run destructive reset, clean, checkout, or force push
- perform repository-wide formatting, large renames, or directory moves
- add dependencies or change public schemas
- replace the test framework

Never commit `.venv/`, `__pycache__/`, `*.pyc`, or local generated output.

Use existing commit prefixes:

```text
feat:  fix:  test:  refactor:  docs:  chore:
```

One commit should represent one independently verifiable purpose.

At the end of each approved implementation task, run the required verification and commit that task's changes before starting the next task. If a task cannot be committed immediately, report the blocker and leave the worktree state explicit.

Planning-only documentation is not an implementation task. Do not commit it unless the user explicitly asks for a commit.

## Completion

Before claiming completion, apply `superpowers:verification-before-completion` and freshly run:

```bash
git status --short
git diff --check
git diff --stat
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src   .venv/bin/python3 -m unittest discover -s tests -v
```

For planning-only documentation, do not run the full verification block above. Freshly run only:

```bash
git status --short
git diff --check
git diff --stat
```

Do not trust a subagent report without inspecting the diff and running verification yourself. Never claim an unexecuted test passed.

Final responses and meaningful progress updates must be written in Korean for a non-developer.

Explain the user impact before technical details. Avoid unexplained terms such as class names, schema, fixture, serialization, worktree, or Superpowers skill names.

Use this structure:

1. **한 줄 요약**

   * 무엇이 달라졌는지 사용자 관점에서 설명

2. **처리한 내용**

   * 주요 변경사항을 쉬운 표현으로 설명
   * 파일명이나 함수명보다 실제 동작 중심으로 작성

3. **확인 결과**

   * 실행한 테스트 수와 성공·실패 결과
   * 실행하지 않은 테스트는 성공했다고 표현하지 않음

4. **남은 사항**

   * 확인하지 못한 부분, 제한사항, 실패 원인
   * 없으면 `현재 확인된 미완료 사항은 없습니다.`라고 작성

5. **개발자 참고**

   * 변경 파일
   * 실행 명령
   * 커밋 정보
   * 필요한 기술 세부사항

Progress updates should briefly explain:

* 현재 무엇을 하고 있는지
* 발견한 문제
* 사용자에게 어떤 영향이 있는지
* 다음에 무엇을 확인할지

Do not paste raw command output unless a command failed or the user requests it.
Do not mention Superpowers skill names unless the user asks about the development process.
