# Semantic Agent MVP 구현 계획

## 목표

첫 MVP는 `resolve_runtime_command` 전용 Bounded Semantic Agent로 제한한다. 목적은 Dockerfile `CMD`/`ENTRYPOINT`가 간접 entrypoint를 가리키는 경우, 결정론적 코드가 Semantic Task를 만들고 Agent가 제한된 read-only tool로 실제 runtime command 후보를 찾아 Verifier가 검증하는 흐름을 구현하는 것이다.

프로덕션 구현은 이 문서 이후의 작업이다. 이번 문서는 구현 기준을 고정한다.

## 전역 제약

- 프로덕션 코드를 작성할 때도 결정론적 파서가 항상 먼저 실행된다.
- 결정론적 코드가 Semantic Task와 Agent 실행 여부를 결정한다.
- 하나의 Agent 실행은 하나의 component와 하나의 target field만 처리한다.
- Agent는 허용된 Tool만 사용한다.
- Tool 호출은 budget 안에서 종료한다.
- LLM Candidate의 최대 confidence는 medium이다.
- 실패 또는 증거 부족 시 기존 pipeline은 unresolved 상태로 계속 진행한다.
- 실제 LLM 없는 Fake Agent로 unit/acceptance를 재현할 수 있어야 한다.
- 실제 20B~30B 모델 평가는 integration 또는 evaluation marker로 분리한다.
- 새로운 Python dependency 도입은 구현 시 별도 결정이 필요하다.

## MVP 포함 범위

- Semantic Task 모델
- Semantic Resolution 모델
- Semantic Task Builder
- 제한된 Agent State Machine
- Fake Semantic Agent
- LLM Provider Adapter Interface
- Deterministic Verifier
- Tool allowlist와 budget
- 최소 코드 분석 Tool
- Pipeline 연동
- 단위 테스트와 acceptance fixture
- 실제 모델 평가는 integration 또는 evaluation으로 분리

## MVP 제외 범위

- 범용 LSP 통합
- 전체 Call Graph
- 복잡한 Data Flow
- Kantra 전체 통합
- Move2Kube 런타임 통합
- Draft를 통한 최종 파일 생성
- 파일 수정 Tool
- shell 실행 Tool
- network Tool
- 자동 dependency 설치
- Dockerfile 자유 생성
- Kubernetes YAML 자유 생성

## 초기 Tool 후보

```text
search_code
read_source_range
inspect_entrypoint_script
find_command_target
```

초기 구현은 Python 표준 라이브러리와 기존 코드 스타일을 우선한다. ripgrep 또는 외부 binary 사용은 `확인 필요`다.

## 필요한 fixture

```text
dockerfile-direct-cmd
dockerfile-shell-entrypoint
shell-to-package-script
node-multiple-scripts
python-module-entrypoint
ambiguous-runtime-command
insufficient-runtime-evidence
invalid-evidence-reference
budget-exhausted
```

기존 fixture는 `tests/fixtures/repos/` 아래에 `jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`가 있다. 새 fixture도 같은 구조를 따른다.

## MVP 완료 조건

1. 결정론적 파이프라인에서 완전히 해석된 terminal runtime command가 직접 확인되면 Semantic Agent를 실행하지 않는다.
2. 간접 entrypoint가 발견되면 결정론적 코드가 Semantic Task를 생성한다.
3. Agent는 허용된 Tool만 사용한다.
4. Tool 호출은 설정된 budget 안에서 종료한다.
5. Agent는 근거가 연결된 Candidate만 반환할 수 있다.
6. Verifier는 존재하지 않는 명령과 잘못된 evidence를 거부한다.
7. LLM Candidate는 high confidence가 될 수 없다.
8. 실패 또는 증거 부족 시 기존 파이프라인은 unresolved 상태로 계속 진행한다.
9. 전체 acceptance test는 실제 LLM 없이 Fake Agent로 재현 가능하다.
10. 실제 20B~30B 모델 평가는 별도 marker와 평가 보고서로 분리된다.

## 파일 구조 계획

구현 시 예상 파일이다. 실제 line number는 구현 전 `확인 필요`다.

