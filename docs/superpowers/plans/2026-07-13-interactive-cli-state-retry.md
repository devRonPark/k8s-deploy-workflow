# Interactive CLI State Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make interactive and session-based `k8sagent` validation state match the actual user workflow, so failed validation can be retried and approved interactive runs persist their generated/validated progress.

**Architecture:** Keep the existing `SessionState` enum and make validation aggregate policy explicit at command boundaries. Session CLI and interactive wizard should share the same persisted-state rule: `PASS`/`PARTIAL` become `validated`, while `FAIL` writes a report but leaves the session at `generated`.

**Tech Stack:** Python 3.11+, stdlib `argparse`, Pydantic v2, PyYAML, `unittest`, existing `k8sagent` session/validation/render modules. No new dependency.

## Global Constraints

- Do not add a new session state such as `validation_failed`.
- Do not change validation aggregate values or exit codes: `PASS=0`, `FAIL=3`, `PARTIAL=4`.
- Do not install `kubectl` or kubeconform automatically.
- Do not make `kubectl_dry_run` mandatory for MVP success.
- Do not change generated Kubernetes YAML semantics.
- Do not add a new CLI framework or dependency.
- Automated tests must not depend on external network or real kubeconform schema downloads.
- Keep import direction `k8sagent -> preanalyzer`; do not add reverse imports.

---

## File Scope

- Modify `src/k8sagent/cli.py`
  - Owns session CLI state transitions after `validate`.
  - Add a small local helper if needed, for example `_state_after_validation(report: AgentValidationReport) -> SessionState`.
- Modify `src/k8sagent/interactive.py`
  - Owns wizard `approve` persistence and answer recording.
  - Reuse the same validation-state policy as CLI, either by importing the helper from `k8sagent.cli` only if it does not create awkward CLI coupling, or by moving the helper to `k8sagent/session.py` if shared ownership is cleaner.
- Modify `tests/unit/agent/test_cli_agent.py`
  - Cover failed validation retry and partial state.
- Modify `tests/unit/agent/test_interactive.py`
  - Cover wizard answer persistence and final state after approve.
- Modify `tests/acceptance/test_agent_workflow.py`
  - Cover the end-to-end user scenario without network by using patched validation reports.

## Task 1: Session CLI Validation Retry Policy

### 목표

`k8sagent validate <session-id>`가 `FAIL` 리포트를 만들더라도 세션을 재검증 가능한 상태로 남긴다.

### 변경 범위

- `src/k8sagent/cli.py`
- `tests/unit/agent/test_cli_agent.py`

### 완료 조건

- `validate`가 `FAIL`이면 exit code `3`을 유지한다.
- `validation/report.yaml`은 계속 기록된다.
- 세션 상태는 `generated`로 남는다.
- 같은 세션에서 `validate`를 다시 실행할 수 있다.
- `PARTIAL`이면 exit code `4`, 세션 상태 `validated`가 된다.
- `PASS` 기존 동작은 유지된다.

### 실행할 테스트 범위

개발 중:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_cli_agent -v
```

태스크 완료 시:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_cli_agent tests.unit.agent.test_session -v
```

### 전체 테스트 필요 여부

아니오. 이 태스크는 세션형 CLI의 validate 경로에 국한된다. 전체 테스트는 Task 3 완료 후 실행한다.

### Red -> Green -> Refactor

- [ ] Red: `test_validate_fail_keeps_session_generated_and_retryable` 추가.
- [ ] Red: `test_validate_partial_marks_session_validated_and_returns_4` 추가.
- [ ] Green: `validate` 후 aggregate에 따라 저장 상태를 분기한다.
- [ ] Refactor: CLI와 interactive가 공유할 수 있는 상태 정책 helper 위치를 정리한다.

## Task 2: Interactive Wizard Approve Persistence

### 목표

`k8sagent start --no-llm`에서 사용자가 `approve`하면 답변, 생성 상태, 검증 상태가 세션에 저장되게 한다.

### 변경 범위

- `src/k8sagent/interactive.py`
- 필요 시 `src/k8sagent/session.py` 또는 `src/k8sagent/cli.py`의 상태 정책 helper
- `tests/unit/agent/test_interactive.py`

### 완료 조건

- wizard 질문 답변이 `session.answers`에 저장된다.
- `approve` 후 manifests가 쓰이면 세션이 적어도 `generated`까지 저장된다.
- validation aggregate가 `PASS` 또는 `PARTIAL`이면 최종 세션 상태가 `validated`다.
- validation aggregate가 `FAIL`이면 최종 세션 상태가 `generated`다.
- 기존 `quit`, `nl ...`, `set ...` 흐름은 깨지지 않는다.

