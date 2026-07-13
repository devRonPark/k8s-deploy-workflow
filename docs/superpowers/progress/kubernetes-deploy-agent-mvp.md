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

### Task 8: Target 정책을 적용한 Kubernetes Intent 생성

- 상태: 완료
- commit: `547b65ffc861384260c232c8f6018aff39a1f1ff`
- commit message: `feat(intent): derive target-aware kubernetes intent`
- 변경:
  - Agent-owned `KubernetesIntent`, `IntentCandidate`, `PolicyDecision` 모델 추가
  - development/staging/production target policy와 `PolicyEngine.evaluate()` 추가
  - `IntentBuilder.build(topology, target)`가 Deployment/Service/replica/exposure/secret/storage/resource/probe 후보를 생성
  - external exposure, hostname, Secret, PVC, resource/probe 후보는 confirmation으로 유지
  - production cluster validation은 생성하지 않고, stateful workload 판단은 blocked candidate로 유지
  - 선택적 `analysis/05-kubernetes-intent.yaml` stable output 지원

### Task 9: 현재 상태 기반 Agent Planner와 재계획

- 상태: 완료
- commit: `05beb03fea75f936c3a52c59f108d00a8c9a4e29`
- commit message: `feat(agent): plan repository-specific deployment work`
- 변경:
  - `AgentPlan`, `AgentTask`, `PlanningContext`, `AgentPlanner` 추가
  - topology runtime command conflict와 missing command를 semantic action task로 계획
  - target policy confirmation/blocker 후보를 user question/blocker task로 계획
  - auto-confirmed deployment intent를 manifest generation task로, non-production cluster validation을 validation task로 계획
  - completed task ID를 반영해 재계획 시 다음 action이 완료 task를 건너뜀
  - fixture별 저장소 shape에 따라 다른 plan task가 생성됨을 검증

### Task 10: 사용자 질문, answers file과 non-interactive 차단

- 상태: 완료
- commit: `5923de39c1ea00fc13b4e9acdb1c8aa8b5a46046`
- commit message: `feat(questions): collect explicit deployment decisions`
- 변경:
  - `Question`, `QuestionSet`, `QuestionOption`, `AnswerSet`, `Decision` 모델 추가
  - `QuestionManager.build(intent, plan)`가 external exposure, hostname, Secret, PVC, Stateful, command conflict 질문을 생성
  - stable question ID, evidence refs, options, recommendation, impact, skip impact 보존
  - `AnswerLoader.load(path, questions)`가 unknown question, invalid option, missing required answer를 exit code 3 `QST-201`로 차단
  - `QuestionManager.to_decisions()`가 raw/normalized user answer를 explicit user Decision으로 변환
  - `prepare --non-interactive --answers-file`에서 required bootstrap answer가 없으면 `BLOCKED`로 종료

### Task 11: 추적 가능한 Decision 병합과 immutable Deployment Profile

- 상태: 완료
- commit: `d6e3572d36138632068cecf63cdf34f3ef1c6fba`
- commit message: `feat(profile): merge evidence and user decisions immutably`
- 변경:
  - `DeploymentProfile`, `ProfileValue`, `ProfileConflict`, `ProfileHold` 모델 추가
  - `DeploymentProfileBuilder.build(inputs, previous)`가 Decision과 auto-confirm Intent 후보를 병합
  - user answer > confirmed fact > semantic inference > policy default > rule inference 우선순위 적용
  - 낮은 우선순위와 값이 다르면 conflict로 기록하고 evidence refs 보존
  - unanswered required intent와 blocked intent가 있으면 `renderable=False`로 렌더링 진입 차단
  - profile revision은 previous를 변경하지 않고 새 revision으로 증가, checksum은 동일 입력에서 안정적

### Task 12: Profile 기반 Kubernetes Manifest와 Kustomize 렌더링

- 상태: 완료
- commit: `ddfd2983f39e19d9abcce0529b99fb8c6d7114a4`
- commit message: `feat(render): generate deterministic kubernetes bundles`
- 변경:
  - DNS-safe naming helper 추가
  - Deployment/Service/Ingress/Kustomization dict resource builder 추가
  - stable YAML serializer와 `ManifestRenderer.render(profile, destination)` 추가
  - profile values만 입력으로 base/overlays bundle 생성
  - Service selector와 Pod labels, targetPort와 containerPort 일치 검증
  - external exposure가 `public`일 때만 Ingress 생성, Secret value는 렌더링하지 않음
  - 동일 Profile의 byte-identical bundle checksum 검증

