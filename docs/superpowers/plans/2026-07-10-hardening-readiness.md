# Hardening Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring hardening documentation up to date with the current code and add focused regression tests for the remaining secret-safety, Compose merge, and semantic budget proof gaps.

**Architecture:** Keep this as a readiness pass over the existing deterministic Phase 1 and semantic-support code. Documentation changes clarify boundaries; regression tests exercise public APIs first and only allow minimal production changes when a new assertion exposes an actual leak or mismatch.

**Tech Stack:** Python 3.11+, `unittest`, `PyYAML`, pydantic v2, existing parser and semantic-tool APIs.

## Global Constraints

- This work is a readiness and verification pass, not a new feature milestone.
- Preserve deterministic output behavior and secret-safety rules.
- Do not implement Gradle multi-project, Maven module, or workspace-based component discovery beyond what currently exists.
- Do not add a new parser-status output schema beyond the existing `EvidenceModel.warnings`.
- Do not implement an LLM executor, semantic orchestrator, or final semantic output artifact.
- Do not implement Kubernetes intent, template rendering, validation, deployment, or repair stages.
- Do not change public output field names unless a test demonstrates the existing field leaks data or misstates behavior.
- Keep `repository_snapshot -> artifact_inventory -> evidence_model -> rule_inference` as the completed Phase 1 pipeline boundary.
- Secret values must not appear in parser warnings, pipeline warning messages, semantic tool results, or serialized Phase 1 output.
- Use `unittest`; do not add dependencies or migrate to `pytest`.
- Use TDD for behavior changes: add the focused regression first, run it, make the smallest code or doc change needed, rerun targeted verification, run the full suite before completion, and commit each task independently.

---

## File Structure

- Modify `README.md`: replace stale "Step 7+ entirely unstarted" wording with separate sections for completed Phase 1, implemented semantic-analysis support, and unimplemented downstream manifest work. Replace the hard-coded test count sentence with command-based wording.
- Modify `docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md`: add a concise current-code status summary near the top so readers can distinguish completed, partially addressed, and open hardening work.
- Create `tests/unit/test_hardening_readiness.py`: focused regression module for the readiness gaps listed in the design:
  - parser and pipeline warning/output secret non-leakage;
  - semantic tool result secret non-leakage through the public context and execution APIs;
  - Compose override merge behavior for `command`, `entrypoint`, `healthcheck.test`, `secrets`, and `configs`;
  - structured budget status from `SemanticToolSession`.
- Modify `src/preanalyzer/analyzer/parsers/compose.py` only if the new Compose regression exposes a mismatch.
- Modify `src/preanalyzer/pipeline.py`, `src/preanalyzer/analyzer/parsers/result.py`, or parser wrappers only if warning text includes secret values.
- Modify `src/preanalyzer/semantic/tools/common.py`, individual semantic tools, or `src/preanalyzer/semantic/budget.py` only if the new regression exposes a secret leak or missing budget status.

## Task 1: Documentation Status Alignment

**Files:**
- Modify: `README.md`
- Modify: `docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md`

**Interfaces:**
- Consumes: current code boundary documented in `README.md` and the status mapping from `docs/superpowers/specs/2026-07-10-hardening-readiness-design.md`.
- Produces: documentation that clearly separates completed deterministic Phase 1, partial semantic-analysis support, and unimplemented Kubernetes manifest-generation stages.

- [ ] **Step 1: Update README implementation status**

In `README.md`, keep the current Step 0~6 table, but replace the current Step 7~15 status rows with this wording:

```markdown
| 7 | Application Topology Model 생성 | ⬜ 미착수 |
| 8 | Kubernetes Intent Model 생성 | ⬜ 미착수 |
| 9 | 불확실 값 질문 생성 (LLM 개입 시작점) | ⬜ 미착수 |
| 10 | Deployment Profile 병합 | ⬜ 미착수 |
| 11 | 템플릿 기반 매니페스트 렌더링 | ⬜ 미착수 |
| 12 | Kubernetes 유효성 검증 | ⬜ 미착수 |
| 13 | 배포 테스트 | ⬜ 미착수 |
| 14 | 스모크 테스트 | ⬜ 미착수 |
| 15 | 리페어 루프 | ⬜ 미착수 |
```

