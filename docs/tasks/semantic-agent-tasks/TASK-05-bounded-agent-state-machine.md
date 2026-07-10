# TASK-05 — Fake Decision Provider 기반 Bounded Semantic Agent State Machine

현재 구현된 다음 요소를 연결하는 제한된 Semantic Agent 실행 루프를 구현하라.

```text
SemanticTask
→ AgentDecisionProvider
→ 단일 Tool 실행
→ 구조화된 Observation과 Evidence 축적
→ 다음 Decision
→ SemanticResolution
→ Deterministic Verifier
→ SemanticAgentRunResult
```

이번 단계에서는 실제 LLM이나 HTTP API를 사용하지 않는다.

`FakeDecisionProvider`를 통해 Agent 실행 흐름, Tool allowlist, 누적 budget, 종료 조건, Verifier 연결을 재현 가능하게 테스트한다.

## 핵심 전제

대상 모델은 20B~30B급 On-Premise LLM이다.

State Machine은 다음 원칙을 코드에서 강제해야 한다.

1. 한 실행은 하나의 `SemanticTask`만 처리한다.
2. 한 Turn에는 하나의 Tool만 호출한다.
3. Parallel Tool Calling은 허용하지 않는다.
4. Tool은 Task의 allowlist 안에서만 호출한다.
5. Tool 호출 수와 Agent Turn 수를 제한한다.
6. Repository 전체 또는 전체 대화 이력을 상태에 누적하지 않는다.
7. Tool 원문 전체보다 구조화된 Evidence와 Observation을 사용한다.
8. Budget 초과 시 Provider를 다시 호출하지 않는다.
9. Tool 또는 Provider 오류를 구조화된 종료 상태로 반환한다.
10. Verifier를 통과하지 않은 Candidate는 수용하지 않는다.

## 작업 전 확인

다음을 먼저 읽어라.

- `docs/design/semantic-agent-architecture.md`
- `docs/design/semantic-agent-contracts-and-policies.md`
- `docs/decisions/ADR-004-bounded-onprem-semantic-agent.md`
- `docs/plans/semantic-agent-mvp-plan.md`
- `src/preanalyzer/models/semantic.py`
- `src/preanalyzer/models/semantic_tools.py`
- `src/preanalyzer/semantic/task_builder.py`
- `src/preanalyzer/semantic/tools/`
- `src/preanalyzer/semantic/verifier.py`
- 관련 단위 테스트

현재 모델과 함수의 실제 이름 및 필드를 우선 사용한다.

## Ambiguous 정책

현재 정책을 유지한다.

- 추천 Candidate는 없다.
- 검증을 통과한 Candidate가 한 개 이상이면 `VerificationStatus.ambiguous`
- 검증 통과 Candidate가 하나뿐이어도 Verifier가 `accepted`로 승격하지 않음
- 검증 통과 Candidate가 없으면 `VerificationStatus.rejected`

이 의미를 코드 주석 또는 관련 문서에 최소한으로 명시한다.

## 권장 구현 위치

```text
src/preanalyzer/models/semantic_agent.py
src/preanalyzer/semantic/agent.py
src/preanalyzer/semantic/fake_provider.py

tests/unit/test_semantic_agent_models.py
tests/unit/test_semantic_agent.py
tests/unit/test_fake_decision_provider.py
```

현재 프로젝트 규모에 맞게 파일을 합칠 수 있지만 다음 책임은 구분한다.

- Agent 실행 모델
- Decision Provider Protocol
- Fake Provider
- State Machine
- Tool 실행
- Verifier 호출

## Agent Action 계약

Decision Provider가 반환하는 행동은 정확히 두 종류다.

```text
tool_call
resolution
```

### ToolCallAction

최소 필드:

```text
action_type
tool_name
arguments
reason_code
```

정책:

- `action_type = tool_call`
- 한 Action에는 하나의 Tool만 존재
- 여러 Tool Call 배열 금지
- `arguments`는 raw dict를 허용하되 Tool Registry에서 Pydantic 검증
- 긴 reasoning이나 chain-of-thought 필드 금지

### ResolutionAction

최소 필드:

```text
action_type
resolution
```

정책:

- `action_type = resolution`
- `resolution`은 기존 `SemanticResolution`
- Candidate 검증은 Deterministic Verifier가 담당

`AgentAction`은 Pydantic discriminated union 또는 명시적 union으로 구현한다.

## AgentDecisionProvider Protocol

권장 인터페이스:

```python
class AgentDecisionProvider(Protocol):
    def decide(
        self,
        context: SemanticDecisionContext,
    ) -> AgentAction:
        ...
```

초기 구현은 동기식으로 유지한다.

Provider 책임:

- 현재 구조화된 상태를 보고 다음 Action 하나 반환