### Task 13: 정적 검증 파이프라인과 manifest-ready 계산

- 상태: 완료
- commit: `f48e86e56c558c0b57c72876bd8ce39b76e2df62`
- commit message: `feat(validation): calculate manifest readiness`
- 변경:
  - `ValidationFinding`, `ValidationStage`, `ValidationReport` 모델 추가
  - YAML syntax, duplicate resource, Service selector, Service targetPort internal validation 추가
  - kubeconform/kustomize adapter skeleton과 tool-missing/not-run 상태 정규화 추가
  - `ValidationOrchestrator.validate(bundle, profile, destination)`가 stage 순서와 manifest-ready를 계산
  - rendered bundle acceptance에서 internal validation ready 상태 검증
  - project-managed kubeconform preflight 확인 완료

### Task 14: 제한된 자동 리페어와 재검증 루프

- 상태: 완료
- commit: `94ac3eee57a347d42d389139a13a4438fc14d224`
- commit message: `feat(repair): add bounded manifest repair loop`
- 변경:
  - allowlisted repair strategy map 추가
  - Service selector/targetPort를 Deployment pod labels/containerPort에 맞추는 bounded repair 추가
  - `RepairController.repair(bundle, profile, report)`가 generated file path guard와 repeated strategy suppression 적용
  - 각 attempt를 `repairs/attempt-N.yaml`로 기록
  - repair 후 `ValidationOrchestrator`로 전체 정적 검증 재실행
  - renderer/validator/profile 전체 회귀 확인 완료

### Task 15: Observe–Decide–Act–Evaluate prepare 오케스트레이션

- 상태: 완료
- commit: `fcd33518e3a0e08de087d6beafdf8a636689a6c3`
- commit message: `feat(agent): orchestrate prepare to manifest readiness`
- 변경:
  - `RunOutcome`, `OrchestrationResult`, `AgentOrchestrator.run(run_id)` 추가
  - `prepare`가 source 확보 후 Phase 1, topology, intent, plan, questions, profile, render, validate, repair 경로를 호출하도록 연결
  - run state를 `ANALYZING`, `WAITING_FOR_USER`, `BLOCKED`, `READY`, `FAILED`, `CANCELLED`로 명확히 전이
  - terminal run에서는 pipeline을 재실행하지 않도록 guard 추가
  - Ctrl+C cancellation, policy blocked exit `4`, validation failure exit `5`, internal error exit `8`, success exit `0` 계약 검증
  - CLI prepare summary에 state와 next action message를 출력하고 outcome exit code를 반환
  - 실제 fixture prepare가 analysis/intent/plan/questions/profile 산출물까지 생성하는 end-to-end 경로 검증

### Task 16: resume과 Source drift 처리

- 상태: 완료
- commit: `209ef498570641f9211141090e64a5dc2bbeff08`
- commit message: `feat(run): resume safely across source changes`
- 변경:
  - `AgentApplication.resume(run_id, drift_policy)` 추가
  - `DriftPolicy`로 `continue-pinned`, `replan`, `new-run` 선택 지원
  - local source fingerprint/head drift를 감지하고 명시적 drift policy 없이는 exit `3`으로 진행 차단
  - GitHub source는 저장된 pinned workspace/source metadata를 사용해 네트워크 refetch 없이 resume
  - runtime tool metadata를 기록하고 stale metadata나 누락된 Phase 1 artifact는 분석 단계부터 재생성
  - unchanged source에서는 기존 Phase 1 artifact를 재사용해 완료된 분석을 재실행하지 않음
  - terminal `READY`/`FAILED`/`BLOCKED`/`CANCELLED` run에 대해 명확한 non-resumable outcome 반환
  - `k8s-agent resume <run-id> [--drift-policy ...]` CLI 연결과 state/run_root summary 출력 추가

### Task 17: status, explain, export와 최종 보고서

- 상태: 완료
- commit: `03c39ea09c5ca319cefbeedba5d2a5527ac0255a`
- commit message: `feat(report): explain and export manifest-ready runs`
- 변경:
  - `FinalReport`, `ExplanationView`, `ExportResult`와 report용 source/validation/resource model 추가
  - `FinalReportBuilder.build(run_id)`가 source/profile/bundle/validation artifact를 집계하고 `final-report.yaml` 생성
  - report summary, validation, generated resources, decision count, limitations, next action 제공
  - `production-ready` 표현 없이 build-verified/cluster-verified 미실행을 limitation으로 명시
  - `FinalReportBuilder.explain()`이 Evidence → Decision → Profile field → Resource trace를 제공하고 Secret 값을 노출하지 않음
  - `status`, `explain`, `export` application method와 CLI handler 연결
  - export는 generated manifest directory만 명시 경로로 복사하며 기존 출력 경로는 `--overwrite` 없이는 거부