Then add this section after the Phase 1 output list and before "Phase 1이 하지 않는 것":

```markdown
## Semantic analysis support status

The repository now includes deterministic support code that prepares for a bounded semantic agent, but it does not yet run an LLM or persist a final semantic-analysis artifact.

Implemented support:
- Semantic task models and runtime-command task building for deterministic runtime gaps.
- Constrained semantic read/search/inspect tools scoped to one component.
- Deterministic semantic candidate verification.
- Task-level semantic tool budget tracking through `SemanticToolSession`.

Not implemented:
- LLM executor or semantic orchestrator.
- Persisted semantic output artifact.
- Application Topology Model.
- Kubernetes Intent Model.
- Manifest rendering, validation, deployment, smoke testing, or repair loop.
```

Replace the hard-coded sentence:

```markdown
현재 50개 테스트 전부 통과. `tests/fixtures/repos/` 아래 샘플 레포 3종(`jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`)으로 acceptance 테스트도 함께 검증된다.
```

with:

```markdown
단위 테스트와 acceptance 테스트는 아래 명령으로 함께 실행한다. `tests/fixtures/repos/` 아래 샘플 레포 3종(`jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`)이 end-to-end 검증에 사용된다.
```

Replace the current "다음 단계" paragraph with:

```markdown
Step 7(Application Topology Model) 이후의 최종 모델과 Kubernetes 산출물 생성은 아직 구현 전이다. 다만 런타임 명령처럼 결정론만으로 확정하기 어려운 일부 값을 다루기 위한 semantic task 모델, 제한된 읽기 도구, 예산 추적, 결정론적 검증기는 준비되어 있다.
```

- [ ] **Step 2: Add current-code status summary to hardening task document**

Insert this section in `docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md` immediately after the introductory block and before `## 우선순위 정의`:

```markdown
## 현재 코드 기준 상태 요약

이 문서는 원래 개선 후보를 정리한 작업 목록이며, 아래 상태는 현재 코드와 테스트 기준의 최신 판정이다.

### 완료 또는 실질적으로 반영됨

- TASK-001: Repository boundary와 symlink 안전성은 scanner와 semantic tool 경로 검증 테스트로 보호된다.
- TASK-002: 환경변수 원문과 credential-bearing URI 값은 evidence, rule inference, serialized output에서 제거된다.
- TASK-003: `workspace`와 `commit` snapshot 모드, dirty metadata, workspace hash가 구현되어 있다.
- TASK-005: 손상된 parser 입력은 pipeline 전체 실패 대신 warning으로 격리된다.
- TASK-006: Compose port 파싱은 원문 보존, IPv6, protocol, interpolation, range 미추측 동작을 포함한다.
- TASK-008: component ownership은 compose service와 package 후보를 reconcile하며 image-only service를 source root에 잘못 연결하지 않는다.
- TASK-009: semantic tool은 component scope, allowed tools, source-line/file 제한, secret redaction을 적용한다.
- TASK-010: deterministic verifier는 semantic candidate를 검증하며 secret-like candidate와 deterministic conflict를 거부한다.

### 부분 반영됨

- TASK-004: Compose override 병합은 mapping, env/label, ports, volumes, secrets, configs, command, entrypoint, healthcheck.test의 주요 정책을 구현했으며 추가 regression coverage가 필요하다.
- TASK-007: runtime command gap 분석과 semantic task routing은 구현되어 있으나 LLM executor와 persisted semantic artifact는 없다.
- TASK-012: Semantic budget ledger와 session wrapper는 구현되어 있으나 최종 semantic artifact가 없어 budget status persistence는 아직 출력 단계와 연결되지 않았다.
- TASK-013: Python requirements parsing은 include, constraints, index option, hash, editable, VCS/direct URL 분리를 지원하지만 모든 packaging ecosystem 확장은 범위 밖이다.
- TASK-014: README 일부가 현재 코드보다 뒤처져 있어 이번 readiness 작업에서 정정한다.

### 아직 열려 있음

- TASK-011: README와 작업 문서의 최신 상태 반영은 이번 readiness 작업으로 처리한다.
- Gradle multi-project, Maven module, workspace 기반 component discovery 확장.
- LLM executor, semantic orchestrator, final semantic output artifact.
- Application Topology Model, Kubernetes Intent Model, manifest rendering, validation, deployment, repair loop.
```