Provider 비책임:

- Tool 직접 실행
- Repository 파일 직접 접근
- allowlist 검사
- Budget 관리
- Tool Evidence 생성
- Candidate 검증
- 최종 Candidate 채택

## Runtime State와 Decision Context

### SemanticAgentState

State Machine 내부 상태 최소 필드:

```text
task
turn_count
tool_call_count
distinct_tools_used
files_read
source_lines_returned
tool_results
tool_call_records
terminal_resolution
```

Repository 절대 경로는 직렬화 산출물에 포함하지 않는다.

### SemanticDecisionContext

Provider에 전달하는 최소 상태:

```text
task_id
task_type
component_id
target_field
reason
known_candidates
available_tools
collected_evidence
observations
remaining_budget
```

포함 금지:

- Repository 절대 경로
- Repository 전체 파일 목록
- 전체 파일 원문
- 전체 대화 이력
- Secret 값
- Python exception
- Verifier 내부 구현 정보

매 Turn마다 현재 State에서 Decision Context를 새로 구성한다.

## Tool Call Record

`SemanticToolCallRecord` 최소 필드:

```text
tool_call_id
turn_index
tool_name
arguments
result_status
evidence_refs
usage
```

Tool Call ID는 결정론적으로 생성한다.

```text
canonical(task_id, turn_index, tool_name, arguments)
→ SHA-256
→ 앞 12자리
→ TC-{HASH}
```

현재 시각, UUID, random을 사용하지 않는다.

`SemanticResolution.tool_trace_refs`는 현재 계약대로 `SE-*` Evidence ID를 유지한다. Tool Call ID로 변경하지 않는다.

## Agent Run 결과

### SemanticAgentRunStatus

최소 상태:

```text
completed
budget_exhausted
tool_error
provider_error
invalid_action
verification_rejected
```

`completed`는 Verifier 실행까지 정상 종료됐다는 뜻이며, 반드시 `accepted`일 필요는 없다.

### SemanticAgentRunResult

최소 필드:

```text
task_id
status
resolution
verification_result
tool_results
tool_call_records
turn_count
tool_call_count
distinct_tools_used
files_read
source_lines_returned
messages
```

정책:

- budget/provider 오류 시 resolution이 없을 수 있음
- Resolution이 존재하면 가능한 경우 VerificationResult도 존재
- exception 원문, 절대 경로, Secret을 messages에 복사하지 않음

## 실행 함수

권장 인터페이스:

```python
def run_semantic_agent(
    *,
    task: SemanticTask,
    tool_context: SemanticToolExecutionContext,
    decision_provider: AgentDecisionProvider,
    phase1_evidence: EvidenceModel,
) -> SemanticAgentRunResult:
    ...
```

## State Machine 전이

### 초기화

- Task와 Tool Context의 component, target field, allowlist 일치 확인
- 불일치 시 Provider나 Tool을 호출하지 않고 종료

### Decision Turn

```text
budget 사전 확인
→ Decision Context 생성
→ provider.decide(context)
→ Action schema 확인
→ Tool Call 또는 Resolution 처리
```

`turn_count`는 Provider에게 Decision을 요청할 때 증가한다.

### ToolCallAction 처리

1. Task allowlist 검사
2. distinct Tool 수 검사
3. Tool Call 수 검사
4. Tool Registry 실행
5. Tool Result 기록
6. Tool Call Record 생성
7. usage 누적
8. 누적 Budget 검사
9. 다음 Turn 또는 종료

### ResolutionAction 처리

1. Resolution의 Task ID 기본 일치 확인
2. 기존 Verifier 호출
3. VerificationResult 기록
4. RunStatus 결정
5. 즉시 종료

## 누적 Budget

Task의 기존 `SemanticTaskBudget`을 사용한다.

- `max_agent_turns`
- `max_tool_calls`
- `max_distinct_tools`
- `max_files_read`
- `max_source_lines`
- `max_schema_retries`

이번 단계에서 schema retry는 구현하지 않는다.

### 사전 검사

- 이미 max tool calls 도달
- 새 Tool 사용 시 max distinct tools 초과
- max agent turns 도달

명확한 초과는 실행 전에 차단한다.

### 사후 검사

- 누적 files read 초과
- 누적 source lines 초과

사후 초과 시:

- 해당 Tool Result와 audit record는 보존
- Provider를 재호출하지 않음
- `budget_exhausted`로 종료
- Candidate 생성 금지

Synthetic `SemanticResolution(status=budget_exhausted)`을 만들고 기존 Verifier passthrough 경로를 사용하는 방식을 권장한다.

## Tool 상태 처리

계속 가능:

```text
ok
no_match
not_found
unsupported
```

즉시 종료:

```text
blocked
invalid_input
→ invalid_action

error
→ tool_error
```

Task allowlist에 없는 Tool은 Registry 실행 전에 `invalid_action`으로 종료한다.

## Fake Decision Provider

`ScriptedFakeDecisionProvider(actions: list[AgentAction])`를 구현한다.

- 등록 Action을 순서대로 반환
- Action 소진 후 추가 요청은 provider error
- 같은 Action script는 같은 결과
- Fake Provider는 Tool을 직접 실행하지 않음

테스트 helper로 다음 시나리오를 둘 수 있다.

```text
single_tool_then_resolve
multi_tool_then_resolve
immediate_resolution
ambiguous_resolution
insufficient_evidence
hallucinated_candidate
unknown_evidence_reference
unauthorized_tool
provider_error
tool_error
budget_exhausted
```

## Decision Context 정규화

Provider에는 다음만 전달한다.

```text
evidence:
  evidence_id
  tool_name
  path
  start_line
  end_line
  excerpt

observations:
  tool_name
  kind
  structured fields

remaining_budget:
  agent_turns
  tool_calls
  distinct_tools
  files
  source_lines
```

Tool의 내부 error message, 절대 경로, exception, 중복 excerpt는 제외한다.

## Verifier 연결

`ResolutionAction` 반환 시 반드시 기존 `verify_semantic_resolution()`을 호출한다.

권장 RunStatus 매핑:

```text
accepted              → completed
ambiguous             → completed
insufficient_evidence → completed
budget_exhausted      → budget_exhausted
tool_error            → tool_error
rejected              → verification_rejected
```

Verifier를 우회하는 성공 경로를 만들지 않는다.

## 테스트 우선 구현

최소 테스트:

### Action 및 Context

1. ToolCallAction 정상 생성
2. ResolutionAction 정상 생성
3. malformed Action 거부
4. 여러 Tool Call 구조 거부
5. Context에 절대 경로 없음
6. available tools와 Task allowlist 일치
7. remaining budget 계산
8. 동일 State에서 동일 Context

### Fake Provider

9. Action 순차 반환
10. immediate resolution
11. Action 소진 시 provider error
12. Fake Provider가 Tool을 직접 실행하지 않음

### 정상 실행

13. 단일 Tool 후 resolved
14. 여러 Tool 후 resolved
15. immediate insufficient_evidence
16. immediate ambiguous
17. Tool Result가 다음 Context에 반영
18. Verifier accepted 연결
19. Verifier ambiguous 연결
20. Verifier rejected 연결

### Allowlist 및 Budget

21. unauthorized Tool을 Registry 전에 차단
22. max agent turns
23. max tool calls
24. max distinct tools
25. max files read 사후 초과
26. max source lines 사후 초과
27. 초과 후 Provider 재호출 없음
28. synthetic budget resolution

### Tool 상태 및 오류

29. no_match 후 계속
30. not_found 후 계속
31. unsupported 후 계속
32. blocked → invalid_action
33. invalid_input → invalid_action
34. error → tool_error
35. Provider exception
36. malformed Action
37. Action script 소진

### Audit 및 재현성

38. deterministic Tool Call ID
39. arguments 순서가 달라도 같은 ID
40. Turn이 다르면 다른 ID
41. Secret-like argument 기록 차단 또는 redaction
42. 동일 Fake script에서 동일 RunResult

### End-to-end

43. shell script Task → Tool → grounded Resolution → accepted
44. hallucinated Candidate → verification_rejected
45. invalid Evidence → verification_rejected
46. 반복 Tool 호출 → budget_exhausted
47. 기존 전체 테스트 통과

## 비목표

구현하지 않는다.

- 실제 Qwen3-Coder 호출
- HTTP Client
- Native Tool Calling
- JSON Schema Guided Decoding
- Prompt
- Schema retry
- Pipeline 연동
- 최종 Runtime Command reconciliation
- Dockerfile/Kubernetes 생성
- 외부 Tool Adapter

## 테스트

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=src \
.venv/bin/python3 -m unittest discover -s tests -v

git diff --check
git status --short
```

## 완료 보고

1. 변경 파일
2. Action 계약
3. AgentDecisionProvider Protocol
4. State와 Decision Context 차이
5. Tool Call Record와 ID
6. State Machine 전이
7. Budget 처리
8. Tool 상태별 처리
9. Fake Provider 시나리오
10. Verifier 연결
11. ambiguous 정책 유지 방식
12. 테스트 결과
13. 기존 계층 영향
14. 다음 Provider가 구현할 인터페이스
15. 의도적으로 제외한 항목

범위를 넘어 실제 LLM, Pipeline 또는 YAML 산출물 연동을 구현했다면 제거한 뒤 완료하라.
