# TASK-06 — Qwen3-Coder용 OpenAI-compatible Decision Provider

현재 완성된 Bounded Semantic Agent State Machine에 실제 20B~30B급 On-Premise LLM을 연결하기 위한 Provider Adapter를 구현하라.

기본 대상은 vLLM 또는 동등한 OpenAI-compatible endpoint에서 서비스되는 Qwen3-Coder 계열 모델이다.

## 핵심 원칙

Provider는 다음 Action 하나를 구조화해 반환하는 역할만 담당한다.

```text
ToolCallAction
또는
ResolutionAction
```

Provider가 담당하지 않는 것:

- Tool 실행
- Tool allowlist 판정
- Budget 관리
- Repository 파일 접근
- Evidence 생성
- Candidate 검증
- Pipeline 변경
- 최종 Candidate 채택

기존 `AgentDecisionProvider` Protocol과 State Machine을 변경하지 않는다.

## 작업 전 확인

- `src/preanalyzer/models/semantic_agent.py`
- `src/preanalyzer/semantic/agent.py`
- `src/preanalyzer/semantic/fake_provider.py`
- `src/preanalyzer/semantic/tools/`
- `src/preanalyzer/semantic/verifier.py`
- Provider 관련 설계 문서
- 현재 `pyproject.toml`

## 환경 정보 정책

실제 값은 코드 또는 Git에 저장하지 않는다.

예상 환경변수:

```text
SEMANTIC_LLM_BASE_URL
SEMANTIC_LLM_MODEL
SEMANTIC_LLM_API_KEY
SEMANTIC_LLM_TIMEOUT_SECONDS
```

API Key는 optional일 수 있지만 설정 계약은 환경변수 참조 방식으로 유지한다.

로그, exception, 결과 산출물에 API Key를 포함하지 않는다.

## Provider 설정 모델

최소 모델:

```text
OpenAICompatibleProviderConfig
  base_url
  model
  api_key_env
  timeout_seconds
  temperature
  max_output_tokens
  capability_profile
```

### ModelCapabilityProfile

최소 필드:

```text
native_tool_calling
structured_output_mode
supports_guided_decoding
supports_parallel_tool_calls
context_window_tokens
recommended_max_agent_turns
reasoning_mode
```

`structured_output_mode`:

```text
json_schema
json_object
prompted_json
```

`parallel_tool_calls`는 모델 지원 여부와 무관하게 기본 false다.

## SDK 선택

다음을 비교하고 더 단순한 방식을 선택한다.

1. 공식 OpenAI Python Client의 OpenAI-compatible endpoint 사용
2. PydanticAI를 얇은 Adapter로 사용

선택 기준:

- 기존 State Machine을 침범하지 않는가
- 구조화 Action 파싱이 단순한가
- vLLM 호환성이 좋은가
- dependency와 추상화가 과도하지 않은가
- test double 작성이 쉬운가

PydanticAI가 Agent Loop를 소유하게 해서는 안 된다.

선택 이유를 문서 또는 완료 보고에 기록한다.

## Provider 인터페이스

기존 Protocol을 구현한다.

```python
class OpenAICompatibleDecisionProvider:
    def decide(
        self,
        context: SemanticDecisionContext,
    ) -> AgentAction:
        ...
```

State Machine은 Provider가 어떤 SDK를 사용하는지 알지 못해야 한다.

## 모델 입력

모델에 다음만 전달한다.

- Task identity
- Task reason
- Known Candidates
- 현재까지 수집된 redacted Evidence
- 구조화된 Observation
- 사용 가능한 Tool 이름과 Tool별 입력 schema
- 남은 Budget
- Action 출력 schema

포함 금지:

- Repository 절대 경로
- Repository 전체
- 전체 대화 이력
- Verifier 구현
- Secret 값
- 환경변수 실제 값
- 내부 Python repr

## 시스템 지시 핵심

Prompt에는 다음 규칙을 간결하게 포함한다.

1. 한 번에 하나의 Action만 반환
2. 허용된 Tool만 사용
3. Tool을 호출하거나 Resolution을 반환
4. 근거 없는 Candidate 생성 금지
5. Candidate 값은 수집된 Evidence에서 직접 확인 가능해야 함
6. 근거가 없으면 `insufficient_evidence`
7. 여러 후보 중 결정할 수 없으면 `ambiguous`
8. confidence는 `low` 또는 `medium`
9. `high` 금지
10. 최종 Dockerfile 또는 Kubernetes YAML 생성 금지
11. 긴 reasoning 출력 금지
12. Action schema 외 텍스트 출력 금지

20B~30B 모델을 고려해 Prompt를 짧고 반복 없이 유지한다.

## 실행 모드

### Native Tool Calling

Capability가 true인 경우 Tool schema를 제공할 수 있다.

단:

- 한 응답의 Tool Call은 하나만 허용
- parallel Tool Calls 반환 시 Provider error 또는 invalid action
- Provider는 Tool을 실행하지 않고 `ToolCallAction`으로 변환