- [ ] **Step 3: Verify documentation diff**

Run:

```bash
git diff -- README.md docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md
git diff --check
```

Expected:
- README no longer states semantic analysis is entirely unstarted.
- README still says final topology, Kubernetes intent, manifest rendering, validation, deployment, and repair are not implemented.
- Hardening task document has an explicit current-code status section near the top.
- `git diff --check` exits 0.

- [ ] **Step 4: Commit documentation alignment**

Run:

```bash
git add README.md docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md
git commit -m "docs: align hardening readiness status"
```

## Task 2: Secret Non-Leakage Readiness Regressions

**Files:**
- Create: `tests/unit/test_hardening_readiness.py`
- Modify only if needed: `src/preanalyzer/pipeline.py`
- Modify only if needed: `src/preanalyzer/analyzer/parsers/result.py`
- Modify only if needed: `src/preanalyzer/semantic/tools/common.py`
- Modify only if needed: `src/preanalyzer/semantic/tools/read_source_range.py`
- Modify only if needed: `src/preanalyzer/semantic/tools/search_code.py`
- Modify only if needed: `src/preanalyzer/semantic/tools/inspect_entrypoint_script.py`

**Interfaces:**
- Consumes:
  - `run_phase1_analysis(repo: Path, output_dir: Path, url: str | None, ref: str | None, clock: Callable[[], datetime], mode: str = "workspace")`
  - `build_semantic_tool_context(repository_root: Path, task: SemanticTask, rules: RuleInferenceSet, evidence: EvidenceModel)`
  - `execute_semantic_tool(tool_name: SemanticToolName | str, tool_input: BaseModel | dict, context: SemanticToolExecutionContext)`
- Produces: regression coverage proving secret values do not appear in parser warnings, pipeline warnings, semantic tool results, or serialized Phase 1 output.

- [ ] **Step 1: Add focused readiness test module with secret checks**

Create `tests/unit/test_hardening_readiness.py` with:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def read_all_outputs(output_dir: Path) -> str:
    return "\n".join(
        (output_dir / filename).read_text(encoding="utf-8")
        for filename in [
            "00-repository-snapshot.yaml",
            "01-artifact-inventory.yaml",
            "02-evidence-model.yaml",
            "03-rule-inference.yaml",
        ]
    )


class HardeningReadinessSecretTests(unittest.TestCase):
    def test_phase1_outputs_and_warnings_do_not_include_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            output = root / "out"
            write(
                repo / "docker-compose.yml",
                "services:\n"
                "  api:\n"
                "    image: app\n"
                "    environment:\n"
                "      DATABASE_URL: postgresql://admin:real-password@db:5432/app\n"
                "  db:\n"
                "    image: postgres:16\n",
            )
            write(
                repo / "package.json",
                '{"scripts":{"start":"node server.js"},"password":"json-secret",\n',
            )

            _, _, evidence, _ = run_phase1_analysis(
                repo=repo,
                output_dir=output,
                url="fixture://hardening-readiness",
                ref="fixture",
                clock=fixed_clock,
            )

            serialized = read_all_outputs(output)
            warning_text = "\n".join(evidence.warnings)

        self.assertNotIn("real-password", serialized)
        self.assertNotIn("admin:real-password", serialized)
        self.assertNotIn("json-secret", serialized)
        self.assertNotIn("real-password", warning_text)
        self.assertNotIn("json-secret", warning_text)
        self.assertIn("package.json", warning_text)

    def test_semantic_tool_results_do_not_include_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "backend" / "settings.py",
                "API_TOKEN = 'semantic-secret-value'\n"
                "def serve():\n"
                "    return 'ok'\n",
            )
            write(
                repo / "backend" / "entrypoint.sh",
                "PASSWORD=entrypoint-secret\n"
                "exec python settings.py\n",
            )
            context = build_semantic_tool_context(
                repo,
                task(
                    allowed_tools=[
                        "read_source_range",
                        "search_code",
                        "inspect_entrypoint_script",
                    ],
                    max_source_lines=20,
                ),
                rules_for(),
                evidence_model("F001"),
            )

            read_result = execute_semantic_tool(
                "read_source_range",
                {"path": "settings.py", "start_line": 1, "end_line": 3},
                context,
            )
            search_result = execute_semantic_tool(
                "search_code",
                {"query": "API_TOKEN", "max_matches": 5},
                context,
            )
            inspect_result = execute_semantic_tool(
                "inspect_entrypoint_script",
                {"path": "entrypoint.sh", "max_candidates": 5},
                context,
            )

        combined = "\n".join(
            str(result.model_dump())
            for result in [read_result, search_result, inspect_result]
        )
        self.assertNotIn("semantic-secret-value", combined)
        self.assertNotIn("entrypoint-secret", combined)
        self.assertIn("[REDACTED]", combined)
