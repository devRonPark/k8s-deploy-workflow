# Codex CLI Guidelines (full)

> `AGENTS.md`의 상세 원문. AGENTS.md는 이 문서를 요약한 나침반이고, 여기가 전체 규칙이다.

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

Multi-agent execution assumes `[features] multi_agent = true`. Close completed implementer and reviewer agents.

Superpowers documents belong only in:

```text
docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
docs/superpowers/plans/YYYY-MM-DD-<topic>.md
```

Do not create task briefs, progress reports, review packages, or duplicate summaries unless explicitly requested. Reuse an existing spec or plan when possible.

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

A planning-only document should normally contain: goal and scope; assumptions and exclusions; short phases or work items; acceptance checks at the behavior level; risks or open questions.

Only use the full agent-executable planning format when the user asks for a Superpowers implementation plan, an agentic worker plan, or a plan that another coding agent should execute task-by-task.

## Working Principles

Follow the Karpathy-inspired rules:

- **Think before coding:** expose assumptions, ambiguity, and trade-offs.
- **Simplicity first:** implement the minimum required behavior.
- **Surgical changes:** every changed line must trace to the request or approved plan.
- **Goal-driven execution:** for implementation work, define success with tests and commands, then verify it. For planning-only documentation, define success by whether the document answers the requested planning question.

Do not refactor adjacent code, reformat whole files, rename unrelated symbols, or delete pre-existing dead code.

## Python and Tests

- Target Python `>=3.11`. Follow existing naming, typing, and import style. Prefer `pathlib.Path`.
- Use existing Pydantic v2 patterns. Use `Field(default_factory=...)` for mutable defaults. Preserve frozen-model behavior where already used.
- Model changes require valid, invalid, and serialization round-trip tests.
- Do not rename public fields or change YAML ordering without an approved reason.
- Do not add dependencies when the standard library or existing dependencies suffice.
- Keep `unittest`; do not migrate tests to `pytest`.

Do not modify system Python. Create the project environment when needed:

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0"
```

For production and test changes, follow true RED-GREEN-REFACTOR: write one failing test → run it and confirm the expected failure → write minimal production code → run the targeted test → refactor only while green → run the full suite.

Targeted vs. full suite:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit -p "test_<target>.py" -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

Parser changes also require the relevant fixture-based acceptance path. These test rules do not apply to planning-only documentation.

## Git and Safety

Without explicit approval, do not: push, merge, or create a PR; run destructive reset, clean, checkout, or force push; perform repository-wide formatting, large renames, or directory moves; add dependencies or change public schemas; replace the test framework.

Never commit `.venv/`, `__pycache__/`, `*.pyc`, or local generated output.

Use existing commit prefixes: `feat:` `fix:` `test:` `refactor:` `docs:` `chore:`. One commit should represent one independently verifiable purpose.

At the end of each approved implementation task, run the required verification and commit that task's changes before starting the next. If a task cannot be committed immediately, report the blocker and leave the worktree state explicit.

## Completion

Before claiming completion, apply `superpowers:verification-before-completion` and freshly run:

```bash
git status --short
git diff --check
git diff --stat
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

For planning-only documentation, run only the first three commands (no full suite).

Do not trust a subagent report without inspecting the diff and running verification yourself. Never claim an unexecuted test passed.

Final responses and meaningful progress updates must be in Korean for a non-developer. Explain user impact before technical details. Avoid unexplained terms (class names, schema, fixture, serialization, worktree, skill names). Structure:

1. **한 줄 요약** — 사용자 관점 변화
2. **처리한 내용** — 쉬운 표현, 동작 중심
3. **확인 결과** — 실행한 테스트 수·결과 (미실행은 성공으로 표현 금지)
4. **남은 사항** — 없으면 `현재 확인된 미완료 사항은 없습니다.`
5. **개발자 참고** — 변경 파일·실행 명령·커밋·기술 세부

Progress updates briefly explain: 현재 무엇을 하는지 / 발견한 문제 / 사용자 영향 / 다음 확인 대상. Do not paste raw command output unless a command failed or the user requests it. Do not mention Superpowers skill names unless asked.