### Task 18: 고급 analyze, plan, generate, validate 단계 명령

- 상태: 완료
- commit: `89bacd7ac64262a102ca46ea1a68d7ffde03338d`
- commit message: `feat(cli): expose safe stage-level agent commands`
- 변경:
  - `AgentApplication.analyze(request)`가 source 확보 후 Phase 1과 topology까지만 생성
  - `AgentApplication.plan(run_id)`이 기존 topology에서 intent, questions, agent plan, deployment profile을 생성
  - `AgentApplication.generate(run_id, profile_revision)`이 기존 renderable Deployment Profile만 입력으로 manifest bundle 생성
  - `AgentApplication.validate(run_id)`가 기존 generated bundle과 profile을 읽어 정적 검증 재실행
  - analyze/plan/generate/validate CLI handler와 stage summary 출력 추가
  - plan 전 analysis, profile 전 generate, bundle 전 validate 선행조건 오류 `STAGE-101/201/301` 추가
  - 단계별 완료 event에 command와 입력 revision/result metadata 기록

## 현재 Task

- 현재 Task: Task 19 Trust boundary 보안 강화와 감사 추적
- 다음 Task: Task 19 Trust boundary 보안 강화와 감사 추적

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
- Task 8 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.policy.test_target_policy tests.unit.k8s_agent.analysis.test_intent_builder -v`
  - 결과: 기대한 실패. `k8s_agent.models.intent`와 `k8s_agent.analysis.intent_builder` 미구현으로 실패.
- Task 8 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.policy.test_target_policy tests.unit.k8s_agent.analysis.test_intent_builder -v`
  - 결과: 통과, `Ran 9 tests in 0.014s`, `OK`
- Task 9 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.agent.test_planner tests.acceptance.test_repository_specific_plans -v`
  - 결과: 기대한 실패. `k8s_agent.agent.planner` 미구현으로 실패.
- Task 9 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.agent.test_planner tests.acceptance.test_repository_specific_plans -v`
  - 결과: 통과, `Ran 9 tests in 0.083s`, `OK`
- Task 10 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.questions.test_manager tests.unit.k8s_agent.questions.test_answers tests.cli.test_non_interactive_questions -v`
  - 결과: 기대한 실패. `k8s_agent.models.decision`과 `k8s_agent.questions` 미구현으로 실패.
- Task 10 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.questions.test_manager tests.unit.k8s_agent.questions.test_answers tests.cli.test_non_interactive_questions -v`
  - 결과: 통과, `Ran 7 tests in 0.460s`, `OK`
- Task 11 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.profile.test_builder tests.acceptance.test_deployment_profile -v`
  - 결과: 기대한 실패. `k8s_agent.profile.builder` 미구현으로 실패.
- Task 11 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.profile.test_builder tests.acceptance.test_deployment_profile -v`
  - 결과: 통과, `Ran 6 tests in 0.001s`, `OK`
  - 전체 테스트 실행 이유: 공통 Decision/Profile 계약이 Phase 1 이후 전체 기능 묶음의 연결점이 됨.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 428 tests in 2.548s`, `OK (skipped=1)`
- Task 12 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/render -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_manifest_renderer tests.acceptance.test_manifest_reproducibility -v`
  - 결과: 기대한 실패. `k8s_agent.render.names`와 `k8s_agent.render.resources` 미구현으로 실패.
- Task 12 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/render -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_manifest_renderer tests.acceptance.test_manifest_reproducibility -v`
  - 결과: 통과, unit `Ran 4 tests`, acceptance `Ran 3 tests`, `OK`
- Task 13 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/validation -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_manifest_validation -v`
  - 결과: 기대한 실패. `k8s_agent.validation.kubeconform`와 `k8s_agent.validation.internal` 미구현으로 실패.
- Task 13 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/validation -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_manifest_validation -v`
  - 결과: 통과, unit `Ran 4 tests`, acceptance `Ran 1 test`, `OK`
  - kubeconform preflight: `python3 scripts/ensure_kubeconform.py --check`
  - 결과: 통과, `.tools/kubeconform/v0.8.0/linux-amd64/kubeconform`
- Task 14 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/repair -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_repair_loop -v`
  - 결과: 기대한 실패. `k8s_agent.repair.controller`와 `k8s_agent.repair.strategies` 미구현으로 실패.