```

- [ ] **Step 2: Run the targeted test**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessSecretTests -v
```

Expected:
- If current code already protects these paths, the two tests pass and no production code is needed.
- If any assertion fails, the failure output names the leaked literal. Make the smallest change in the leaking layer so that the literal is redacted or omitted while preserving existing evidence metadata.

- [ ] **Step 3: Minimal production fix if a leak is exposed**

If the failing literal appears in `EvidenceModel.warnings`, change the warning construction path to omit raw input text. For pipeline parser warnings, keep the current relative-path payload shape in `src/preanalyzer/pipeline.py`:

```python
return json.dumps(
    {
        "path": rel_path,
        "parser": warning.parser,
        "code": warning.code,
        "message": warning.message,
        "fatal": warning.fatal,
    },
    sort_keys=True,
)
```

and sanitize only `warning.message` at the parser boundary before it reaches this function. A concrete helper can live in `src/preanalyzer/analyzer/parsers/result.py`:

```python
def sanitize_warning_message(message: str) -> str:
    redacted = re.sub(
        r"(?i)(password|passwd|token|secret|api[_-]?key)(['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+",
        r"\1\2[REDACTED]",
        message,
    )
    return re.sub(
        r"(?i)(://[^:\s/@]+:)[^@\s]+(@)",
        r"\1[REDACTED]\2",
        redacted,
    )
```

Then apply it where `ParseWarning(message=...)` objects are created.

If the failing literal appears in semantic tool output, route the raw text through `redacted(...)` in `src/preanalyzer/semantic/tools/common.py` before creating observations, excerpts, or messages. Preserve evidence IDs and hashes over the redacted excerpt, as `read_source_range` already expects.

- [ ] **Step 4: Rerun targeted secret tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessSecretTests -v
```

Expected: PASS.

- [ ] **Step 5: Commit secret readiness regression**

Run:

```bash
git add tests/unit/test_hardening_readiness.py src/preanalyzer/pipeline.py src/preanalyzer/analyzer/parsers/result.py src/preanalyzer/semantic/tools/common.py src/preanalyzer/semantic/tools/read_source_range.py src/preanalyzer/semantic/tools/search_code.py src/preanalyzer/semantic/tools/inspect_entrypoint_script.py
git commit -m "test: cover hardening secret non-leakage"
```

If no production files changed, stage only `tests/unit/test_hardening_readiness.py`.

## Task 3: Compose Override Readiness Regressions

**Files:**
- Modify: `tests/unit/test_hardening_readiness.py`
- Modify only if needed: `src/preanalyzer/analyzer/parsers/compose.py`

**Interfaces:**
- Consumes:
  - `parse_with_override(base_path: Path, override_path: Path | None) -> ParsedCompose`
  - `_merge_compose_documents(base: dict, override: dict) -> dict`
- Produces: regression coverage proving implemented Compose override behavior remains compatible for `command`, `entrypoint`, `healthcheck.test`, `secrets`, and `configs`.

- [ ] **Step 1: Add Compose readiness tests**

Append to `tests/unit/test_hardening_readiness.py`:

```python
from preanalyzer.analyzer.parsers.compose import _merge_compose_documents, parse_with_override


