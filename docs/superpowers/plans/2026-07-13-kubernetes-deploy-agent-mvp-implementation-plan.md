# Kubernetes Deploy Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. 각 태스크는 독립 브랜치 또는 독립 커밋 단위로 검토하며, 태스크 내부에서는 반드시 Red → Green → Refactor 순서를 따른다.

**Goal:** 현재 `main` 브랜치의 결정론적 사전분석 코어와 semantic runtime-command 해석 기능을 기반으로, 명시적 Source 입력부터 Deployment Profile, Kubernetes 매니페스트 생성, 정적 검증, 제한된 리페어, 중단·재개까지 수행하는 CLI-first Agent MVP를 구현한다.

**Architecture:** 기존 `src/preanalyzer`는 Repository 분석과 근거 추출을 담당하는 순수 코어로 유지한다. 신규 `src/k8s_agent` 애플리케이션 계층이 Source 확보, Run 상태, Agent 계획, 질문, Profile, 렌더링, 검증, 리페어와 CLI를 오케스트레이션한다. LLM은 기존 semantic task/tool/verifier 계층을 통해서만 호출하며, 승인된 구조화 결과는 Decision과 Deployment Profile을 거쳐야만 매니페스트에 반영된다.

**Tech Stack:** Python 3.11+, Pydantic 2.8+, PyYAML 6+, 표준 `argparse`, 표준 `subprocess`/`urllib`, Git CLI, Kustomize, kubeconform, `unittest` 기반 테스트, 선택적 pytest integration marker.

**Baseline:** 2026-07-13에 확인한 GitHub `main` 기준. 현재 Repository에는 Phase 1 산출물 `00`~`03`, `src/preanalyzer/semantic/task_builder.py`, `src/preanalyzer/semantic/verifier.py`, 제한된 semantic tool 구현과 관련 단위 테스트가 존재한다. 이 계획은 해당 기능을 재작성하지 않고 Agent 실행 경로에 통합한다.

---

## 0. 구현 전 확정할 설계 결정

1. **Source와 Agent 상태 디렉터리 분리**
   - 원본 Repository 읽기 전용 원칙을 지키기 위해 Run 저장소는 기본적으로 `${K8S_AGENT_HOME:-~/.local/state/k8s-agent}/runs/<run-id>`를 사용한다.
   - 문서의 `.k8s-agent/runs/<run-id>` 구조는 Run root 아래의 논리 구조로 유지한다.
   - 사용자가 결과물을 프로젝트에 복사하려면 `k8s-agent export <run-id> --output <path>`를 명시적으로 실행한다.

2. **MVP readiness 범위**
   - 구현 완료 목표는 `manifest-ready`다.
   - `build-verified`, `cluster-verified`는 상태 모델과 보고서 필드만 제공하고 실제 실행은 Release 2/3로 남긴다.
   - `production` Target은 Profile 생성과 정적 검증까지만 허용한다.

3. **Stateful workload 처리**
   - MVP renderer는 `Deployment`, `Service`, `ConfigMap`, Secret reference, `Ingress`, 기본 Probe, `PVC`, Kustomize를 지원한다.
   - StatefulSet이 필수인 경우 자동 생성하지 않고 사용자 질문 후 `BLOCKED` 처리한다. 사용자가 Deployment+PVC로 충분하다고 승인한 경우에만 진행한다.

4. **LLM provider 경계**
   - MVP는 OpenAI-compatible HTTP endpoint를 위한 adapter를 제공한다.
   - 로컬 endpoint 기본값은 `http://192.168.30.167:30000/v1`이다.
   - 로컬 endpoint 확인 시 `Authorization` 헤더를 보내지 않는다.
   - 먼저 `GET /models`로 실제 모델 ID를 확인한 뒤, 확인된 ID로 `POST /chat/completions`를 호출한다.
   - `K8S_AGENT_LLM_BASE_URL`, `K8S_AGENT_LLM_MODEL`을 환경변수로 받으며, `K8S_AGENT_LLM_API_KEY`는 외부 provider용 선택값이다.
   - API key는 외부 provider에만 사용하고 로그, event, prompt snapshot, 산출물에 저장하지 않는다.
   - API key 누락만으로 로컬 provider 실패를 판정하지 않는다.
   - provider 장애 시 결정론적 분석 결과는 보존하고 질문 또는 unresolved로 전환한다.

5. **테스트 프레임워크**
   - 기존 테스트 관례를 따라 기본 명령은 `unittest`를 사용한다.
   - 네트워크·외부 바이너리 의존 테스트는 환경변수 또는 pytest marker로 명시적으로 opt-in 한다.

---

## 1. 전역 제약

- `--repo-url`과 `--local-path` 중 정확히 하나를 요구한다.
- Source 옵션 생략 시 현재 디렉터리를 자동 선택하지 않는다.
- `--local-path`와 `--ref`를 함께 허용하지 않는다.
- 지원 Target은 `development`, `staging`, `production`이다.
- 원본 Repository는 읽기 전용으로 취급한다.
- Secret 값은 LLM 입력, 로그, Profile, YAML, 오류 보고서, 캐시에 기록하지 않는다.
- LLM 자유 텍스트는 Agent Decision으로 사용하지 않는다. Pydantic schema 검증을 통과한 결과만 허용한다.
- 동일 Source fingerprint, Profile revision, renderer/template/policy version은 byte-identical Manifest Bundle을 생성해야 한다.
- 자동 리페어는 생성된 Manifest/Kustomize와 Agent metadata에만 적용한다.
- 자동 리페어 최대 횟수는 3회다.
- 동일 오류와 동일 전략 조합은 두 번 사용하지 않는다.
- 외부 공개, Secret 공급 방식, PVC, workload 종류, 사용자 제공 값 변경은 사용자 승인 없이 수정하지 않는다.
- 기본 실행에서는 traceback을 노출하지 않고 `--debug`에서만 표시한다.
- Git hook, submodule, Git LFS 다운로드는 기본 비활성화한다.
- subprocess는 `shell=False`와 argument list만 사용한다.

---

## 2. 테스트 실행 원칙

### 환경 준비

구현 시작 전 `.venv/bin/python3`가 없으면 먼저 프로젝트 가상환경을 준비한다.

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0" "jinja2>=3.1" "openai>=1.0"
```

### 개발 중

새로 작성한 테스트 또는 직접 관련된 테스트 모듈만 실행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest <test.module> -v
```

### 태스크 완료 시

해당 패키지 또는 기능 묶음의 테스트만 실행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/<package> -p 'test_*.py' -v
```

### 전체 테스트

기능 묶음 완료, 보안 경계 변경, 공통 모델 변경, 최종 커밋 전만 실행한다. 실행 전 다음 형식으로 이유를 남긴다.

```text
전체 테스트 실행 이유: <공통 모델/오케스트레이션/보안 경계 변경으로 기존 Phase 1 회귀 가능성이 있음>
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

문서만 변경하는 태스크에서는 전체 테스트를 실행하지 않는다.

---

## 3. 목표 파일 구조

```text
src/
├── preanalyzer/                       # 기존 결정론적 분석 코어 유지
│   ├── analyzer/
│   ├── models/
│   ├── semantic/
│   └── pipeline.py
└── k8s_agent/
    ├── __init__.py
    ├── cli.py                         # argparse 명령과 사용자 출력
    ├── application.py                 # prepare/resume 등 use case 진입점
    ├── errors.py                      # 오류 코드, exit code, 사용자 메시지
    ├── versions.py                    # policy/template/renderer schema version
    ├── models/
    │   ├── run.py
    │   ├── source.py
    │   ├── topology.py
    │   ├── intent.py
    │   ├── decision.py
    │   ├── profile.py
    │   ├── validation.py
    │   └── report.py
    ├── run/
    │   ├── store.py
    │   ├── manager.py
    │   └── events.py
    ├── source/
    │   ├── local.py
    │   ├── github.py
    │   ├── workspace.py
    │   ├── fingerprint.py
    │   └── git_runner.py
    ├── analysis/
    │   ├── phase1_adapter.py
    │   ├── topology_builder.py
    │   └── intent_builder.py
    ├── policy/
    │   ├── target_policy.py
    │   └── engine.py
    ├── agent/
    │   ├── planner.py
    │   ├── orchestrator.py
    │   └── actions.py
    ├── questions/
    │   ├── manager.py
    │   └── answers.py
    ├── llm/
    │   ├── gateway.py
    │   ├── openai_compatible.py
    │   └── redaction.py
    ├── profile/
    │   └── builder.py
    ├── render/
    │   ├── renderer.py
    │   ├── resources.py
    │   ├── names.py
    │   └── serializer.py
    ├── validation/
    │   ├── orchestrator.py
    │   ├── internal.py
    │   ├── kubeconform.py
    │   └── kustomize.py
    ├── repair/
    │   ├── controller.py
    │   └── strategies.py
    └── reporting/
        └── final_report.py

tests/
├── unit/k8s_agent/
├── cli/
├── acceptance/
├── integration/
└── fixtures/repos/
```

