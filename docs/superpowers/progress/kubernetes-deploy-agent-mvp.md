# Kubernetes Deploy Agent MVP Progress

## 기준

- 기준 commit: `9252b708a5b6e71ac1145872d0cd96076c532524`
- 현재 브랜치: `feat/k8s-deploy-agent-mvp`
- worktree: `/home/daolts/k8s-deploy-workflow-agent-mvp`
- 구현 계획: `docs/superpowers/plans/2026-07-13-kubernetes-deploy-agent-mvp-implementation-plan.md`

## 완료된 Task

### Task 1: 목표 중심 CLI 입력 계약과 오류 체계

- 상태: 완료
- commit: `0de50d58ae540c2d792943e600e1d4b67ac5c3e4`
- commit message: `feat(cli): add explicit source contract and error codes`
- 변경:
  - `k8s_agent.cli.main(argv)` 추가
  - `AgentError`와 오류 포맷터 추가
  - `prepare`, `resume`, `status`, `explain`, `export`, `analyze`, `plan`, `generate`, `validate` 명령 skeleton 추가
  - `--repo-url`/`--local-path`, `--ref`, `--target`, `--non-interactive`, `--answers-file`, `--debug` 입력 검증 추가
  - `k8s-agent` console script 등록

### Task 2: 영속 Run 상태, 상태 전이와 append-only Event Log

- 상태: 완료
- commit: `d74655d6139b91015e0c67b4a4c04ae3936d336f`
- commit message: `feat(run): persist state transitions and event log`
- 변경:
  - `RunRecord`, `RunState`, `RunSource`, `RunEvent` 모델 추가
  - `RunStore` YAML 저장/로드, atomic write, lock file guard 추가
  - `EventLog` append-only JSONL 기록 추가
  - `RunManager.create()`와 `RunManager.transition()` 추가
  - 잘못된 상태 전이 `RUN-201`, lock contention `RUN-202` 오류 추가
  - `AgentError`가 traceback metadata와 error code string을 안전하게 보존하도록 수정

### Task 3: 로컬 Repository 확보와 재현 가능한 snapshot fingerprint

- 상태: 완료, commit 예정: `feat(source): resolve local repositories and fingerprints`
- 변경:
  - `RepositorySource`, `GitMetadata`, `SourceFingerprint`, `ScanLimits` 모델 추가
  - `LocalSourceResolver.resolve(path, acquired_at)` 추가
  - `GitRunner` argument-list 기반 Git 조회 추가
  - tracked/untracked 현재 파일 내용 기반 deterministic fingerprint 추가
  - `.git`, `.k8s-agent`, binary, oversized, source 밖 symlink 제외 처리 추가

## 현재 Task

- 현재 Task: Task 3 검증 및 커밋
- 다음 Task: Task 4 GitHub Repository ref 고정과 격리 Workspace

## 실행한 테스트와 결과

- Baseline:
  - 전체 테스트 실행 이유: isolated worktree 시작 기준선 확인. 기존 분석 코어와 acceptance fixture가 현재 HEAD에서 통과하는지 확인하기 위함.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 378 tests in 1.486s`, `OK (skipped=1)`
- Task 1 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments tests.unit.k8s_agent.test_errors -v`
  - 결과: 기대한 실패. `k8s_agent.cli`와 `k8s_agent.errors` 미구현으로 실패.
- Task 1 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments tests.unit.k8s_agent.test_errors -v`
  - 결과: 통과, `Ran 9 tests in 0.268s`, `OK`
- Task 2 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/run -p 'test_*.py' -v`
  - 결과: 기대한 실패. `k8s_agent.models.run` 미구현으로 실패.
- Task 2 Debug:
  - 현상: `AgentError`가 `frozen=True` dataclass로 선언되어 Python/unittest의 `__traceback__` 재할당을 막음.
  - 조치: 실패 재현 테스트를 추가한 뒤 `AgentError`를 mutable dataclass로 변경하고 `str(error)`에 code를 포함.
- Task 2 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/run -p 'test_*.py' -v`
  - 결과: 통과, `Ran 6 tests in 0.010s`, `OK`
  - 회귀 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments tests.unit.k8s_agent.test_errors -v`
  - 결과: 통과, `Ran 10 tests in 0.258s`, `OK`
- Task 3 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 기대한 실패. `k8s_agent.source.local`과 `k8s_agent.source.fingerprint` 미구현으로 실패.
- Task 3 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_local.py' -v`
  - 결과: 통과, `Ran 4 tests in 0.049s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.source.test_fingerprint -v`
  - 결과: 통과, `Ran 2 tests in 0.004s`, `OK`
  - 패키지 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 통과, `Ran 6 tests in 0.052s`, `OK`

## 전체 테스트 실행 이유와 결과

- 시작 기준선에서만 전체 테스트를 실행했다.
- Task 1, Task 2, Task 3 완료 조건에는 전체 테스트가 필요하지 않다. 신규 Agent 애플리케이션 패키지 내부 변경이며 기존 분석 코어를 변경하지 않았다.

## 설계 결정 또는 계획과의 차이

- `--debug`는 CLI validation 오류에서도 traceback을 표시한다. 기본 모드에서는 traceback을 숨긴다.
- 아직 실제 prepare orchestration은 실행하지 않고 검증 통과 요청을 stub으로 수락한다. 이는 Task 1 범위와 일치한다.
- 구현 계획 파일은 현재 worktree에서 처음 추적되는 기준 문서로 함께 보존한다.
- Run 저장소 테스트에서는 temp directory를 Run root로 주입한다. 기본 `${K8S_AGENT_HOME}` 정책은 Task 15 application orchestration에서 연결한다.
- Task 3 fingerprint는 기존 `preanalyzer.path_safety`의 symlink boundary walk를 재사용하고 Agent state exclusion만 추가했다.

## Blocker

- 없음.

## 다음 Task

- Task 4: GitHub Repository ref 고정과 격리 Workspace