class HardeningReadinessComposeMergeTests(unittest.TestCase):
    def test_command_entrypoint_and_healthcheck_test_are_replaced(self):
        base = {
            "services": {
                "api": {
                    "image": "api",
                    "command": ["python", "old.py"],
                    "entrypoint": ["/old-entrypoint.sh"],
                    "healthcheck": {
                        "test": ["CMD", "curl", "-f", "http://localhost/old"],
                        "interval": "10s",
                        "timeout": "5s",
                    },
                }
            }
        }
        override = {
            "services": {
                "api": {
                    "command": ["python", "new.py"],
                    "entrypoint": ["/new-entrypoint.sh"],
                    "healthcheck": {
                        "test": ["CMD-SHELL", "curl -f http://localhost/new"],
                    },
                }
            }
        }

        merged = _merge_compose_documents(base, override)
        api = merged["services"]["api"]

        self.assertEqual(api["command"], ["python", "new.py"])
        self.assertEqual(api["entrypoint"], ["/new-entrypoint.sh"])
        self.assertEqual(api["healthcheck"]["test"], ["CMD-SHELL", "curl -f http://localhost/new"])
        self.assertEqual(api["healthcheck"]["interval"], "10s")
        self.assertEqual(api["healthcheck"]["timeout"], "5s")

    def test_secrets_and_configs_merge_by_source_or_target(self):
        base = {
            "services": {
                "api": {
                    "image": "api",
                    "secrets": [
                        {"source": "db_password", "target": "db_password"},
                        {"source": "api_token", "target": "api_token"},
                    ],
                    "configs": [
                        {"source": "app_config", "target": "/etc/app/config.yml"},
                        "shared_config",
                    ],
                }
            },
            "secrets": {
                "db_password": {"file": "./db.txt"},
                "api_token": {"file": "./api-token.txt"},
            },
            "configs": {
                "app_config": {"file": "./config.yml"},
                "shared_config": {"file": "./shared.yml"},
            },
        }
        override = {
            "services": {
                "api": {
                    "secrets": [
                        {"source": "db_password", "target": "database_password"},
                        {"source": "session_key", "target": "session_key"},
                    ],
                    "configs": [
                        {"source": "app_config", "target": "/etc/app/config.yml", "mode": 292},
                        "worker_config",
                    ],
                }
            },
            "secrets": {
                "session_key": {"file": "./session.txt"},
            },
            "configs": {
                "worker_config": {"file": "./worker.yml"},
            },
        }

        merged = _merge_compose_documents(base, override)
        api = merged["services"]["api"]

        self.assertEqual(
            api["secrets"],
            [
                {"source": "db_password", "target": "database_password"},
                {"source": "api_token", "target": "api_token"},
                {"source": "session_key", "target": "session_key"},
            ],
        )
        self.assertEqual(
            api["configs"],
            [
                {"source": "app_config", "target": "/etc/app/config.yml", "mode": 292},
                "shared_config",
                "worker_config",
            ],
        )
        self.assertEqual(merged["secrets"]["db_password"], {"file": "./db.txt"})
        self.assertEqual(merged["secrets"]["session_key"], {"file": "./session.txt"})
        self.assertEqual(merged["configs"]["worker_config"], {"file": "./worker.yml"})

    def test_parse_with_override_does_not_warn_for_implemented_merge_only_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            base.write_text(
                "services:\n"
                "  api:\n"
                "    image: api\n"
                "    command: [\"python\", \"old.py\"]\n"
                "    entrypoint: [\"/old-entrypoint.sh\"]\n"
                "    healthcheck:\n"
                "      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost/old\"]\n"
                "    secrets:\n"
                "      - source: db_password\n"
                "        target: db_password\n"
                "    configs:\n"
                "      - source: app_config\n"
                "        target: /etc/app/config.yml\n",
                encoding="utf-8",
            )
            override.write_text(
                "services:\n"
                "  api:\n"
                "    command: [\"python\", \"new.py\"]\n"
                "    entrypoint: [\"/new-entrypoint.sh\"]\n"
                "    healthcheck:\n"
                "      test: [\"CMD-SHELL\", \"curl -f http://localhost/new\"]\n"
                "    secrets:\n"
                "      - source: session_key\n"
                "        target: session_key\n"
                "    configs:\n"
                "      - worker_config\n",
                encoding="utf-8",
            )

            parsed = parse_with_override(base, override)

        self.assertEqual(parsed.warnings, [])
        self.assertEqual(parsed.service("api").image, "api")