- Create: `src/preanalyzer/models/semantic.py`
  - `SemanticTask`, `TaskReason`, `KnownCandidate`, `SemanticAgentState`, `SemanticCandidate`, `SemanticResolution`, `VerificationResult`, `ModelCapabilityProfile`
- Create: `src/preanalyzer/semantic/task_builder.py`
  - Evidence/Rule 후보에서 `resolve_runtime_command` task 생성
- Create: `src/preanalyzer/semantic/agent.py`
  - bounded state machine과 provider adapter 호출
- Create: `src/preanalyzer/semantic/fake_agent.py`
  - deterministic test double
- Create: `src/preanalyzer/semantic/provider.py`
  - LLM Provider Protocol
- Create: `src/preanalyzer/semantic/tools.py`
  - read-only tool definitions와 최소 구현
- Create: `src/preanalyzer/semantic/verifier.py`
  - schema/evidence/secret/target field 검증
- Modify: `src/preanalyzer/pipeline.py`
  - Phase 1 이후 optional semantic phase 연결. 정확한 output filename은 `확인 필요`
- Test: `tests/unit/test_semantic_task_builder.py`
- Test: `tests/unit/test_semantic_agent_state_machine.py`
- Test: `tests/unit/test_semantic_tools.py`
- Test: `tests/unit/test_semantic_verifier.py`
- Test: `tests/acceptance/test_semantic_runtime_command.py`
- Fixture: `tests/fixtures/repos/<semantic-fixture-name>/...`

## Task 1: Semantic 계약 모델 추가

목적:

- 문서의 계약을 Pydantic 모델 또는 기존 스타일에 맞는 모델로 옮긴다.

변경 파일:

- Create: `src/preanalyzer/models/semantic.py`
- Modify: `src/preanalyzer/models/__init__.py` 필요 여부 `확인 필요`
- Test: `tests/unit/test_semantic_models.py`

상세 작업:

- `SemanticTaskType` enum 정의
- `VerificationStatus` enum 정의
- `AgentBudget` 모델 정의
- `TaskReason`, `KnownCandidate`, `SemanticTask` 정의
- `ToolTraceRef`, `SemanticCandidate`, `SemanticResolution` 정의
- `VerificationResult`, `ModelCapabilityProfile` 정의
- LLM confidence cap을 모델 validator 또는 verifier 정책으로 둔다. 위치는 `확인 필요`

테스트:

- `resolve_runtime_command` task가 필수 필드 없이 생성되지 않는지 검증
- `parallel_tool_calls: false` 기본값 검증
- `SemanticCandidate.confidence == "high"`가 verifier에서 거부되는 경로를 위한 fixture model 생성

완료 조건:

- 모델이 `model_dump()`로 YAML 직렬화 가능한 dict를 낸다.
- schema invalid 입력은 테스트에서 실패한다.

비목표:

- Agent 실행 구현
- LLM provider 구현

선행 조건:

- 현재 pydantic v2 스타일 확인
- 기존 dataclass/pydantic 혼용 방식을 유지할지 결정

## Task 2: Semantic Task Builder

목적:

- 결정론적 코드가 Agent 실행 여부와 task 생성을 판단하게 한다.

변경 파일:

- Create: `src/preanalyzer/semantic/task_builder.py`
- Test: `tests/unit/test_semantic_task_builder.py`

상세 작업:

- `RuleInferenceSet.runtime_command_candidates`를 입력으로 받는다.
- 완전히 해석된 terminal command는 task를 만들지 않는다.
- Dockerfile command가 script 또는 package script target을 가리키는 경우 `SemanticTask`를 만든다.
- component id와 target field는 하나만 채운다.
- known candidate와 evidence refs를 task에 포함한다.

테스트:

- `dockerfile-direct-cmd`: task 없음
- `dockerfile-shell-entrypoint`: `resolve_runtime_command` task 1개
- `shell-to-package-script`: task 1개
- `node-multiple-scripts`: ambiguous reason code

완료 조건:

- Semantic Task 생성 여부가 LLM 없이 결정된다.
- task가 없는 경우 pipeline은 현재 Phase 1 결과와 동일하게 진행 가능하다.

비목표:

- script 내부 분석
- Verifier 구현

선행 조건:

- Task 1 모델 완료

## Task 3: 최소 코드 분석 Tool

목적:

- Agent가 repository를 자유 탐색하지 않고 read-only 도메인 tool로 좁게 분석하게 한다.

변경 파일:

- Create: `src/preanalyzer/semantic/tools.py`
- Test: `tests/unit/test_semantic_tools.py`

상세 작업:

- `search_code`: component root 안에서 문자열 또는 제한 pattern 검색
- `read_source_range`: 지정 path와 line range 조회
- `inspect_entrypoint_script`: shell script에서 마지막 `exec` 또는 command line 후보 추출
- `find_command_target`: Dockerfile command가 가리키는 script/package script target 해석
- path traversal 방지
- Secret-like line redaction
- source lines budget 계산

테스트:

- component root 밖 파일 접근 거부
- Secret-like value redaction
- script의 `exec uvicorn ...` 후보 추출
- package script target 추출
- max source lines 초과 시 budget error

완료 조건:

- 모든 tool은 read-only다.
- tool result는 source range와 evidence 연결 정보를 가진다.

비목표:

- shell 실행
- LSP
- full parser

선행 조건:

- Task 1 모델 완료

## Task 4: Fake Semantic Agent

목적:

- 실제 LLM 없이 acceptance test를 재현한다.

변경 파일:

- Create: `src/preanalyzer/semantic/fake_agent.py`
- Test: `tests/unit/test_semantic_agent_state_machine.py`

상세 작업:

- `SemanticTask`를 받아 fixture별 deterministic `SemanticResolution` 반환
- allowlist 밖 tool 호출을 시뮬레이션할 수 있는 negative response 지원
- budget exhausted response 지원
- hallucinated command response 지원

테스트:

- 정상 후보 반환
- hallucinated command 반환
- invalid evidence reference 반환
- budget exhausted 반환

완료 조건:

- acceptance test가 실제 LLM 없이 semantic success/failure path를 모두 실행할 수 있다.

비목표:

- 실제 provider call

선행 조건:

- Task 1 모델 완료

## Task 5: LLM Provider Adapter Interface와 Agent State Machine

목적:

- 실제 provider 교체가 가능한 Agent 실행 경계를 만든다.

변경 파일:

- Create: `src/preanalyzer/semantic/provider.py`
- Create: `src/preanalyzer/semantic/agent.py`
- Test: `tests/unit/test_semantic_agent_state_machine.py`

상세 작업:

- `SemanticAgentProvider` protocol 정의
- Native Tool Calling 지원 여부와 JSON envelope fallback 분리
- 매 turn `SemanticAgentState` 재구성
- budget enforcement
- schema retry 최대 1회
- parallel tool call 금지

테스트:

- allowlist 밖 tool 요청 거부
- max tool calls 초과 시 `budget_exhausted`
- schema invalid 후 1회 retry, 재실패 시 unresolved
- tool error 시 `tool_error`

완료 조건:

- Fake provider로 state machine이 deterministic하게 동작한다.
- native tool calling 미지원 provider도 JSON envelope로 동작 가능하다.

비목표:

- vLLM 실제 HTTP 연동
- multi-agent loop

선행 조건:

- Task 3 tool 완료
- Task 4 Fake Agent 또는 Fake Provider 완료

## Task 6: Deterministic Verifier

목적:

- Semantic Agent 결과를 검증 가능한 후보로만 통과시킨다.

변경 파일:

- Create: `src/preanalyzer/semantic/verifier.py`
- Test: `tests/unit/test_semantic_verifier.py`

상세 작업:

- schema 검증
- task id, component id, target field 일치 확인
- evidence refs 존재 확인
- source range가 value를 뒷받침하는지 최소 문자열 기준 검증
- Secret 값 포함 여부 확인
- confidence cap 적용
- existing high-confidence deterministic candidate override 금지
- tool trace와 final evidence 연결 확인

테스트:

- valid runtime command accepted
- nonexistent command rejected
- invalid evidence reference rejected
- wrong target field rejected
- high confidence LLM candidate downgraded 또는 rejected. 정책 선택은 `확인 필요`
- Secret 포함 candidate rejected
- budget exhausted status passthrough

완료 조건:

- Verifier 결과는 지정된 여섯 상태 중 하나다.
- rejected candidate는 candidate stream에 들어가지 않는다.

비목표:

- Reconciliation Engine 전체 구현

선행 조건:

- Task 1 모델 완료
- Task 3 tool result shape 완료

## Task 7: Pipeline 연동

목적:

- 현재 `run_phase1_analysis(...)` 이후 Semantic MVP를 선택적으로 연결한다.

변경 파일:

- Modify: `src/preanalyzer/pipeline.py`
- Create 또는 Modify: output writer 파일. 현재는 `pipeline.py` 내부 `_write_yaml`을 사용하므로 분리 여부 `확인 필요`
- Test: `tests/acceptance/test_semantic_runtime_command.py`

상세 작업:

- 기본 Phase 1 동작은 유지한다.
- semantic 옵션이 꺼져 있으면 output `00~03`은 기존과 동일하다.
- semantic 옵션이 켜져 있고 task가 있으면 task, agent resolution, verification report를 산출한다.
- output filename은 기존 설계의 `04-semantic-analysis.yaml`과 맞출지 별도 `04-semantic-tasks.yaml`, `05-semantic-resolution.yaml`로 둘지 `확인 필요`
- Fake Agent 주입 경로를 제공한다.

테스트:

- direct command fixture에서 Agent 미실행
- shell entrypoint fixture에서 task 생성, Fake Agent, Verifier accepted
- invalid evidence fixture에서 rejected
- budget exhausted fixture에서 unresolved로 계속
- 기존 Phase 1 acceptance는 변경 없이 통과

완료 조건:

- 실제 LLM 없이 semantic acceptance가 통과한다.
- semantic 실패가 pipeline exception이 되지 않는다.

비목표:

- Application Topology Model 생성
- Kubernetes Intent Model 생성

선행 조건:

- Task 2~6 완료

## Task 8: 실제 On-Premise 모델 평가 Harness

목적:

- MVP 구현이 외부 대형 모델에서만 성공하는지 검증하지 않고, 실제 대상 모델에서 평가한다.

변경 파일:

- Create: `tests/evaluation/` 또는 `tests/integration/semantic/`. 위치 `확인 필요`
- Create: `docs/reports/semantic-agent-evaluation-YYYY-MM-DD.md`. 위치 `확인 필요`

상세 작업:

- vLLM 등 OpenAI-compatible endpoint 설정을 env로 받는다.
- fixture별 task를 실행한다.
- success, insufficient_evidence, rejected, budget_exhausted 비율을 기록한다.
- evidence grounding 100% 여부를 기록한다.
- prompt/schema retry 횟수를 기록한다.

테스트:

- 기본 test suite에서는 실행하지 않는다.
- marker 예: `integration` 또는 `evaluation`. 현재 프로젝트는 `unittest` 기반이므로 marker 전략은 `확인 필요`

완료 조건:

- 실제 20B~30B 모델 평가 보고서가 있다.
- 외부 상용 대형 모델에서만 통과한 결과를 완료로 보지 않는다.

비목표:

- CI 기본 실행
- 모델 성능 튜닝 자동화

선행 조건:

- Task 7 pipeline 연동 완료

## 열린 결정 사항

- Semantic 산출물 파일명을 기존 Step 7 이후 번호와 어떻게 맞출지
- `EvidenceModel`에 line location과 excerpt hash를 추가할지, tool evidence namespace를 따로 둘지
- LLM high confidence candidate를 Verifier에서 downgrade할지 reject할지
- 현재 `unittest` 기반에서 integration/evaluation marker를 어떻게 표현할지
- ripgrep 같은 외부 binary를 MVP tool 내부에서 허용할지
- Prompt 전문을 audit log에 저장할지, hash와 template version만 저장할지