### 실행할 테스트 범위

개발 중:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_interactive -v
```

태스크 완료 시:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_interactive tests.unit.agent.test_cli_agent -v
```

### 전체 테스트 필요 여부

아니오. Task 1과 같은 정책을 공유하므로 관련 agent unit 테스트 묶음으로 충분하다.

### Red -> Green -> Refactor

- [ ] Red: `test_scripted_wizard_persists_answers_and_validated_state_on_partial` 추가.
- [ ] Red: `test_scripted_wizard_keeps_generated_state_on_validation_fail` 추가.
- [ ] Green: 질문 답변을 누적해 session에 저장하고, approve 단계에서 generated/validated 상태를 저장한다.
- [ ] Refactor: `_approve`가 report 작성과 상태 저장 책임을 명확히 갖도록 정리한다.

## Task 3: User Flow Regression Coverage

### 목표

수동으로 확인했던 두 사용자 흐름을 자동 회귀 테스트로 고정한다.

### 변경 범위

- `tests/acceptance/test_agent_workflow.py`
- 필요 시 `tests/unit/agent/helpers.py`

### 완료 조건

- 세션형 flow가 `FAIL` 후 같은 세션으로 `validate`를 재시도할 수 있음을 acceptance 수준에서 확인한다.
- 세션형 flow가 `PARTIAL`이면 report와 session state가 일관됨을 확인한다.
- 대화형 `start` flow가 `approve` 후 manifests/report/session state를 모두 남김을 확인한다.
- 테스트는 fake validation result를 사용해 네트워크와 실제 `kubectl` 설치 여부에 의존하지 않는다.

### 실행할 테스트 범위

개발 중:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.acceptance.test_agent_workflow -v
```

태스크 완료 시:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_cli_agent tests.unit.agent.test_interactive tests.acceptance.test_agent_workflow -v
```

### 전체 테스트 필요 여부

예. 이유: CLI, interactive wizard, session store, validation report, acceptance flow가 같은 상태 정책을 공유하므로 기능 묶음 완료 시 전체 회귀 확인이 필요하다.

전체 테스트 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest discover -s tests -v
```

### Red -> Green -> Refactor

- [ ] Red: acceptance test에 failed validation retry 시나리오 추가.
- [ ] Red: acceptance test에 interactive approve persistence 시나리오 보강.
- [ ] Green: Task 1~2 구현으로 acceptance가 통과하는지 확인한다.
- [ ] Refactor: 중복된 fake report 생성이나 session 읽기 helper를 테스트 파일 안에서만 정리한다.

## Task 4: Operator-Facing Documentation

### 목표

사용자가 `PARTIAL`과 `FAIL`을 보고 다음 행동을 판단할 수 있게 README의 대화형 CLI 설명을 보강한다.

### 변경 범위

- `README.md`

### 완료 조건

- `PARTIAL`은 kubeconform 등 핵심 검증이 통과했지만 선택 검증 도구가 없어 생길 수 있음을 설명한다.
- `FAIL` 후에는 환경 또는 입력을 고친 뒤 같은 session id로 `validate`를 재실행할 수 있음을 설명한다.
- `kubectl` 미설치로 인한 `PARTIAL`과 kubeconform 실패로 인한 `FAIL`을 구분한다.
- 문서가 실제 CLI 명령과 일치한다.

### 실행할 테스트 범위

문서만 변경할 경우:

```bash
git diff --check
```

문서 예시 명령에 영향을 주는 CLI 출력 변경이 포함되면:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_cli_agent -v
```

### 전체 테스트 필요 여부

문서만 변경하면 불필요하다. CLI 출력을 추가로 바꾸면 Task 3의 전체 테스트 결과를 최종 검증으로 사용한다.

### Red -> Green -> Refactor

- [ ] Red: 해당 없음. 문서-only 작업이다.
- [ ] Green: README의 대화형 Kubernetes Agent MVP 섹션에 결과 해석과 재시도 절차를 추가한다.
- [ ] Refactor: 중복 설명을 줄이고 기존 실행 예시는 유지한다.

## Final Verification

구현 묶음 완료 후 다음을 실행한다.

```bash
git status --short
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.unit.agent.test_cli_agent tests.unit.agent.test_interactive tests.acceptance.test_agent_workflow -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest discover -s tests -v
```

Optional manual smoke test, only after automated tests pass:

```bash
K8S_AGENT_HOME=/tmp/k8sagent-smoke-home K8S_AGENT_NO_LLM=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m k8sagent start --no-llm
```

If kubeconform needs external schema downloads, rerun only the validation smoke command with approved network access and report whether the result is `PASS`, `PARTIAL`, or `FAIL`.
