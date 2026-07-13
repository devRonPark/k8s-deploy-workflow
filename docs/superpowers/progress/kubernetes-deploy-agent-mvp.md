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

- 상태: 완료
- commit: `834efc698bb5be90bfc5015c966e4b3656b29b71`
- commit message: `feat(source): resolve local repositories and fingerprints`
- 변경:
  - `RepositorySource`, `GitMetadata`, `SourceFingerprint`, `ScanLimits` 모델 추가
  - `LocalSourceResolver.resolve(path, acquired_at)` 추가
  - `GitRunner` argument-list 기반 Git 조회 추가
  - tracked/untracked 현재 파일 내용 기반 deterministic fingerprint 추가
  - `.git`, `.k8s-agent`, binary, oversized, source 밖 symlink 제외 처리 추가

### Task 4: GitHub Repository ref 고정과 격리 Workspace

- 상태: 완료
- commit: `cfb91df8fcbe59f3137664bbe2aa226a9a3cb33e`
- commit message: `feat(source): pin github refs in isolated workspaces`
- 변경:
  - `GitHubSourceResolver.acquire()` 추가
  - GitHub HTTPS/SSH URL normalization과 embedded credential 제거 추가
  - `git init`, sanitized remote, depth-1 fetch, detached checkout 흐름 추가
  - `requested_ref`와 `resolved_commit`을 `AcquiredSource`로 기록
  - `WorkspaceManager`로 source/generated workspace 분리 및 cleanup 추가
  - Git 실행 시 `shell=False`, argument list, LFS smudge/prompt 비활성 env 적용

### Task 5: 기존 Phase 1 분석을 Run 산출물 체계에 통합

- 상태: 완료
- commit: `98dc0688ee72e7862daebe01b3ad30aa4c511097`
- commit message: `feat(analysis): integrate phase1 outputs into agent runs`
- 변경:
  - `Phase1Adapter.run(source, run_id)` 추가
  - 기존 `preanalyzer.pipeline.run_phase1_analysis`를 thin adapter로 호출
  - Run Directory의 `analysis/00`~`03` 산출물 생성
  - 각 산출물 checksum 계산과 `phase1_completed` event 기록
  - parse warning이 Run 전체 실패로 전환되지 않고 기존 Evidence warning으로 보존됨을 검증

### Task 6: Evidence 기반 Application Topology 생성

- 상태: 완료
- commit: `a2e1c2905f024e49cf5de9efee7d57b9e9e98625`
- commit message: `feat(topology): build evidence-linked application topology`
- 변경:
  - `ApplicationTopology`, `ApplicationComponent`, evidence-linked runtime/port/command/dependency/secret 모델 추가
  - `TopologyBuilder.build(phase1)`가 Phase 1 Evidence/Rule Inference 산출물을 읽어 component 중심 topology로 병합
  - 충돌하는 runtime command를 확정하지 않고 `conflicts`에 evidence ref와 함께 기록
  - Secret은 이름과 사용 위치 메타데이터만 topology에 포함
  - `analysis/04-application-topology.yaml`을 안정적인 component/field ordering으로 생성

### Task 7: 구조화 LLM Gateway와 기존 runtime-command semantic task 실행

- 상태: 완료
- commit: `d26069e3ffa10a00d9fa977b4cc1dd2452fcc7b0`
- commit message: `feat(llm): execute verified semantic runtime tasks`
- 변경:
  - Agent-owned LLM redaction boundary 추가
  - OpenAI-compatible decision provider 추가: injectable transport, timeout retry, optional Authorization header
  - `LLMGateway.execute(task, context)`가 기존 semantic agent/tool/verifier를 호출하고 provider/model/prompt metadata를 보존
  - `SemanticActionExecutor.resolve_runtime_commands(topology, phase1)`가 Phase 1 산출물에서 runtime command semantic task를 만들고 검증 결과를 반환
  - provider schema error retry, unavailable fallback, allowlist 밖 tool 차단, verifier rejection을 Agent 경계에서 검증

## 현재 Task