`preanalyzer`의 public data model을 직접 변경해야 할 때만 해당 파일을 수정한다. Agent 전용 상태와 모델을 `preanalyzer`에 넣지 않는다. 모든 신규 Python package와 test package에는 해당 package를 처음 소유하는 태스크에서 `__init__.py`를 함께 추가한다.

### Run artifact ownership

| Artifact | Owner task |
|---|---:|
| `run.yaml`, `events.jsonl` | 2 |
| `source.yaml` | 3, 4 |
| `analysis/00`~`03` | 5 |
| `analysis/04-application-topology.yaml` | 6, 7 |
| `analysis/05-kubernetes-intent.yaml` | 8 |
| `plan.yaml` | 9 |
| `questions.yaml`, `answers.yaml` | 10 |
| `decisions.yaml`, `deployment-profile.yaml` | 11 |
| `manifests/base`, `manifests/overlays/<target>` | 12 |
| `validation/static-report.yaml` | 13 |
| `repairs/attempt-*.yaml`, `attempt-*.patch` | 14 |
| `final-report.yaml` | 17 |

---

# Milestone 1 — CLI, Run, Source

## Task 1: 목표 중심 CLI 입력 계약과 오류 체계

**예상 크기:** 30~45분

**목표**

사용자가 `k8s-agent prepare`를 실행했을 때 Source 배타성, `--ref`, Target, non-interactive 옵션이 명확히 검증되고 안정적인 종료 코드와 해결 방법이 표시된다.

**변경 범위**

- `prepare`, `resume`, `status`, `explain`, `export`, `analyze`, `plan`, `generate`, `validate` command skeleton
- `--repo-url`, `--local-path`, `--ref`, `--target`, `--non-interactive`, `--answers-file`, `--debug`
- 오류 코드와 exit code mapping
- traceback 숨김과 debug 출력 경계
- `pyproject.toml` build-system/package discovery와 console script 등록

**Files**

- Create: `src/k8s_agent/__init__.py`
- Create: `src/k8s_agent/cli.py`
- Create: `src/k8s_agent/errors.py`
- Modify: `pyproject.toml`
- Test: `tests/cli/test_prepare_arguments.py`
- Test: `tests/unit/k8s_agent/test_errors.py`

**Interfaces**

- Produces: `k8s_agent.cli.main(argv: list[str] | None = None) -> int`
- Produces: `AgentError(code: str, exit_code: int, message: str, resolution: str, context: dict[str, str])`
- Consumed later by: 모든 application use case와 CLI black-box 테스트

**Red → Green → Refactor**

- [ ] **Red:** subprocess black-box 테스트로 Source 생략, 두 Source 동시 사용, local+ref, 잘못된 Target, answers-file 없는 non-interactive 실행이 각각 exit code `2`와 해결 방법을 반환하는지 검증한다.
- [ ] **Green:** `argparse` parser와 `AgentError` formatter를 최소 구현한다. 아직 실제 prepare를 실행하지 않고 검증을 통과한 요청은 application stub에 전달한다.
- [ ] **Refactor:** parser 생성, 오류 포맷, exit code mapping을 분리하고 CLI에 도메인 판단 로직이 남지 않게 한다.

**완료 조건**

- `k8s-agent prepare --target development`는 Source 누락 오류를 낸다.
- Source 두 개를 동시에 주면 오류를 낸다.
- `--local-path`와 `--ref` 조합은 오류다.
- `production`은 유효한 Target으로 파싱된다.
- 기본 오류에는 traceback이 없고 `--debug`에서만 traceback을 볼 수 있다.
- 모든 CLI 입력 오류에 명령 예시 또는 수정 방법이 포함된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.cli.test_prepare_arguments \
  tests.unit.k8s_agent.test_errors -v
```

**전체 테스트 필요 여부:** 아니요. 신규 CLI 경계만 추가하며 기존 분석 코어를 변경하지 않는다.

**권장 커밋:** `feat(cli): add explicit source contract and error codes`

---

## Task 2: 영속 Run 상태, 상태 전이와 append-only Event Log

**예상 크기:** 45~60분

**목표**

유효한 prepare 요청이 고유 Run을 만들고, 허용된 상태 전이만 수행하며, 중간 산출물과 이벤트를 원자적으로 저장한다.

**변경 범위**

- Run ID와 Run root
- `run.yaml` 생성
- 상태 전이 검증
- append-only `events.jsonl`
- atomic YAML/JSON write와 실행 lock
- Run metadata 기본 필드

**Files**

- Create: `src/k8s_agent/models/run.py`
- Create: `src/k8s_agent/run/store.py`
- Create: `src/k8s_agent/run/manager.py`
- Create: `src/k8s_agent/run/events.py`
- Create: `src/k8s_agent/versions.py`
- Test: `tests/unit/k8s_agent/run/test_store.py`
- Test: `tests/unit/k8s_agent/run/test_manager.py`
- Test: `tests/unit/k8s_agent/run/test_events.py`

**Interfaces**

- Produces: `RunManager.create(request: PrepareRequest) -> RunRecord`
- Produces: `RunManager.transition(run_id: str, target: RunState, summary: str) -> RunRecord`
- Produces: `RunStore.load(run_id: str) -> RunRecord`
- Produces: `EventLog.append(event: RunEvent) -> None`
- Consumed later by: Source resolver, planner, orchestrator, resume, report

**Red → Green → Refactor**

- [ ] **Red:** `CREATED → ACQUIRING_SOURCE`는 성공하고 `CREATED → READY`, terminal 상태 이후 전이, 동시 lock 획득은 실패하는 테스트를 작성한다.
- [ ] **Green:** Pydantic Run 모델, transition table, temp file+rename 기반 atomic write, JSONL append, lock file을 구현한다.
- [ ] **Refactor:** 파일 시스템 코드를 `RunStore`, 정책을 `RunManager`, 이벤트 직렬화를 `EventLog`로 분리한다.

**완료 조건**

- Run 생성 시 `run.yaml`과 `events.jsonl`이 생성된다.
- 잘못된 전이는 `RUN-201` 오류가 된다.
- 마지막 성공 상태와 timestamps가 저장된다.
- 이벤트는 기존 줄을 수정하지 않고 추가만 된다.
- lock이 있는 Run에 두 번째 writer가 진입할 수 없다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/run -p 'test_*.py' -v
```

**전체 테스트 필요 여부:** 아니요. 신규 Run 패키지 내부 변경이다.

**권장 커밋:** `feat(run): persist state transitions and event log`

---

## Task 3: 로컬 Repository 확보와 재현 가능한 snapshot fingerprint

**예상 크기:** 45~60분

**목표**

명시적 로컬 경로를 안전하게 정규화하고 Git metadata, working tree 상태, untracked 파일을 포함하는 현재 snapshot을 `source.yaml`에 기록한다.

**변경 범위**

- 경로 존재·디렉터리·읽기 권한 검증
- 절대 real path 정규화
- Git 저장소 여부, branch, HEAD, clean 여부, 변경 파일 수
- tracked/untracked 현재 내용 기반 fingerprint
- `.git`, Agent state root, binary/oversized 파일 제외 정책
- Source 영역과 Run output 분리 확인

**Files**

- Create: `src/k8s_agent/models/source.py`
- Create: `src/k8s_agent/source/local.py`
- Create: `src/k8s_agent/source/fingerprint.py`
- Create: `src/k8s_agent/source/git_runner.py`
- Test: `tests/unit/k8s_agent/source/test_local.py`
- Test: `tests/unit/k8s_agent/source/test_fingerprint.py`

**Interfaces**

- Produces: `LocalSourceResolver.resolve(path: Path, acquired_at: datetime) -> RepositorySource`
- Produces: `build_source_fingerprint(root: Path, limits: ScanLimits) -> SourceFingerprint`
- Consumes: `RunManager`, `AgentError`
- Consumed later by: Phase 1 adapter, resume drift detection, final report