- Task 14 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests/unit/k8s_agent/repair -p 'test_*.py' -v && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_repair_loop -v`
  - 결과: 통과, unit `Ran 4 tests`, acceptance `Ran 1 test`, `OK`
  - 전체 테스트 실행 이유: 리페어가 공통 생성물과 검증 결과를 변경하므로 기존 재현성과 정적 검증 회귀를 확인해야 함.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 433 tests in 59.585s`, `OK (skipped=1)`
- Task 15 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.agent.test_orchestrator tests.cli.test_prepare_black_box tests.acceptance.test_prepare_end_to_end -v`
  - 결과: 기대한 실패. `k8s_agent.agent.orchestrator` 미구현, `PrepareOutcome.state` 부재, CLI가 prepare 상태/exit code를 반환하지 않아 실패.
- Task 15 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.agent.test_orchestrator tests.cli.test_prepare_black_box tests.acceptance.test_prepare_end_to_end -v`
  - 결과: 통과, `Ran 12 tests in 1.017s`, `OK`
  - 전체 테스트 실행 이유: CLI부터 기존 Phase 1, semantic, Profile, renderer, validator, repair까지 전체 호출 경로가 연결됨.
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
  - 결과: 통과, `Ran 437 tests in 61.007s`, `OK (skipped=1)`
- Task 16 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_resume tests.cli.test_resume_black_box -v`
  - 결과: 기대한 실패. `AgentApplication.resume` 미구현, `resume` CLI skeleton, `--drift-policy` 미지원으로 실패.
- Task 16 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_resume tests.cli.test_resume_black_box -v`
  - 결과: 통과, `Ran 10 tests in 2.885s`, `OK`
  - 인접 회귀 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_resume tests.cli.test_resume_black_box tests.unit.k8s_agent.agent.test_orchestrator tests.cli.test_prepare_black_box tests.acceptance.test_prepare_end_to_end tests.unit.k8s_agent.run.test_manager -v`
  - 결과: 통과, `Ran 25 tests in 3.915s`, `OK`
- Task 17 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.reporting.test_final_report tests.cli.test_status_explain_export -v`
  - 결과: 기대한 실패. `k8s_agent.reporting` 미구현과 `status`/`explain`/`export` skeleton으로 실패.
- Task 17 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.reporting.test_final_report tests.cli.test_status_explain_export -v`
  - 결과: 통과, `Ran 6 tests in 2.100s`, `OK`
  - 인접 회귀 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.reporting.test_final_report tests.cli.test_status_explain_export tests.cli.test_resume_black_box tests.cli.test_prepare_black_box tests.cli.test_prepare_arguments tests.cli.test_non_interactive_questions -v`
  - 결과: 통과, `Ran 20 tests in 6.871s`, `OK`