```

- [ ] **Step 2: Run the targeted Compose readiness tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessComposeMergeTests -v
```

Expected:
- The internal merge behavior tests pass if `compose.py` already implements the design.
- If `test_parse_with_override_does_not_warn_for_implemented_merge_only_keys` fails with warnings like `api: unsupported key command`, update `SUPPORTED_SERVICE_KEYS` in `src/preanalyzer/analyzer/parsers/compose.py` to include keys that are intentionally supported for merge semantics even though they are not exposed on `ComposeService`.

- [ ] **Step 3: Minimal Compose parser fix if unsupported-key warnings are emitted**

If the public parser emits warnings for implemented merge-only keys, change `SUPPORTED_SERVICE_KEYS` to:

```python
SUPPORTED_SERVICE_KEYS = {
    "image",
    "build",
    "ports",
    "environment",
    "volumes",
    "depends_on",
    "labels",
    "command",
    "entrypoint",
    "healthcheck",
    "secrets",
    "configs",
}
```

Do not add `command`, `entrypoint`, `healthcheck`, `secrets`, or `configs` fields to `ComposeService` in this readiness task. The design only requires warning and merge-policy coverage.

- [ ] **Step 4: Rerun Compose readiness tests and existing Compose merge tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessComposeMergeTests tests.unit.test_compose_merge -v
```

Expected: PASS.

- [ ] **Step 5: Commit Compose readiness regression**

Run:

```bash
git add tests/unit/test_hardening_readiness.py src/preanalyzer/analyzer/parsers/compose.py
git commit -m "test: cover hardening compose merge readiness"
```

If `compose.py` did not change, stage only `tests/unit/test_hardening_readiness.py`.

## Task 4: Semantic Budget Status Readiness Regression

**Files:**
- Modify: `tests/unit/test_hardening_readiness.py`
- Modify only if needed: `src/preanalyzer/semantic/budget.py`

**Interfaces:**
- Consumes:
  - `SemanticToolSession(context: SemanticToolExecutionContext, budget: SemanticTaskBudget | None = None, executor=execute_semantic_tool)`
  - `SemanticToolSession.call(tool_name: SemanticToolName | str, tool_input) -> SemanticToolResult`
  - `SemanticToolSession.budget_status() -> dict`
- Produces: regression coverage proving budget status remains available from the session wrapper after budget exhaustion.

- [ ] **Step 1: Add semantic budget readiness test**

Append to `tests/unit/test_hardening_readiness.py`:

```python
from preanalyzer.models.semantic import SemanticTaskBudget
from preanalyzer.models.semantic_tools import SemanticToolResultStatus
from preanalyzer.semantic.budget import SemanticToolSession


class HardeningReadinessSemanticBudgetTests(unittest.TestCase):
    def test_semantic_tool_session_reports_budget_status_after_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('one')\nprint('two')\n")
            context = build_semantic_tool_context(
                repo,
                task(allowed_tools=["read_source_range"], max_source_lines=10),
                rules_for(),
                evidence_model("F001"),
            )
            session = SemanticToolSession(
                context,
                budget=SemanticTaskBudget(max_tool_calls=1, max_source_lines=10),
            )

            first = session.call(
                "read_source_range",
                {"path": "app.py", "start_line": 1, "end_line": 1},
            )
            second = session.call(
                "read_source_range",
                {"path": "app.py", "start_line": 2, "end_line": 2},
            )
            status = session.budget_status()

        self.assertEqual(first.status, SemanticToolResultStatus.OK.value)
        self.assertEqual(second.status, SemanticToolResultStatus.BUDGET_EXHAUSTED.value)
        self.assertEqual(status["status"], "budget_exhausted")
        self.assertEqual(status["reason"], "max_tool_calls")
        self.assertEqual(status["budget"]["max_tool_calls"], 1)
        self.assertEqual(status["budget"]["used_tool_calls"], 1)
        self.assertEqual(status["budget"]["used_files_read"], 1)
        self.assertEqual(status["budget"]["used_source_lines"], 1)
        self.assertTrue(status["partial_evidence_preserved"])
```

- [ ] **Step 2: Run semantic budget readiness test**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessSemanticBudgetTests -v
```

Expected: PASS if `SemanticToolSession.budget_status()` is still available and structured as designed.