**Red → Green → Refactor**

- [ ] **Red:** clean Git repo, 수정 파일, untracked 파일, non-Git 디렉터리, 존재하지 않는 경로, unreadable 경로, symlink escape fixture를 테스트한다.
- [ ] **Green:** `git` argument-list 호출과 결정론적 파일 순회로 metadata와 SHA-256 fingerprint를 만든다.
- [ ] **Refactor:** Git 조회 실패와 일반 파일 snapshot 실패를 분리하고, fingerprint 입력 규칙을 한 곳에 모은다.

**완료 조건**

- 상대 경로가 real absolute path로 저장된다.
- 수정·미추적 파일 변화가 fingerprint를 변경한다.
- 동일 snapshot은 동일 fingerprint를 생성한다.
- Agent state 디렉터리와 `.git`은 fingerprint에 포함되지 않는다.
- 원본 Repository에는 파일을 생성하거나 수정하지 않는다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/source -p 'test_local.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.source.test_fingerprint -v
```

**전체 테스트 필요 여부:** 아니요. Source 신규 패키지와 임시 fixture만 검증한다.

**권장 커밋:** `feat(source): resolve local repositories and fingerprints`

---

## Task 4: GitHub Repository ref 고정과 격리 Workspace

**예상 크기:** 45~60분

**목표**

GitHub URL과 branch/tag/SHA를 실제 commit SHA로 고정하고, hook·submodule·LFS를 실행하지 않는 임시 읽기 전용 Workspace를 만든다.

**변경 범위**

- GitHub HTTPS/SSH URL normalization
- embedded credential 제거
- public/private 인증 처리
- ref fetch, `FETCH_HEAD` commit 고정, detached checkout
- 임시 Source workspace와 generated workspace 분리
- timeout, size limit, cleanup
- Git LFS smudge/submodule/hook 비활성화
- Remote Source 오류 코드

**Files**

- Create: `src/k8s_agent/source/github.py`
- Create: `src/k8s_agent/source/workspace.py`
- Modify: `src/k8s_agent/source/git_runner.py`
- Test: `tests/unit/k8s_agent/source/test_github.py`
- Test: `tests/unit/k8s_agent/source/test_workspace.py`
- Test: `tests/integration/test_github_source.py`

**Interfaces**

- Produces: `GitHubSourceResolver.acquire(url: str, requested_ref: str | None, workspace: Workspace) -> AcquiredSource`
- Produces: `WorkspaceManager.create(run_id: str) -> Workspace`
- Produces: `WorkspaceManager.cleanup(workspace: Workspace) -> None`
- Consumed later by: prepare orchestration, Phase 1 adapter, resume

**Red → Green → Refactor**

- [ ] **Red:** fake `GitRunner`로 fetch argument, credential masking, nonexistent ref, auth failure, cleanup failure, detached SHA 고정을 검증한다.
- [ ] **Green:** `git init`, sanitized remote, `git fetch --depth 1`, `git checkout --detach FETCH_HEAD` 흐름을 구현한다.
- [ ] **Refactor:** command construction을 pure function으로 분리해 shell injection과 보안 옵션을 단위 테스트 가능하게 만든다.

**완료 조건**

- `requested_ref`와 `resolved_commit`이 모두 `source.yaml`에 기록된다.
- branch가 이후 이동해도 해당 Run은 resolved commit을 사용한다.
- token 또는 embedded credential이 오류와 이벤트에 노출되지 않는다.
- hook, submodule, LFS가 자동 실행되지 않는다.
- 실패 또는 취소 후 임시 Workspace가 정리된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.source.test_github \
  tests.unit.k8s_agent.source.test_workspace -v
```

선택적 실제 GitHub 테스트:

```bash
K8S_AGENT_RUN_NETWORK_TESTS=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest tests.integration.test_github_source -v
```

**전체 테스트 필요 여부:** 아니요. 실제 네트워크 테스트도 Source integration 범위로 제한한다.

**권장 커밋:** `feat(source): pin github refs in isolated workspaces`

---

# Milestone 2 — 기존 분석 통합, Topology, LLM

## Task 5: 기존 Phase 1 분석을 Run 산출물 체계에 통합

**예상 크기:** 30~45분

**목표**

확보된 Source에 기존 `run_phase1_analysis`를 실행해 Run의 `analysis/00`~`03` 산출물로 보존하고, 기존 결정론적 출력과 테스트를 깨지 않는다.

**변경 범위**

- `RepositorySource`에서 Phase 1 인자 변환
- Run state `ANALYZING`
- output 경로 adapter
- Phase 1 결과 checksum과 event 기록
- 기존 pipeline 예외의 사용자 오류 변환

**Files**

- Create: `src/k8s_agent/analysis/phase1_adapter.py`
- Create: `tests/unit/k8s_agent/analysis/test_phase1_adapter.py`
- Create: `tests/acceptance/test_agent_phase1_integration.py`
- Modify only if required: `src/preanalyzer/pipeline.py`

**Interfaces**

- Produces: `Phase1Adapter.run(source: AcquiredSource, run_paths: RunPaths, clock: Clock) -> Phase1Result`
- Consumes: `preanalyzer.pipeline.run_phase1_analysis`
- Consumed later by: Topology Builder and Agent Planner

**Red → Green → Refactor**

- [ ] **Red:** 기존 3개 fixture에서 `analysis/00`~`03` 파일, source identity, checksum, parse warning 보존을 검증한다.
- [ ] **Green:** thin adapter만 구현하고 Phase 1 내부 분석 로직을 복제하지 않는다.
- [ ] **Refactor:** preanalyzer 예외를 `ANALYSIS-*` 오류로 정규화하고 adapter에 serialization 중복이 없게 한다.

**완료 조건**

- Run Directory에 기존 네 산출물이 생성된다.
- 동일 Source의 기존 Phase 1 결과와 Agent 경유 결과가 의미적으로 동일하다.
- 손상된 package manifest는 warning으로 남고 Run 전체가 실패하지 않는다.
- Phase 1 public API는 유지된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.analysis.test_phase1_adapter \
  tests.acceptance.test_agent_phase1_integration \
  tests.acceptance.test_phase1_deterministic_outputs -v
```

**전체 테스트 필요 여부:** 예. 기존 Phase 1 pipeline과 산출물 경로를 연결하므로 회귀 가능성이 있다.

전체 테스트 실행 이유: 기존 결정론적 분석 API와 Agent adapter의 경계가 모든 parser/fixture에 영향을 줄 수 있음.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `feat(analysis): integrate phase1 outputs into agent runs`

---

## Task 6: Evidence 기반 Application Topology 생성

**예상 크기:** 45~60분

**목표**

Phase 1 Evidence와 Rule Inference를 Component 중심 Application Topology로 병합하고, 충돌·미확정 정보를 명시한다.

**변경 범위**

- Component ID/root path/type
- runtime/build/run/network/env/secret/volume/dependency
- 모노레포 component boundary 규칙
- Evidence reference와 confidence/classification 유지
- topology conflict와 unresolved 목록
- `analysis/04-application-topology.yaml`

**Files**

- Create: `src/k8s_agent/models/topology.py`
- Create: `src/k8s_agent/analysis/topology_builder.py`
- Test: `tests/unit/k8s_agent/analysis/test_topology_builder.py`
- Test: `tests/acceptance/test_application_topology.py`

**Interfaces**

- Produces: `TopologyBuilder.build(phase1: Phase1Result) -> ApplicationTopology`
- Consumes: `EvidenceModel`, `RuleInferenceSet`, existing runtime command analysis models
- Consumed later by: LLM semantic executor, Intent Builder, planner, report

**Red → Green → Refactor**

- [ ] **Red:** Node 단일 서비스, FastAPI 모노레포, frontend/backend 모노레포, Compose 다중 서비스에 대한 component/dependency/secret/port expectations를 작성한다.
- [ ] **Green:** 결정론적 group/merge 규칙과 conflict recording을 구현한다. 근거 없는 framework 추측은 하지 않는다.
- [ ] **Refactor:** component identity, field merge, dependency edge merge를 독립 pure function으로 분리한다.

**완료 조건**

- 모든 확정·추론 필드에 evidence reference가 있다.
- 상충하는 실행 명령과 component 경계는 unresolved/conflict로 남는다.
- Secret은 이름과 사용 위치만 포함한다.
- 출력 순서는 component ID와 field path 기준으로 안정적이다.
- 동일 Phase 1 입력은 byte-identical topology YAML을 생성한다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.analysis.test_topology_builder \
  tests.acceptance.test_application_topology -v
```