- 현재 Task: Task 8 Target 정책을 적용한 Kubernetes Intent 생성
- 다음 Task: Task 8 Target 정책을 적용한 Kubernetes Intent 생성

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
- Task 4 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.source.test_github tests.unit.k8s_agent.source.test_workspace -v`
  - 결과: 기대한 실패. `k8s_agent.source.github`와 `k8s_agent.source.workspace` 미구현으로 실패.
- Task 4 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.source.test_github tests.unit.k8s_agent.source.test_workspace -v`
  - 결과: 통과, `Ran 4 tests in 0.003s`, `OK`
  - 패키지 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 통과, `Ran 10 tests in 0.063s`, `OK`
  - 선택적 실제 GitHub integration: 실행하지 않음. `K8S_AGENT_RUN_NETWORK_TESTS=1` opt-in 테스트이며 현재 Task 완료에 필수 아님.
- Milestone 1 Review:
  - reviewer: subagent `Aristotle`
  - range: `9252b708a5b6e71ac1145872d0cd96076c532524..cfb91df8fcbe59f3137664bbe2aa226a9a3cb33e`
  - 결과: Critical 4건, Important 4건, Minor 3건 발견. Milestone 2 진행 전 trust boundary와 source persistence 수정 필요.
- Milestone 1 Review Fix Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/run -p 'test_*.py' -v`
  - 결과: 기대한 실패. run id path traversal 미차단.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 기대한 실패. optional locks 미설정, 민감 파일 fingerprint 포함, GitHub hardening 부족, credential URL variant 미마스킹, workspace traversal 미차단.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments.PrepareArgumentTests.test_prepare_accepts_production_target -v`
  - 결과: 기대한 실패. valid prepare가 run/source.yaml을 만들지 않는 stub 동작.
- Milestone 1 Review Fix Green:
  - commit: `369e030bf1d5b9e04f208c461192437b22582b6a`
  - commit message: `fix(security): harden milestone1 source boundaries`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments tests.unit.k8s_agent.test_errors -v`
  - 결과: 통과, `Ran 10 tests in 0.461s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/run -p 'test_*.py' -v`
  - 결과: 통과, `Ran 7 tests in 0.012s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 통과, `Ran 13 tests in 0.068s`, `OK`
- Milestone 1 Re-review:
  - reviewer: subagent `Anscombe`
  - range: `9252b708a5b6e71ac1145872d0cd96076c532524..2285f02c9f1473797d7844fdd62d3cd0b7b569ba`
  - 결과: Critical 없음. Important 1건: `GitRunner`가 inherited Git/SSH execution env를 scrub하지 않음.
- Milestone 1 Re-review Fix:
  - commit: `1abc6fbd08e84d626aeae99eb1fe42ec40e337fe`
  - commit message: `fix(source): scrub git subprocess environment`
  - 변경: `GitRunner` 기본 subprocess 환경을 allowlist로 제한하고 caller-provided hardening env만 추가.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.source.test_git_runner -v`
  - 결과: 통과, `Ran 1 test in 0.002s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.cli.test_prepare_arguments tests.unit.k8s_agent.test_errors -v`
  - 결과: 통과, `Ran 10 tests in 0.702s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/run -p 'test_*.py' -v`
  - 결과: 통과, `Ran 7 tests in 0.023s`, `OK`
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/source -p 'test_*.py' -v`
  - 결과: 통과, `Ran 14 tests in 0.098s`, `OK`
- Task 5 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.analysis.test_phase1_adapter tests.acceptance.test_agent_phase1_integration tests.acceptance.test_phase1_deterministic_outputs -v`
  - 결과: 기대한 실패. `k8s_agent.analysis.phase1_adapter` 미구현으로 실패.
- Task 5 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.analysis.test_phase1_adapter tests.acceptance.test_agent_phase1_integration tests.acceptance.test_phase1_deterministic_outputs -v`
  - 결과: 통과, `Ran 4 tests in 0.080s`, `OK`
  - 전체 테스트 실행 이유: 기존 결정론적 분석 API와 Agent adapter의 경계가 모든 parser/fixture에 영향을 줄 수 있음.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 412 tests in 1.903s`, `OK (skipped=1)`
- Task 6 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.analysis.test_topology_builder -v`
  - 결과: 기대한 실패. `k8s_agent.analysis.topology_builder` 미구현으로 실패.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.analysis.test_topology_builder tests.acceptance.test_application_topology -v`
  - 결과: 기대한 실패. `TOPOLOGY_ARTIFACT`와 topology YAML writer 미구현으로 실패.
- Task 6 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.analysis.test_topology_builder tests.acceptance.test_application_topology -v`
  - 결과: 통과, `Ran 4 tests in 0.115s`, `OK`