- [ ] **Step 3: Minimal budget wrapper fix if status is missing or incomplete**

If the test fails because `budget_status()` is missing or lacks fields, implement this method in `src/preanalyzer/semantic/budget.py`:

```python
def budget_status(self) -> dict:
    """Structured budget usage for the final semantic output."""
    return {
        "status": "budget_exhausted" if self.exhausted else "within_budget",
        "reason": self._exhausted_reason,
        "budget": {
            "max_tool_calls": self.budget.max_tool_calls,
            "used_tool_calls": self.ledger.tool_calls,
            "max_distinct_tools": self.budget.max_distinct_tools,
            "used_distinct_tools": len(self.ledger.distinct_tools),
            "max_files_read": self.budget.max_files_read,
            "used_files_read": len(self.ledger.files_read),
            "max_source_lines": self.budget.max_source_lines,
            "used_source_lines": self.ledger.source_lines_returned,
            "max_schema_retries": self.budget.max_schema_retries,
            "used_schema_retries": self.ledger.schema_retries,
        },
        "partial_evidence_preserved": True,
    }
```

Do not introduce a persisted semantic output artifact in this task.

- [ ] **Step 4: Rerun semantic budget readiness and existing budget tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness.HardeningReadinessSemanticBudgetTests tests.unit.test_semantic_budget -v
```

Expected: PASS.

- [ ] **Step 5: Commit semantic budget readiness regression**

Run:

```bash
git add tests/unit/test_hardening_readiness.py src/preanalyzer/semantic/budget.py
git commit -m "test: cover semantic budget readiness status"
```

If `budget.py` did not change, stage only `tests/unit/test_hardening_readiness.py`.

## Task 5: Final Verification

**Files:**
- Inspect: all files changed by Tasks 1~4.

**Interfaces:**
- Consumes: committed task changes.
- Produces: final verified readiness pass with no unrelated generated files staged.

- [ ] **Step 1: Inspect working tree and diff**

Run:

```bash
git status --short
git diff --check
git diff --stat
git diff
```

Expected:
- No `.venv/`, `__pycache__/`, `*.pyc`, or generated output is staged.
- Diff contains only documentation readiness updates, focused regression tests, and any minimal fixes required by those tests.
- `git diff --check` exits 0.

- [ ] **Step 2: Run focused readiness tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_hardening_readiness -v
```

Expected: PASS.

- [ ] **Step 3: Run related existing tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_env_secret_redaction tests.unit.test_compose_merge tests.unit.test_semantic_budget tests.unit.semantic_tools.test_read_source_range tests.unit.semantic_tools.test_search_code tests.unit.semantic_tools.test_inspect_entrypoint_script -v
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit final verification metadata only if there are remaining tracked changes**

If Task 5 inspection reveals a small tracked correction, commit it with:

```bash
git add README.md docs/tasks/k8s-deploy-workflow-hardening/202607101744/tasks.md tests/unit/test_hardening_readiness.py src/preanalyzer/analyzer/parsers/compose.py src/preanalyzer/pipeline.py src/preanalyzer/analyzer/parsers/result.py src/preanalyzer/semantic/tools/common.py src/preanalyzer/semantic/tools/read_source_range.py src/preanalyzer/semantic/tools/search_code.py src/preanalyzer/semantic/tools/inspect_entrypoint_script.py src/preanalyzer/semantic/budget.py
git commit -m "chore: finish hardening readiness verification"
```

If no files changed after Task 4, do not create an empty commit.

## Self-Review

- Spec coverage: Task 1 covers README and hardening task documentation. Task 2 covers secret-bearing values in warnings, pipeline output, semantic tool results, and serialized Phase 1 output. Task 3 covers Compose `command`, `entrypoint`, `healthcheck.test`, `secrets`, and `configs`. Task 4 covers semantic budget status from the session wrapper. Task 5 covers final verification.
- Placeholder scan: The plan contains concrete file paths, code blocks, commands, and expected outcomes for each task.
- Type consistency: The plan uses existing public signatures for `run_phase1_analysis`, `parse_with_override`, `_merge_compose_documents`, `build_semantic_tool_context`, `execute_semantic_tool`, and `SemanticToolSession`.