**전체 테스트 필요 여부:** 아니요. Phase 1 모델은 소비만 하고 변경하지 않는다.

**권장 커밋:** `feat(topology): build evidence-linked application topology`

---

## Task 7: 구조화 LLM Gateway와 기존 runtime-command semantic task 실행

**예상 크기:** 45~60분

**목표**

기존 semantic task builder, allowlisted tools, verifier를 실제 Agent 경로에 연결하고, LLM 장애나 schema 오류 시 안전하게 unresolved 또는 사용자 질문으로 전환한다.

**변경 범위**

- Evidence redaction
- OpenAI-compatible request adapter
- timeout/retry
- prompt/model/schema version metadata
- Pydantic structured response validation
- 기존 `build_runtime_command_semantic_tasks`와 verifier 호출
- allowlisted semantic tool 실행
- LLM unavailable fallback

**Files**

- Create: `src/k8s_agent/llm/redaction.py`
- Create: `src/k8s_agent/llm/openai_compatible.py`
- Create: `src/k8s_agent/llm/gateway.py`
- Create: `src/k8s_agent/agent/actions.py`
- Modify: `src/preanalyzer/semantic/task_builder.py` only for generic integration seams if required
- Modify: `src/preanalyzer/semantic/verifier.py` only for reusable verifier interface if required
- Test: `tests/unit/k8s_agent/llm/test_redaction.py`
- Test: `tests/unit/k8s_agent/llm/test_gateway.py`
- Test: `tests/acceptance/test_runtime_command_semantic_resolution.py`

**Interfaces**

- Produces: `LLMGateway.execute(task: SemanticTask, context: SemanticContext) -> VerifiedSemanticResult`
- Produces: `SemanticActionExecutor.resolve_runtime_commands(topology: ApplicationTopology, phase1: Phase1Result) -> SemanticResolutionSet`
- Consumes: existing semantic models, tools, task builder, verifier
- Consumed later by: Topology enrichment and planner

**Red → Green → Refactor**

- [ ] **Red:** Secret-like values 제거, allowlist 밖 tool 거부, invalid JSON/schema 거부, timeout 재시도, provider unavailable fallback, verifier rejection을 테스트한다.
- [ ] **Green:** fake transport로 Gateway를 구현하고 기존 semantic task/tool/verifier를 순서대로 연결한다.
- [ ] **Refactor:** transport, prompt construction, redaction, schema validation을 분리하고 Gateway가 file system이나 shell을 직접 호출하지 않게 한다.

**완료 조건**

- LLM 입력에 Secret 값이나 credential이 포함되지 않는다.
- 자유 텍스트 또는 schema-invalid 결과가 Decision으로 저장되지 않는다.
- tool call은 task의 `allowed_tools` 안에서만 실행된다.
- 모델 장애 시 Phase 1/Topology 산출물이 유지된다.
- 성공한 semantic 결과에는 task ID, evidence refs, model/prompt version이 기록된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.llm.test_redaction \
  tests.unit.k8s_agent.llm.test_gateway \
  tests.unit.test_semantic_task_builder \
  tests.unit.test_semantic_verifier \
  tests.acceptance.test_runtime_command_semantic_resolution -v
```

**전체 테스트 필요 여부:** 예. 기존 semantic 모델·도구·검증기와 신규 Gateway를 연결하는 기능 묶음 완료 시점이다.

전체 테스트 실행 이유: 기존 semantic task routing과 verifier의 public interface가 Agent에서 직접 사용됨.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `feat(llm): execute verified semantic runtime tasks`

---

# Milestone 3 — Intent, Planning, Questions, Profile

## Task 8: Target 정책을 적용한 Kubernetes Intent 생성

**예상 크기:** 45~60분

**목표**

Application Topology를 workload, networking, configuration, secret, storage, resources, probes에 대한 Kubernetes Intent로 변환하고 Target별 자동 확정·질문·차단 정책을 적용한다.

**변경 범위**

- development/staging/production policy table
- Deployment/Service 필요성
- exposure/Ingress 후보
- ConfigMap/Secret reference 후보
- PVC/probe/resource/replica 후보
- auto-confirm, requires-confirmation, blocked 분류
- `analysis/05-kubernetes-intent.yaml`

**Files**

- Create: `src/k8s_agent/models/intent.py`
- Create: `src/k8s_agent/policy/target_policy.py`
- Create: `src/k8s_agent/policy/engine.py`
- Create: `src/k8s_agent/analysis/intent_builder.py`
- Test: `tests/unit/k8s_agent/policy/test_target_policy.py`
- Test: `tests/unit/k8s_agent/analysis/test_intent_builder.py`

**Interfaces**

- Produces: `IntentBuilder.build(topology: ApplicationTopology, target: Target) -> KubernetesIntent`
- Produces: `PolicyEngine.evaluate(candidate: IntentCandidate, target: Target) -> PolicyDecision`
- Consumed later by: Planner, Question Manager, Profile Builder

**Red → Green → Refactor**

- [ ] **Red:** Target별 replica, exposure, resource, probe, temporary storage, production cluster verification 금지 테스트를 작성한다.
- [ ] **Green:** 명시된 policy table과 deterministic conversion을 구현한다.
- [ ] **Refactor:** topology-to-intent 변환과 위험 정책 판단을 분리한다.

**완료 조건**

- 외부 공개, hostname, Secret 공급, PVC 크기, stateful 요구는 자동 확정되지 않는다.
- high confidence·저위험·충돌 없음 조건만 자동 확정된다.
- production은 cluster validation action을 생성하지 않는다.
- StatefulSet 필요 판단은 blocked candidate로 남는다.
- 모든 Intent 항목이 source evidence 또는 policy version을 가진다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.policy.test_target_policy \
  tests.unit.k8s_agent.analysis.test_intent_builder -v
```

**전체 테스트 필요 여부:** 아니요. 신규 정책과 Intent 경계에 한정된다.

**권장 커밋:** `feat(intent): derive target-aware kubernetes intent`

---

## Task 9: 현재 상태 기반 Agent Planner와 재계획

**예상 크기:** 45~60분

**목표**

Agent가 저장소마다 다른 실행 Task를 만들고, 현재 Evidence·Intent·질문·검증 결과에 따라 다음 action을 결정하며 `plan.yaml`을 갱신한다.

**변경 범위**

- Agent task model
- task dependency/priority
- 자동 action, semantic action, user question 구분
- completion criteria
- plan revision
- deterministic task ordering
- validation finding 이후 replanning seam

**Files**

- Create: `src/k8s_agent/agent/planner.py`
- Extend: `src/k8s_agent/models/run.py`
- Test: `tests/unit/k8s_agent/agent/test_planner.py`
- Test: `tests/acceptance/test_repository_specific_plans.py`

**Interfaces**

- Produces: `AgentPlanner.plan(context: PlanningContext) -> AgentPlan`
- Produces: `AgentPlanner.next_action(plan: AgentPlan, run: RunRecord) -> AgentAction | None`
- Consumes: Topology, Intent, semantic gaps, policy decisions, validation findings
- Consumed later by: Orchestrator and resume

**Red → Green → Refactor**

- [ ] **Red:** 단일 서비스, 모노레포, 충돌 실행 명령, missing Dockerfile, external exposure 질문이 서로 다른 plan을 생성하는지 검증한다.
- [ ] **Green:** rule-based planner와 plan revision 저장을 구현한다.
- [ ] **Refactor:** task creation rule, priority, completion check를 독립 함수로 나눠 plan diff가 설명 가능하게 한다.

**완료 조건**

- 저장소 특성에 따라 task 수와 순서가 달라진다.
- 동일 context는 동일 plan task ID를 만든다.
- 완료된 task는 재계획 시 중복 실행되지 않는다.
- plan에는 action, 이유, evidence, tool, completion condition이 포함된다.
- LLM 없이도 결정론적 action과 질문 생성까지 진행 가능하다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.agent.test_planner \
  tests.acceptance.test_repository_specific_plans -v