- Task 18 Red:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_stage_commands tests.cli.test_advanced_commands -v`
  - 결과: 기대한 실패. `AgentApplication.analyze/plan/generate/validate` 미구현과 advanced command skeleton으로 실패.
- Task 18 Green:
  - 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_stage_commands tests.cli.test_advanced_commands -v`
  - 결과: 통과, `Ran 9 tests in 3.439s`, `OK`
  - 인접 회귀 확인: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.k8s_agent.test_stage_commands tests.cli.test_advanced_commands tests.cli.test_prepare_arguments tests.cli.test_prepare_black_box tests.cli.test_resume_black_box tests.cli.test_status_explain_export tests.unit.k8s_agent.test_resume -v`
  - 결과: 통과, `Ran 31 tests in 9.984s`, `OK`

## 전체 테스트 실행 이유와 결과

- 시작 기준선에서 전체 테스트를 실행했다.
- Task 1~4 완료 조건에는 전체 테스트가 필요하지 않았다. 신규 Agent 애플리케이션 패키지 내부 변경이며 기존 분석 코어를 변경하지 않았다.
- Task 5 완료 시 전체 테스트를 실행했다. 이유: 기존 결정론적 분석 API와 Agent adapter의 경계가 모든 parser/fixture에 영향을 줄 수 있음.
- Task 6 완료 조건에는 전체 테스트가 필요하지 않았다. Phase 1 모델은 소비만 하고 변경하지 않는다.
- Task 7 완료 시 전체 테스트를 실행했다. 이유: 기존 semantic task routing과 verifier의 public interface가 Agent에서 직접 사용됨.
- Task 8 완료 조건에는 전체 테스트가 필요하지 않았다. 신규 정책과 Intent 경계에 한정된다.
- Task 9 완료 조건에는 전체 테스트가 필요하지 않았다. Planner 자체와 fixture별 plan만 검증한다.
- Task 10 완료 조건에는 전체 테스트가 필요하지 않았다. 질문·답변 기능 묶음에 한정된다.
- Task 11 완료 시 전체 테스트를 실행했다. 이유: 공통 Decision/Profile 계약이 Phase 1 이후 전체 기능 묶음의 연결점이 됨.
- Task 12 완료 조건에는 전체 테스트가 필요하지 않았다. Profile 계약 이후의 독립 renderer 기능이다.
- Task 13 완료 조건에는 전체 테스트가 필요하지 않았다. Renderer 결과에 대한 검증 기능 묶음에 한정한다.
- Task 14 완료 시 전체 테스트를 실행했다. 이유: 리페어가 공통 생성물과 검증 결과를 변경하므로 기존 재현성과 정적 검증 회귀를 확인해야 함.
- Task 15 완료 시 전체 테스트를 실행했다. 이유: CLI부터 기존 Phase 1, semantic, Profile, renderer, validator, repair까지 전체 호출 경로가 연결됨.
- Task 16 완료 조건에는 전체 테스트가 필요하지 않았다. 기존 prepare 수직 경로는 인접 회귀 테스트로 확인하고 resume 분기에 한정했다.
- Task 17 완료 조건에는 전체 테스트가 필요하지 않았다. read-only 조회와 generated manifest export 기능에 한정했다.
- Task 18 완료 조건에는 전체 테스트가 필요하지 않았다. 기존 application action을 재사용하는 고급 진입점과 선행조건에 한정했다.

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
- Task 8은 기존 `preanalyzer.models.intent`를 변경하지 않고 Agent-owned intent model을 별도로 추가했다.
- Task 9 planner는 manifest/profile/question 구현을 직접 수행하지 않고, 다음 task들이 소비할 action/이유/근거/완료조건만 결정론적으로 계획한다.
- Task 10의 CLI non-interactive 검사는 Task 15 전체 orchestration 전까지 bootstrap 질문 세트를 사용해 answers file 계약과 BLOCKED exit code를 검증한다.
- Task 11 profile은 아직 renderer 입력으로 필요한 최소 JSON-pointer values/holds/conflicts 계약만 보존하고, 구체 Kubernetes resource shape은 Task 12에서 생성한다.
- Task 12 renderer는 Deployment Profile만 읽고, Evidence/Topology/Intent를 직접 조회하지 않는다.
- Task 13 external adapters는 실제 tool 실행 전 단계로 상태 정규화와 stage 계약을 고정했다.
- Task 14 repair는 Source와 Profile을 수정하지 않고 ManifestBundle에 포함된 generated file만 변경한다.
- Task 15 prepare orchestration은 아직 generated manifest로 진행 가능한 profile이 없으면 `WAITING_FOR_USER`를 성공 exit `0`으로 반환한다. non-interactive 실제 answer 재적용과 resume continuation은 Task 16 이후 범위에서 다룬다.
- Task 15 validation은 기존 Task 13 기본값과 동일하게 `run_external=False` internal validation 경로를 사용한다. kubeconform pass/fail이 필요한 sample repo batch 검증은 Task 19/20 completion 범위에서 수행한다.
- Task 16 `continue-pinned`는 저장된 source metadata와 기존 analysis artifact를 신뢰해 진행한다. source drift가 있고 tool metadata도 stale인 조합은 안전하게 재분석하지 않고 사용자가 `replan` 또는 `new-run`을 선택해야 하는 운영 케이스로 남긴다.
- Task 16 `new-run`은 현재 drifted local source에서 새 run을 생성한다. GitHub source는 저장된 pinned workspace를 기본으로 하며 refetch하지 않는다.
- Task 17 report는 기존 run artifact를 집계하는 read-only view로 구현했고, status 호출 시 최신 `final-report.yaml`을 함께 갱신한다.
- Task 17 explain은 MVP 범위에서 profile decision/field와 generated resource refs를 연결한다. 더 깊은 line-level Evidence traversal은 기존 evidence refs를 보존해 후속 고도화 지점으로 남긴다.
- Task 18 stage commands는 Run state를 강제로 READY/FAILED로 전환하지 않고 산출물과 event를 갱신한다. 최종 readiness state 전이는 prepare/resume 오케스트레이션과 Task 20 acceptance에서 보강한다.

## Blocker

- 없음.

## 다음 Task

- Task 19: Trust boundary 보안 강화와 감사 추적