### Structured Action JSON

Native Tool Calling이 불안정하거나 비활성화된 경우 모델이 다음 Action JSON을 반환하게 한다.

```json
{
  "action_type": "tool_call",
  "tool_name": "read_source_range",
  "arguments": {
    "path": "scripts/start.sh",
    "start_line": 1,
    "end_line": 20
  },
  "reason_code": "inspect_entrypoint"
}
```

또는:

```json
{
  "action_type": "resolution",
  "resolution": {
    "...": "SemanticResolution schema"
  }
}
```

### Structured Output 우선순위

```text
json_schema
→ json_object
→ prompted_json
```

Guided Decoding은 endpoint가 실제 지원하는 경우에만 사용한다.

## Schema Validation과 1회 Retry

- 첫 출력은 기존 AgentAction schema로 검증
- validation 실패 시 최대 1회 보정 요청
- 보정 Prompt에는 validation error의 안전한 요약만 포함
- 원 응답 전체 또는 Secret을 그대로 반복하지 않음
- 두 번째 실패 시 Provider error
- State Machine이 아닌 Provider 내부에서 schema retry를 관리
- Tool 실행 retry는 하지 않음

## Qwen3-Coder / Reasoning 처리

확인해야 할 항목:

- reasoning parser 사용 여부
- thinking 내용이 어떤 응답 필드로 반환되는지
- Tool Call과 thinking 동시 반환 여부
- structured output과 reasoning parser 충돌 여부

정책:

- hidden reasoning 또는 thinking content를 AgentAction에 저장하지 않는다.
- reasoning field를 로그나 산출물에 저장하지 않는다.
- 최종 structured Action만 파싱한다.
- thinking 때문에 JSON 앞뒤에 텍스트가 붙는 경우 모델 설정 또는 parser 경로로 해결하며 무제한 문자열 복구 로직을 만들지 않는다.

## Timeout과 오류

구조화할 오류:

```text
provider_timeout
provider_connection_error
provider_http_error
provider_schema_error
provider_parallel_tool_call
provider_empty_response
provider_unsupported_mode
```

실제 endpoint 응답 본문 전체를 오류 메시지에 포함하지 않는다.

API Key, Base URL credential, 내부 절대 경로를 노출하지 않는다.

## Audit Metadata

최소:

```text
provider_type
model
structured_output_mode
native_tool_calling
schema_retry_count
request_context_hash
```

다음은 기록하지 않는다.

- API Key
- 전체 Prompt
- 전체 응답
- reasoning
- Repository 원문

필요하면 별도 `ProviderDecisionMetadata` 모델을 추가하되 기존 Protocol을 과도하게 변경하지 않는다.

## 테스트

실제 네트워크가 없어도 단위 테스트가 통과해야 한다.

Mock client 또는 fake transport를 사용한다.

최소 테스트:

1. Native Tool Call → ToolCallAction
2. Structured JSON Tool Call → ToolCallAction
3. Resolution JSON → ResolutionAction
4. JSON Schema mode
5. JSON Object mode
6. Prompted JSON fallback
7. malformed JSON
8. schema 실패 후 1회 보정 성공
9. 1회 보정도 실패
10. empty response
11. timeout
12. connection error
13. HTTP error
14. 여러 Tool Call 반환 거부
15. unknown Tool 이름을 Action으로 반환하되 State Machine에서 차단되는 계약 확인
16. API Key 로그 미노출
17. reasoning field 무시
18. Repository 절대 경로가 요청 payload에 없음
19. 전체 대화 이력 없음
20. 같은 Context에서 deterministic request payload
21. mock Provider로 기존 State Machine 전체 흐름
22. 기존 전체 테스트 통과

## 실제 Qwen3-Coder Smoke Test

단위 테스트와 분리한다.

예:

```text
integration
onprem
```

환경변수가 없으면 skip한다.

Smoke Test 범위:

1. Endpoint 연결
2. Immediate `insufficient_evidence` Resolution 생성
3. 허용된 Tool 하나 선택
4. Tool 실행 후 grounded Resolution 생성
5. schema retry 발생 여부 기록

Smoke Test는 성공률 평가가 아니라 통신 및 계약 검증이다.

## 비목표

- Pipeline 연동
- 실제 모델 평가 통계
- Prompt 최적화
- Tool 확장
- Runtime Command reconciliation
- Dockerfile/Kubernetes 생성
- Draft/Kantra/Move2Kube 연동

## 테스트 및 완료 보고

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=src \
.venv/bin/python3 -m unittest discover -s tests -v

git diff --check
git status --short
```

보고:

1. 선택 SDK와 이유
2. Provider 설정 계약
3. Capability Profile
4. Prompt에 포함된 핵심 규칙
5. 실행 모드 분기
6. Schema retry
7. Qwen reasoning 처리
8. 오류 처리
9. Audit metadata
10. 단위 테스트
11. Smoke Test 실행 방법
12. 다음 Pipeline 연동 계약
13. 제외 항목