```

**전체 테스트 필요 여부:** 아니요. Planner 자체와 fixture별 plan만 검증한다.

**권장 커밋:** `feat(agent): plan repository-specific deployment work`

---

## Task 10: 사용자 질문, answers file과 non-interactive 차단

**예상 크기:** 45~60분

**목표**

배포 결과에 영향을 주는 미확정 항목만 사용자에게 질문하고, interactive 답변 또는 answers file을 검증해 Decision 후보로 변환한다.

**변경 범위**

- question model과 stable ID
- 중복 제거·우선순위
- 근거·선택지·권장·영향 출력
- interactive input
- YAML answers file
- non-interactive unresolved 처리
- `WAITING_FOR_USER`, `BLOCKED`, exit code `3`

**Files**

- Create: `src/k8s_agent/questions/manager.py`
- Create: `src/k8s_agent/questions/answers.py`
- Extend: `src/k8s_agent/models/decision.py`
- Test: `tests/unit/k8s_agent/questions/test_manager.py`
- Test: `tests/unit/k8s_agent/questions/test_answers.py`
- Test: `tests/cli/test_non_interactive_questions.py`

**Interfaces**

- Produces: `QuestionManager.build(intent: KubernetesIntent, plan: AgentPlan) -> QuestionSet`
- Produces: `AnswerLoader.load(path: Path, questions: QuestionSet) -> AnswerSet`
- Produces: `QuestionManager.to_decisions(answers: AnswerSet) -> list[Decision]`
- Consumed later by: Profile Builder and Orchestrator

**Red → Green → Refactor**

- [ ] **Red:** 외부 공개, hostname, Secret 공급 방식, PVC 크기, 복수 command 후보, 미지원 StatefulSet 질문을 검증한다.
- [ ] **Green:** stable question ID, answer schema, interactive/non-interactive 분기를 구현한다.
- [ ] **Refactor:** 질문 문구 생성과 answer validation을 분리하고 비대화형 모드에 암묵적 default가 없게 한다.

**완료 조건**

- 질문에는 ID, 이유, 근거, 선택지, 권장, 영향, skip 영향이 있다.
- answers file의 unknown question, invalid option, missing required answer가 명확히 보고된다.
- non-interactive에서 필수 답이 없으면 `BLOCKED`, exit code `3`이다.
- 권장값은 자동 선택되지 않는다.
- 사용자 답변은 원문과 정규화된 값 모두 기록된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.questions.test_manager \
  tests.unit.k8s_agent.questions.test_answers \
  tests.cli.test_non_interactive_questions -v
```

**전체 테스트 필요 여부:** 아니요. 질문·답변 기능 묶음에 한정된다.

**권장 커밋:** `feat(questions): collect explicit deployment decisions`

---

## Task 11: 추적 가능한 Decision 병합과 immutable Deployment Profile

**예상 크기:** 45~60분

**목표**

confirmed fact, inference, semantic result, user answer, policy default를 충돌 규칙에 따라 병합하고 renderer의 유일한 입력인 immutable Profile revision을 만든다.

**변경 범위**

- Decision model 전체 필드
- source priority와 conflict rules
- immutable profile revision
- unresolved/blocked 포함
- source/rules/policy/renderer/template version
- YAML 안정 정렬과 checksum

**Files**

- Create: `src/k8s_agent/models/decision.py`
- Create: `src/k8s_agent/models/profile.py`
- Create: `src/k8s_agent/profile/builder.py`
- Test: `tests/unit/k8s_agent/profile/test_builder.py`
- Test: `tests/acceptance/test_deployment_profile.py`

**Interfaces**

- Produces: `DeploymentProfileBuilder.build(inputs: ProfileInputs, previous: DeploymentProfile | None = None) -> DeploymentProfile`
- Produces: `DeploymentProfile.checksum() -> str`
- Consumes: Topology, Intent, semantic results, user answers, policy decisions
- Consumed later by: Renderer, validator, resume, report

**Red → Green → Refactor**

- [ ] **Red:** 사용자 값 우선, confirmed와 inference 충돌, default 금지, immutable revision 증가, unresolved 차단을 테스트한다.
- [ ] **Green:** explicit precedence table과 profile serializer를 구현한다.
- [ ] **Refactor:** field merge를 JSON pointer 단위 pure function으로 만들고 profile 생성 중 입력 객체를 변경하지 않게 한다.

**완료 조건**

- 각 결정에 ID, 값, classification, confidence, evidence, actor, alternatives, approval, affected resources가 있다.
- user-provided 값을 자동 inference가 덮어쓰지 않는다.
- unresolved/blocked가 필수 field에 남으면 renderer 진입을 차단한다.
- Profile revision은 기존 revision을 수정하지 않고 새 파일 또는 revision metadata로 저장된다.
- 동일 입력은 동일 Profile checksum을 만든다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.profile.test_builder \
  tests.acceptance.test_deployment_profile -v
```

**전체 테스트 필요 여부:** 예. Profile은 이후 모든 생성·검증의 공통 계약이며 semantic/질문/정책 모델을 함께 소비한다.

전체 테스트 실행 이유: 공통 Decision/Profile 계약이 Phase 1 이후 전체 기능 묶음의 연결점이 됨.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `feat(profile): merge evidence and user decisions immutably`

---

# Milestone 4 — Deterministic Manifest Generation

## Task 12: Profile 기반 Kubernetes Manifest와 Kustomize 렌더링

**예상 크기:** 45~60분

**목표**

Deployment Profile만을 입력으로 Deployment, Service, ConfigMap, Secret reference, Ingress, Probe, PVC와 Kustomize base/overlay를 결정론적으로 생성한다.

**변경 범위**

- DNS-safe resource naming
- standard labels/annotations
- Deployment와 Service
- ConfigMap과 existing Secret reference
- optional Ingress
- readiness/liveness/startup probe
- optional PVC와 volumeMount
- base/overlays/<target>/kustomization.yaml
- stable YAML document ordering
- renderer/template version

**Files**

- Create: `src/k8s_agent/render/names.py`
- Create: `src/k8s_agent/render/resources.py`
- Create: `src/k8s_agent/render/serializer.py`
- Create: `src/k8s_agent/render/renderer.py`
- Test: `tests/unit/k8s_agent/render/test_names.py`
- Test: `tests/unit/k8s_agent/render/test_resources.py`
- Test: `tests/acceptance/test_manifest_renderer.py`
- Test: `tests/acceptance/test_manifest_reproducibility.py`

**Interfaces**

- Produces: `ManifestRenderer.render(profile: DeploymentProfile, destination: Path) -> ManifestBundle`
- Produces: `ManifestBundle(resource_refs: list[ResourceRef], files: list[GeneratedFile], checksum: str)`
- Consumes: immutable Deployment Profile only
- Consumed later by: Validation, Repair, export, report

**Red → Green → Refactor**

- [ ] **Red:** 단일 서비스, frontend/backend, internal/public exposure, Secret ref, ConfigMap, PVC, probe, staging replica fixtures의 golden expectations를 작성한다.
- [ ] **Green:** Python dict resource builders와 안정 serializer로 최소 리소스를 생성한다.
- [ ] **Refactor:** naming, resource construction, file layout, serialization을 분리하고 renderer에서 Evidence/Topology를 직접 조회하지 않게 한다.

**완료 조건**

- renderer는 Deployment Profile 외 입력을 읽지 않는다.
- Secret value가 생성 YAML에 포함되지 않는다.
- Service selector와 Pod label, targetPort와 containerPort가 일치한다.
- 외부 공개 승인 없이 Ingress가 생성되지 않는다.
- StatefulSet 필요 Profile은 명시적 blocked 오류가 된다.
- 동일 Profile은 byte-identical bundle을 생성한다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/render -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.acceptance.test_manifest_renderer \
  tests.acceptance.test_manifest_reproducibility -v
```

**전체 테스트 필요 여부:** 아니요. Profile 계약 이후의 독립 renderer 기능이다.

**권장 커밋:** `feat(render): generate deterministic kubernetes bundles`

---

# Milestone 5 — Validation and Repair

## Task 13: 정적 검증 파이프라인과 manifest-ready 계산

**예상 크기:** 45~60분

**목표**

생성 Bundle을 순서대로 검증하고, 모든 오류를 공통 ValidationFinding으로 정규화해 `manifest-ready` 여부를 계산한다.

**변경 범위**

- YAML syntax와 duplicate resource
- resource name
- label/selector
- Service targetPort
- ConfigMap/Secret references
- volume/volumeMount
- probe shape
- namespace consistency
- forbidden security settings
- Profile-manifest consistency
- kubeconform adapter
- kustomize build adapter
- validator version 기록