- Task 7 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.llm.test_redaction tests.unit.k8s_agent.llm.test_gateway tests.unit.test_semantic_task_builder tests.unit.test_semantic_verifier tests.acceptance.test_runtime_command_semantic_resolution -v`
  - 결과: 기대한 실패. `k8s_agent.llm`과 `k8s_agent.agent` 미구현으로 실패.
- Task 7 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.llm.test_redaction tests.unit.k8s_agent.llm.test_gateway tests.unit.test_semantic_task_builder tests.unit.test_semantic_verifier tests.acceptance.test_runtime_command_semantic_resolution -v`
  - 결과: 통과, `Ran 62 tests in 0.041s`, `OK`
  - 전체 테스트 실행 이유: 기존 semantic task routing과 verifier의 public interface가 Agent에서 직접 사용됨.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 417 tests in 2.266s`, `OK (skipped=1)`

## 전체 테스트 실행 이유와 결과

- 시작 기준선에서 전체 테스트를 실행했다.
- Task 1~4 완료 조건에는 전체 테스트가 필요하지 않았다. 신규 Agent 애플리케이션 패키지 내부 변경이며 기존 분석 코어를 변경하지 않았다.
- Task 5 완료 시 전체 테스트를 실행했다. 이유: 기존 결정론적 분석 API와 Agent adapter의 경계가 모든 parser/fixture에 영향을 줄 수 있음.
- Task 6 완료 조건에는 전체 테스트가 필요하지 않았다. Phase 1 모델은 소비만 하고 변경하지 않는다.
- Task 7 완료 시 전체 테스트를 실행했다. 이유: 기존 semantic task routing과 verifier의 public interface가 Agent에서 직접 사용됨.

## 설계 결정 또는 계획과의 차이

- `--debug`는 CLI validation 오류에서도 traceback을 표시한다. 기본 모드에서는 traceback을 숨긴다.
- 현재 `prepare`는 Milestone 1 범위의 run/source artifact만 생성한다. 전체 Observe-Decide-Act-Evaluate agent loop는 Task 15 범위다.
- 구현 계획 파일은 현재 worktree에서 처음 추적되는 기준 문서로 함께 보존한다.
- Run 저장소 테스트에서는 temp directory를 Run root로 주입한다. 기본 `${K8S_AGENT_HOME}` 정책은 Task 15 application orchestration에서 연결한다.
- Task 3 fingerprint는 기존 `preanalyzer.path_safety`의 symlink boundary walk를 재사용하고 Agent state exclusion만 추가했다.
- Task 4 실제 네트워크 GitHub 테스트는 opt-in으로 남겼고 unit 테스트는 fake Git runner로 command construction과 Secret masking을 검증했다.
- Milestone 1 review 후 다음을 보강했다: local Git metadata 조회에 `GIT_OPTIONAL_LOCKS=0`, remote Git hardening env/config, run id traversal guard, credential URL variant sanitization, sensitive file fingerprint exclusion, valid local `prepare`의 run/source.yaml persistence.
- Milestone 1 re-review 후 `GitRunner`가 inherited `GIT_*`, askpass, SSH command, protocol override 환경변수를 전달하지 않도록 allowlist 환경으로 변경했다.
- Task 6 `TopologyBuilder.build_from_models()`는 pure merge 로직으로 유지하고, `TopologyBuilder.build()`만 Phase 1 파일 I/O와 `04-application-topology.yaml` 생성을 담당한다.
- Task 7은 기존 `preanalyzer.semantic.agent`를 실행 엔진으로 재사용하고 Agent 패키지에는 redaction, provider transport, metadata wrapping, action executor 경계만 추가했다.

## Blocker

- 없음.

## 다음 Task

- Task 8: Target 정책을 적용한 Kubernetes Intent 생성