**Files**

- Create: `src/k8s_agent/models/validation.py`
- Create: `src/k8s_agent/validation/internal.py`
- Create: `src/k8s_agent/validation/kubeconform.py`
- Create: `src/k8s_agent/validation/kustomize.py`
- Create: `src/k8s_agent/validation/orchestrator.py`
- Test: `tests/unit/k8s_agent/validation/test_internal.py`
- Test: `tests/unit/k8s_agent/validation/test_external_adapters.py`
- Test: `tests/acceptance/test_manifest_validation.py`

**Interfaces**

- Produces: `ValidationOrchestrator.validate(bundle: ManifestBundle, profile: DeploymentProfile) -> ValidationReport`
- Produces: `ValidationFinding(id, validator, severity, resource_ref, field_path, code, message, repairable)`
- Consumed later by: Repair Controller, Planner, final report

**Red → Green → Refactor**

- [ ] **Red:** 각 필수 검증 규칙당 하나의 최소 실패 fixture와 정상 bundle을 테스트한다.
- [ ] **Green:** internal validators, argument-list 외부 tool adapters, finding normalization과 readiness 계산을 구현한다.
- [ ] **Refactor:** 각 validator를 side-effect 없는 check로 분리하고 외부 tool 실행을 injectable runner로 만든다.

**완료 조건**

- 검증은 명시된 순서를 따른다.
- 오류는 validator 고유 문자열이 아니라 공통 finding schema로 저장된다.
- kubeconform/kustomize 미설치 시 설치 방법과 `BLOCKED` 또는 명시적 tool-missing 상태를 제공한다.
- 모든 필수 검증 성공 시에만 `manifest-ready`다.
- build/cluster validation은 `not-run`으로 보고된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/validation -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest tests.acceptance.test_manifest_validation -v
```

선택적 실제 바이너리 검증:

```bash
K8S_AGENT_RUN_TOOL_TESTS=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest tests.integration.test_validation_tools -v
```

**전체 테스트 필요 여부:** 아니요. Renderer 결과에 대한 검증 기능 묶음에 한정한다.

**권장 커밋:** `feat(validation): calculate manifest readiness`

---

## Task 14: 제한된 자동 리페어와 재검증 루프

**예상 크기:** 45~60분

**목표**

repairable finding에 대해서만 생성 파일을 수정하고 최대 3회 재검증하며, 위험 변경과 반복 실패를 안전하게 차단한다.

**변경 범위**

- finding classification
- repair eligibility
- bounded repair strategies
- generated path guard
- user reapproval rules
- attempt 기록과 patch 저장
- repeated strategy suppression
- max attempts와 exit code `6`

**Files**

- Create: `src/k8s_agent/repair/strategies.py`
- Create: `src/k8s_agent/repair/controller.py`
- Test: `tests/unit/k8s_agent/repair/test_strategies.py`
- Test: `tests/unit/k8s_agent/repair/test_controller.py`
- Test: `tests/acceptance/test_repair_loop.py`

**Interfaces**

- Produces: `RepairController.repair(bundle: ManifestBundle, profile: DeploymentProfile, report: ValidationReport) -> RepairResult`
- Produces: `RepairAttempt(attempt, finding_refs, strategy, files_changed, validation_result)`
- Consumes: Validation findings and generated file manifest
- Consumed later by: Orchestrator and report

**Red → Green → Refactor**

- [ ] **Red:** selector/port/reference 같은 repairable 오류, exposure/PVC/user value 같은 approval-required 오류, source file path attack, repeated finding, max attempt를 테스트한다.
- [ ] **Green:** allowlisted strategy map과 generated-path guard를 구현하고 각 attempt 후 전체 정적 검증을 다시 실행한다.
- [ ] **Refactor:** strategy selection과 patch application을 분리하고 patch 전후 checksum을 기록한다.

**완료 조건**

- 원본 Source와 Profile의 user-provided 값은 자동 수정되지 않는다.
- 자동 수정 파일은 Manifest Bundle 내 생성 파일로 제한된다.
- 동일 오류+전략은 두 번 적용되지 않는다.
- 최대 3회 이후 unresolved 오류가 보고된다.
- 위험 변경은 Question 또는 `BLOCKED`로 전환된다.
- 각 attempt YAML과 patch가 `repairs/`에 저장된다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/repair -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest tests.acceptance.test_repair_loop -v
```

**전체 테스트 필요 여부:** 예. Renderer·Validator·Profile을 모두 다시 연결하는 기능 묶음 완료 시점이다.

전체 테스트 실행 이유: 리페어가 공통 생성물과 검증 결과를 변경하므로 기존 재현성과 정적 검증 회귀를 확인해야 함.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `feat(repair): add bounded manifest repair loop`

---

# Milestone 6 — End-to-End Agent, Resume, Reporting

## Task 15: Observe–Decide–Act–Evaluate prepare 오케스트레이션

**예상 크기:** 45~60분

**목표**

`k8s-agent prepare` 한 명령이 Source 확보부터 질문, Profile, 생성, 검증, 리페어와 최종 상태까지 Agent loop로 수행한다.

**변경 범위**

- application service
- orchestrator loop
- action dispatch
- state transitions
- stop conditions
- Ctrl+C cancellation
- idempotent step resume seam
- CLI progress summary

**Files**

- Create: `src/k8s_agent/application.py`
- Create: `src/k8s_agent/agent/orchestrator.py`
- Modify: `src/k8s_agent/cli.py`
- Test: `tests/unit/k8s_agent/agent/test_orchestrator.py`
- Test: `tests/cli/test_prepare_black_box.py`
- Test: `tests/acceptance/test_prepare_end_to_end.py`

**Interfaces**

- Produces: `AgentApplication.prepare(request: PrepareRequest) -> RunOutcome`
- Produces: `AgentOrchestrator.run(run_id: str) -> RunOutcome`
- Consumes: 모든 앞선 service interface
- Consumed later by: resume와 CI

**Red → Green → Refactor**

- [ ] **Red:** ready, waiting-for-user, blocked, validation-failed, repair-success, cancellation 경로를 fake services와 실제 fixture로 검증한다.
- [ ] **Green:** state 기반 loop와 action dispatcher를 구현해 한 action 후 상태를 영속화한다.
- [ ] **Refactor:** loop가 구체 service 구현에 의존하지 않도록 ports/protocols를 정리하고 각 action을 재실행 안전하게 만든다.

**완료 조건**

- 사용자는 내부 단계를 지정하지 않고 `prepare` 목표만 요청한다.
- 실행 결과에 따라 다음 action이 달라진다.
- 질문 대기, blocked, failed, ready가 명확히 구분된다.
- Ctrl+C는 `CANCELLED` 상태와 정리 이벤트를 남긴다.
- terminal 상태에서는 추가 action을 실행하지 않는다.
- 성공 시 exit code `0`, 검증 실패 `5`, 정책 차단 `4`, 내부 오류 `8`이 안정적이다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.agent.test_orchestrator \
  tests.cli.test_prepare_black_box \
  tests.acceptance.test_prepare_end_to_end -v
```

**전체 테스트 필요 여부:** 예. 첫 번째 완전한 수직 기능 묶음이 완료되는 시점이다.

전체 테스트 실행 이유: CLI부터 기존 Phase 1, semantic, Profile, renderer, validator, repair까지 전체 호출 경로가 연결됨.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `feat(agent): orchestrate prepare to manifest readiness`

---

## Task 16: resume과 Source drift 처리

**예상 크기:** 45~60분

**목표**

질문이나 오류로 중단된 Run을 마지막 성공 Task부터 재개하고, Source fingerprint 변경 시 명시적 선택 없이는 진행하지 않는다.

**변경 범위**

- `k8s-agent resume <run-id>`
- last successful task/checksum/version 확인
- local Source drift와 remote commit 고정 확인
- 기존 답변·Profile revision 재사용
- drift 선택: 새 Run, 재계획, pinned source 계속
- validator/version change invalidation

**Files**

- Extend: `src/k8s_agent/application.py`
- Extend: `src/k8s_agent/agent/orchestrator.py`
- Extend: `src/k8s_agent/run/manager.py`
- Modify: `src/k8s_agent/cli.py`
- Test: `tests/unit/k8s_agent/test_resume.py`
- Test: `tests/cli/test_resume_black_box.py`

**Interfaces**

- Produces: `AgentApplication.resume(run_id: str, drift_policy: DriftPolicy | None) -> RunOutcome`
- Consumes: Run Store, source resolver, plan revision, Profile checksum, Manifest checksum

**Red → Green → Refactor**

- [ ] **Red:** WAITING_FOR_USER resume, failed validator resume, unchanged local source, changed local source, remote pinned SHA, tool version change를 테스트한다.
- [ ] **Green:** resumable-state guard, artifact integrity check, drift decision 처리를 구현한다.
- [ ] **Refactor:** resume validation을 별도 function으로 분리하고 신규 prepare 경로와 중복 실행 코드를 제거한다.

**완료 조건**

- unchanged Source는 완료된 분석을 다시 실행하지 않는다.
- changed Source는 사용자 선택 전 진행하지 않는다.
- answers와 immutable Profile revision이 보존된다.
- checksum 불일치 산출물은 해당 단계부터 재생성한다.
- READY/FAILED 같은 비재개 상태에 대한 메시지가 명확하다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.test_resume \
  tests.cli.test_resume_black_box -v
```

**전체 테스트 필요 여부:** 아니요. 기존 prepare 수직 경로는 유지하고 resume 분기만 추가한다.

**권장 커밋:** `feat(run): resume safely across source changes`

---

## Task 17: status, explain, export와 최종 보고서

**예상 크기:** 45~60분

**목표**

사용자가 내부 YAML을 직접 읽지 않고 Run 상태, 주요 판단 근거, 생성 리소스, readiness, 한계와 다음 행동을 확인하고 결과물을 명시적 경로로 export할 수 있다.

**변경 범위**

- `status <run-id>`
- `explain <run-id> [decision-id|resource-ref]`
- `export <run-id> --output <path>`
- `final-report.yaml`
- human-readable summary
- source identity, decision counts, warnings, repairs, limitations, next action
- export collision과 overwrite 정책

**Files**

- Create: `src/k8s_agent/models/report.py`
- Create: `src/k8s_agent/reporting/final_report.py`
- Extend: `src/k8s_agent/application.py`
- Modify: `src/k8s_agent/cli.py`
- Test: `tests/unit/k8s_agent/reporting/test_final_report.py`
- Test: `tests/cli/test_status_explain_export.py`

**Interfaces**

- Produces: `FinalReportBuilder.build(run: RunAggregate) -> FinalReport`
- Produces: `AgentApplication.status(run_id: str) -> StatusView`
- Produces: `AgentApplication.explain(run_id: str, subject: str | None) -> ExplanationView`
- Produces: `AgentApplication.export(run_id: str, output: Path, overwrite: bool) -> ExportResult`

**Red → Green → Refactor**

- [ ] **Red:** ready/blocked/failed report, decision explain, resource evidence chain, export collision, Secret value absence를 테스트한다.
- [ ] **Green:** report aggregation과 read-only query commands, explicit export copy를 구현한다.
- [ ] **Refactor:** machine-readable model과 CLI presentation을 분리한다.

**완료 조건**

- report에 source, summary, validation, limitations, next_action이 포함된다.
- `production-ready`라는 표현을 사용하지 않는다.
- build/cluster 미실행이 명시된다.
- explain은 Evidence → Decision → Profile field → Resource 관계를 보여준다.
- export는 원본 Repository를 자동 수정하지 않으며 overwrite를 명시적으로 요구한다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.reporting.test_final_report \
  tests.cli.test_status_explain_export -v
```

**전체 테스트 필요 여부:** 아니요. read-only 조회와 export 기능에 한정된다.

**권장 커밋:** `feat(report): explain and export manifest-ready runs`

---

# Milestone 7 — Security, CI, Acceptance


## Task 18: 고급 analyze, plan, generate, validate 단계 명령

**예상 크기:** 30~45분

**목표**

플랫폼 엔지니어와 CI가 특정 단계를 명시적으로 실행하거나 재실행할 수 있으면서도, Deployment Profile 단일 입력과 Run 상태·감사 규칙을 우회하지 않는다.

**변경 범위**

- `k8s-agent analyze`로 Source 확보와 `00`~`04` 분석 산출물 생성
- `k8s-agent plan <run-id>`으로 Intent·질문·plan revision 생성
- `k8s-agent generate <run-id> [--profile-revision N]`으로 확정 Profile만 렌더링
- `k8s-agent validate <run-id>`로 기존 Bundle 재검증
- 단계별 선행조건과 안정적인 종료 코드
- 단계 재실행 event와 checksum invalidation

**Files**

- Extend: `src/k8s_agent/application.py`
- Extend: `src/k8s_agent/cli.py`
- Extend: `src/k8s_agent/agent/orchestrator.py`
- Test: `tests/cli/test_advanced_commands.py`
- Test: `tests/unit/k8s_agent/test_stage_commands.py`

**Interfaces**

- Produces: `AgentApplication.analyze(request: AnalyzeRequest) -> RunOutcome`
- Produces: `AgentApplication.plan(run_id: str) -> PlanOutcome`
- Produces: `AgentApplication.generate(run_id: str, profile_revision: int | None) -> ManifestBundle`
- Produces: `AgentApplication.validate(run_id: str) -> ValidationReport`
- Consumes: 기존 Source, Phase 1, Topology, Intent, Profile, Renderer, Validation public interface

**Red → Green → Refactor**

- [ ] **Red:** 분석 전 plan, Profile 전 generate, Bundle 전 validate가 선행조건 오류를 내고, 정상 단계 재실행은 해당 하위 산출물만 갱신하는지 검증한다.
- [ ] **Green:** 각 명령을 기존 application service와 action에 thin wrapper로 연결하고 새 분석·생성 로직을 복제하지 않는다.
- [ ] **Refactor:** prepare와 단계 명령이 동일 action implementation을 공유하게 하고, 단계별 authorization/validation을 공통 guard로 통합한다.

**완료 조건**

- 단계 명령은 기존 Run artifact와 상태 전이 규칙을 사용한다.
- `generate`는 확정된 Deployment Profile 외 입력을 받지 않는다.
- `validate`는 원본 Source를 읽거나 변경하지 않는다.
- 단계 재실행은 영향받는 checksum과 후속 readiness만 무효화한다.
- 모든 단계 실행이 event log에 actor, command, input revision, result를 남긴다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.unit.k8s_agent.test_stage_commands \
  tests.cli.test_advanced_commands -v
```

**전체 테스트 필요 여부:** 아니요. 기존 application action을 재사용하는 고급 진입점만 추가한다.

**권장 커밋:** `feat(cli): expose safe stage-level agent commands`

---

## Task 19: Trust boundary 보안 강화와 감사 추적

**예상 크기:** 45~60분

**목표**

Repository, credential, subprocess, LLM, YAML, Kubernetes resource 경계에서 공격 입력을 차단하고 모든 실행·결정·수정이 감사 가능하게 기록된다.

**변경 범위**

- credential/token masking 공통화
- symlink path escape
- malicious filename
- shell injection
- oversized/binary file
- malicious YAML
- unsafe Kubernetes resource
- privileged/hostPath/cluster-wide/RBAC policy
- tool execution audit event
- file-read/LLM/decision/repair audit event

**Files**

- Extend: `src/k8s_agent/source/fingerprint.py`
- Extend: `src/k8s_agent/source/git_runner.py`
- Extend: `src/k8s_agent/llm/redaction.py`
- Extend: `src/k8s_agent/validation/internal.py`
- Extend: `src/k8s_agent/run/events.py`
- Test: `tests/unit/k8s_agent/security/test_source_boundaries.py`
- Test: `tests/unit/k8s_agent/security/test_secret_redaction.py`
- Test: `tests/unit/k8s_agent/security/test_command_execution.py`
- Test: `tests/unit/k8s_agent/security/test_manifest_policy.py`
- Test: `tests/acceptance/test_audit_trail.py`

**Interfaces**

- Produces: 공통 `Redactor`, `SafePathPolicy`, `CommandPolicy`, `ManifestSecurityPolicy`
- Consumes: Source, LLM, validator, event log public interfaces
- Affects: 전체 시스템 trust boundary

**Red → Green → Refactor**

- [ ] **Red:** 공격 fixture와 canary Secret으로 로그·산출물·prompt·report 유출을 탐지하는 테스트를 작성한다.
- [ ] **Green:** 공통 경계 정책을 각 adapter 진입점에 적용하고 차단 오류와 audit event를 기록한다.
- [ ] **Refactor:** 중복 masking/path check를 제거하고 정책 함수에 default-deny 원칙을 적용한다.

**완료 조건**

- command는 shell string으로 실행되지 않는다.
- Source 밖 symlink는 읽지 않는다.
- Secret canary가 Run Directory 어디에도 나타나지 않는다.
- privileged, hostPath, cluster-wide resource는 자동 생성·허용되지 않는다.
- token이 포함된 Git URL은 저장 전에 정제된다.
- 어떤 tool이 어떤 인자로 실행되었는지 민감 값 없이 감사 가능하다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover \
  -s tests/unit/k8s_agent/security -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest tests.acceptance.test_audit_trail -v
```

**전체 테스트 필요 여부:** 예. 공통 Source·LLM·subprocess·validation 경계를 변경한다.

전체 테스트 실행 이유: 보안 정책이 여러 패키지의 정상 경로를 차단하거나 serialization을 변경할 수 있음.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

**권장 커밋:** `security: harden agent trust boundaries and audit trail`

---

## Task 20: 10개 fixture 기반 MVP acceptance, CI 종료 코드와 재현성 기준

**예상 크기:** 45~60분

**목표**

명세의 10개 fixture와 CLI black-box matrix로 MVP 성공 기준을 검증하고, 지원 fixture의 80% 이상이 사용자 YAML 작성 없이 `manifest-ready`에 도달함을 자동 판정한다.

**변경 범위**

- 기존 3 fixture 보존
- Java 단일 서비스
- frontend/backend 모노레포
- Docker Compose 다중 서비스
- Dockerfile 없음
- conflicting commands
- corrupt package manifest
- Secret candidate
- persistent storage
- readiness success/blocked matrix
- exit code matrix
- reproducibility byte comparison
- CI test grouping 문서

**Files**

- Add/extend: `tests/fixtures/repos/*`
- Create: `tests/acceptance/test_mvp_fixture_matrix.py`
- Create: `tests/acceptance/test_manifest_reproducibility_matrix.py`
- Create: `tests/cli/test_exit_code_matrix.py`
- Modify: `pyproject.toml` marker/config only if required
- Modify: `README.md`
- Create: `docs/testing/agent-mvp-test-matrix.md`

**Interfaces**

- Produces: acceptance matrix as executable contract
- Consumes: public CLI only for black-box tests, application API only for fixture diagnostics

**Red → Green → Refactor**

- [ ] **Red:** 10 fixture expectation table을 먼저 작성하고 현재 미지원 경로가 명확히 실패/blocked되는지 고정한다.
- [ ] **Green:** fixture별 answers file과 expected readiness/exit code를 추가해 80% 기준을 충족하도록 누락된 최소 glue를 보완한다.
- [ ] **Refactor:** fixture helper와 CLI runner 중복을 제거하고 테스트 실패가 어떤 성공 기준을 위반했는지 표시한다.

**완료 조건**

- 10개 fixture가 모두 자동 실행된다.
- 최소 8개 fixture가 사용자 YAML 작성 없이 `manifest-ready`다.
- 나머지는 근거 없는 추측 대신 질문 또는 명확한 blocked reason을 낸다.
- 동일 fixture/Profile 반복 실행은 byte-identical manifest bundle을 만든다.
- CLI exit code `0`~`8`의 정의된 경로가 검증된다.
- README에 실제 설치, prepare, non-interactive, resume, status, explain, export와 고급 analyze/plan/generate/validate 명령이 있다.

**실행할 테스트 범위**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.acceptance.test_mvp_fixture_matrix \
  tests.acceptance.test_manifest_reproducibility_matrix \
  tests.cli.test_exit_code_matrix -v
```

**전체 테스트 필요 여부:** 예. MVP 완료와 커밋 전 최종 검증이다.

전체 테스트 실행 이유: 명세의 성공 기준과 기존 Phase 1 회귀를 함께 확인하는 최종 release gate임.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

선택적 외부 integration:

```bash
K8S_AGENT_RUN_NETWORK_TESTS=1 \
K8S_AGENT_RUN_TOOL_TESTS=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests/integration -v
```

**권장 커밋:** `test: enforce kubernetes deploy agent mvp criteria`

---

# 4. 태스크 의존관계

```text
Task 1  CLI contract
  └─ Task 2  Run persistence
       ├─ Task 3  Local source
       └─ Task 4  GitHub source/workspace
            └─ Task 5  Phase 1 adapter
                 └─ Task 6  Application Topology
                      ├─ Task 7  LLM semantic resolution
                      └─ Task 8  Kubernetes Intent/policy
                           └─ Task 9  Agent Planner
                                └─ Task 10 Questions/answers
                                     └─ Task 11 Deployment Profile
                                          └─ Task 12 Renderer
                                               └─ Task 13 Validation
                                                    └─ Task 14 Repair
                                                         └─ Task 15 Prepare orchestration
                                                              ├─ Task 16 Resume
                                                              └─ Task 17 Status/explain/export/report
                                                                   └─ Task 18 Advanced stage commands
                                                                        └─ Task 19 Security hardening
                                                                             └─ Task 20 MVP acceptance/release gate
```

Task 3과 Task 4는 Task 2 이후 병렬 구현 가능하다. Task 7과 Task 8은 Task 6 이후 일부 병렬 구현 가능하지만, Task 9 통합 전 interface를 고정해야 한다.

---

# 5. 명세 성공 기준 커버리지

| 성공 기준 | 구현 태스크 |
|---|---|
| 명시적 GitHub/local Source, 생략 금지 | 1, 3, 4 |
| GitHub ref → commit SHA 고정 | 4 |
| local working tree와 fingerprint | 3 |
| 기존 결정론적 분석 보존 | 5 |
| 저장소별 Agent 계획 | 6, 8, 9 |
| 미확정 정보 질문 | 9, 10 |
| 사용자 답변 Profile 기록 | 10, 11 |
| Profile 기반 deterministic rendering | 11, 12 |
| 정적 검증과 제한 리페어 | 13, 14 |
| 모든 자동 결정의 Evidence 연결 | 6, 7, 8, 11 |
| Secret 비유출 | 7, 11, 12, 19 |
| 중단 후 재개 | 2, 15, 16 |
| readiness와 한계 보고 | 13, 17 |
| 단계별 analyze/plan/generate/validate | 1, 18 |
| 동일 Profile 동일 Manifest | 12, 20 |
| fixture 80% manifest-ready | 20 |
| 나머지 명확한 질문/차단 | 10, 20 |
| traceback 숨김 | 1, 15 |
| 오류 원인·해결 방법 | 1, 3, 4, 13, 15 |
| non-interactive 안정 종료 코드 | 10, 15, 20 |

---

# 6. MVP에서 구현하지 않을 항목

다음은 이 계획의 테스트 expectation에서 `not-run`, `unsupported`, 또는 명확한 `BLOCKED`로 처리한다.

- 운영 클러스터 자동 배포
- Container build/startup 검증
- 실제 test cluster rollout/smoke test
- Helm Chart 생성
- GitOps commit/PR
- Source code 자동 수정
- StatefulSet/Operator/CRD 자동 생성
- GitLab/GitHub Enterprise
- Git LFS/Submodule
- image registry push
- production-ready 판정

이 항목을 암묵적으로 부분 구현하지 않는다. Release 2/3/4에서 별도 spec과 구현 계획을 작성한다.

---

# 7. 구현 완료 후 검토 체크리스트

- [ ] 각 태스크가 하나의 사용자 동작, 정책 또는 기술 결과를 완성하는가
- [ ] setup/scaffolding이 별도 무가치 태스크로 분리되지 않았는가
- [ ] 관련 테스트와 최소 구현이 같은 태스크에 있는가
- [ ] 각 태스크가 15~60분 범위로 리뷰 가능한가
- [ ] Red → Green → Refactor 순서가 태스크마다 명시되어 있는가
- [ ] 기존 `preanalyzer` 결정론적 코어를 우회하거나 복제하지 않는가
- [ ] LLM 결과가 Profile을 거치지 않고 renderer로 흐르는 경로가 없는가
- [ ] Secret canary가 로그·산출물·prompt·report 어디에도 나타나지 않는가
- [ ] Source Repository가 자동 수정되지 않는가
- [ ] 전체 테스트를 실행한 태스크에 실행 이유가 먼저 기록되어 있는가
- [ ] 최종 fixture matrix와 exit code matrix가 성공하는가
