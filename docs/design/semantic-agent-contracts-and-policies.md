# Semantic Agent 계약과 정책

## 1. 문서 목적

이 문서는 향후 Pydantic 모델로 옮길 수 있을 정도로 Semantic Agent의 데이터 계약, 실행 정책, 검증 정책을 고정한다. 현재 Repository에는 이 모델이 구현되어 있지 않다. 아래 스키마는 설계 계약이며 구현 전에는 `확인 필요` 또는 `향후 검증` 항목을 그대로 유지한다.

현재 구현과의 경계는 다음과 같다.

- 현재 `EvidenceFact`는 `evidence_id`, `fact_type`, `artifact_ref`, `source`, `classification`, `value`를 가진다.
- 현재 Rule 후보는 `component_id` 또는 source/target 필드, `source`, `confidence`, `evidence_refs`, `classification: rule_inference`를 가진다.
- Semantic Agent 계약은 여기에 `task_id`, `target_field`, tool trace, verifier result, model capability profile을 추가한다.

## 2. SemanticTask 최소 스키마

```yaml
SemanticTask:
  task_id: "ST-0001"
  task_type: "resolve_runtime_command"
  component_id: "backend"
  component_root: "backend"
  target_field: "runtime.command"
  reason:
    code: "indirect_entrypoint"
    message: "Dockerfile CMD가 shell script를 가리키지만 실제 실행 명령은 script 내부에 있음"
    evidence_refs: ["F0009"]
  known_candidates:
    - candidate_id: "RC-0001"
      value: '["./entrypoint.sh"]'
      source: "dockerfile_cmd"
      confidence: "high"
      classification: "rule_inference"
      evidence_refs: ["F0009"]
  constraints:
    allowed_task_types:
      - "resolve_runtime_command"
    allowed_target_fields:
      - "runtime.command"
    component_scope_only: true
    read_only: true
    secret_values_allowed: false
  tool_allowlist:
    - "search_code"
    - "read_source_range"
    - "inspect_entrypoint_script"
    - "find_command_target"
  budget:
    max_agent_turns: 4
    max_tool_calls: 4
    max_distinct_tools: 3
    max_files_read: 5
    max_source_lines: 400
    max_schema_retries: 1
    parallel_tool_calls: false
```

`budget` 값은 확정값이 아니라 MVP 초기 제안값이다. 실제 20B~30B 모델 평가 후 조정한다.

## 3. SemanticTaskType

MVP에서 타입은 네 가지를 정의하되, 첫 구현은 하나로 제한한다.

```yaml
SemanticTaskType:
  - resolve_runtime_command
  - resolve_runtime_port
  - resolve_component_role
  - resolve_dependency_edge

FirstImplementationTarget: resolve_runtime_command
```

각 task type은 허용 target field와 tool allowlist를 별도로 가진다.

| Task type | Target field | MVP 상태 |
|---|---|---|
| `resolve_runtime_command` | `runtime.command` | 첫 구현 대상 |
| `resolve_runtime_port` | `runtime.port` | 계약만 정의 |
| `resolve_component_role` | `component.role` | 계약만 정의 |
| `resolve_dependency_edge` | `dependency.edges[]` | 계약만 정의 |

## 4. TaskReason

```yaml
TaskReason:
  code: "indirect_entrypoint"
  message: "사람이 읽는 짧은 설명"
  evidence_refs: ["F0009"]
  conflict_refs: []
  unresolved_field: "runtime.command"
```

초기 reason code 후보:

- `indirect_entrypoint`: Dockerfile `CMD`/`ENTRYPOINT`가 script 또는 package script를 가리킴
- `missing_direct_candidate`: 직접 runtime command 후보가 없음
- `multiple_known_candidates`: 여러 후보가 있고 우선순위를 결정할 근거 부족
- `artifact_conflict`: Dockerfile, Compose, package script 후보가 충돌
- `semantic_role_needed`: component role 해석 필요
- `semantic_dependency_needed`: dependency edge 의미 해석 필요

## 5. KnownCandidate

기존 Rule 후보를 Agent 입력으로 요약한 형태다.

```yaml
KnownCandidate:
  candidate_id: "RC-0001"
  field: "runtime.command"
  value: '["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]'
  source: "dockerfile_cmd"
  confidence: "high"
  classification: "rule_inference"
  evidence_refs: ["F0009"]
  notes: []
```

LLM은 `KnownCandidate.confidence`를 최종 confidence로 재결정하지 않는다. Verifier와 Reconciliation 정책이 최종 채택 여부와 confidence cap을 적용한다.

## 6. EvidenceReference

```yaml
EvidenceReference:
  evidence_id: "F0009"
  artifact_ref: "backend/Dockerfile"
  fact_type: "dockerfile_cmd"
  source: "dockerfile_cmd"
  classification: "observed_fact"
  location:
    path: "backend/Dockerfile"
    start_line: 7
    end_line: 7
  excerpt_hash: "sha256:확인 필요"
```

현재 `EvidenceFact`에는 line location과 excerpt hash가 없다. Semantic Agent MVP에서는 tool result가 location과 snippet을 제공하고, Verifier가 `evidence_id`와 tool trace를 연결한다. Evidence 모델 자체에 location을 넣을지는 `확인 필요`다.

## 7. SemanticAgentState

대화 이력 전체를 누적하지 않고 매 turn마다 구조화된 현재 상태를 만든다.

```yaml
SemanticAgentState:
  task:
    task_id: "ST-0001"
    task_type: "resolve_runtime_command"
    component_id: "backend"
    target_field: "runtime.command"
  current_observations:
    files_seen:
      - "backend/Dockerfile"
      - "backend/entrypoint.sh"
    source_lines_seen: 72
    tool_calls_used: 2
    distinct_tools_used:
      - "read_source_range"
      - "inspect_entrypoint_script"
  known_candidates:
    - candidate_id: "RC-0001"
      value: '["./entrypoint.sh"]'
      source: "dockerfile_cmd"
      confidence: "high"
      classification: "rule_inference"
      evidence_refs: ["F0009"]
  trace:
    - tool_call_id: "TC-0001"
      tool_name: "read_source_range"
      args_summary:
        path: "backend/Dockerfile"
        start_line: 1
        end_line: 80
      result_ref: "TR-0001"
  remaining_budget:
    agent_turns: 2
    tool_calls: 2
    files_read: 3
    source_lines: 328
```

## 8. ToolDefinition과 ToolResult

Tool은 read-only다. 초기 Tool 후보는 네 가지다.

```yaml
ToolDefinition:
  name: "inspect_entrypoint_script"
  description: "Dockerfile CMD/ENTRYPOINT가 가리키는 script에서 실제 exec 명령 후보를 찾는다"
  input_schema:
    type: object
    required: ["component_root", "script_path"]
    properties:
      component_root: {type: string}
      script_path: {type: string}
  output_schema:
    type: object
    required: ["status", "evidence_refs", "candidates"]
  read_only: true
  may_read_files: true
  may_execute_code: false
  may_use_network: false
```

```yaml
ToolResult:
  tool_call_id: "TC-0002"
  tool_name: "inspect_entrypoint_script"
  status: "ok"
  files_read:
    - "backend/entrypoint.sh"
  source_ranges:
    - path: "backend/entrypoint.sh"
      start_line: 10
      end_line: 14
      excerpt: "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
      contains_secret_value: false
  evidence_refs:
    - evidence_id: "SE-0001"
      source: "tool:inspect_entrypoint_script"
      path: "backend/entrypoint.sh"
      start_line: 10
      end_line: 14
  candidates:
    - field: "runtime.command"
      value: "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
      support: "line_10_exec"
  warnings: []
```

`SE-*`처럼 tool이 만든 source evidence id를 기존 `F*` EvidenceFact와 같은 namespace로 둘지, 별도 namespace로 둘지는 `확인 필요`다. Verifier는 두 경우 모두 실제 source range 존재를 확인해야 한다.

## 9. SemanticCandidate

```yaml
SemanticCandidate:
  candidate_id: "SC-0001"
  task_id: "ST-0001"
  component_id: "backend"
  field: "runtime.command"
  value:
    command: "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
    command_form: "shell"
  source: "semantic_agent"
  confidence: "medium"
  classification: "llm_interpretation"
  evidence_refs:
    - "F0009"
    - "SE-0001"
  reasoning_summary: "Dockerfile CMD가 entrypoint.sh를 실행하고, script 마지막 exec가 uvicorn 서버를 시작함"
  tool_trace_refs:
    - "TC-0001"
    - "TC-0002"
  limitations:
    - "PORT 기본값은 script에서 8000으로 보이나 환경변수 override 가능"
```

정책:

- LLM 기반 candidate의 최대 confidence는 `medium`이다.
- `evidence_refs`가 비어 있으면 rejected다.
- `field`가 task의 `target_field`와 다르면 rejected다.
- Secret 값이 포함되면 rejected다.

## 10. SemanticResolution

Agent의 최종 응답은 candidate 하나 또는 unresolved 사유다.

```yaml
SemanticResolution:
  task_id: "ST-0001"
  status: "candidate_found"
  candidates:
    - candidate_id: "SC-0001"
  unresolved_reason: null
  budget:
    turns_used: 3
    tool_calls_used: 2
    files_read: 2
    source_lines_read: 72
  tool_trace_refs:
    - "TC-0001"
    - "TC-0002"
  schema_retry_count: 0
```

`status` 후보:

- `candidate_found`
- `ambiguous`
- `insufficient_evidence`
- `budget_exhausted`
- `tool_error`
- `schema_error`

## 11. VerificationResult

```yaml
VerificationResult:
  task_id: "ST-0001"
  candidate_id: "SC-0001"
  status: "accepted"
  reasons:
    - code: "schema_valid"
    - code: "evidence_refs_exist"
    - code: "target_field_allowed"
    - code: "secret_absent"
    - code: "confidence_capped_to_medium"
  rejected_reasons: []
  accepted_candidate:
    candidate_id: "SC-0001"
    confidence: "medium"
  audit:
    model_id: "확인 필요"
    provider: "openai_compatible"
    tool_calls:
      - "TC-0001"
      - "TC-0002"
    prompt_template_version: "확인 필요"
```

검증 결과 상태:

```text
accepted
ambiguous
insufficient_evidence
rejected
budget_exhausted
tool_error
```

## 12. ModelCapabilityProfile

20B~30B급 On-Premise LLM과 vLLM 등 OpenAI-compatible endpoint를 전제로 한다. 기능 지원은 모델과 서빙 설정에 따라 다르므로 capability profile로 분리한다.

```yaml
ModelCapabilityProfile:
  provider_kind: "openai_compatible"
  model_id: "확인 필요"
  served_by: "vllm"
  native_tool_calling: "unknown"
  json_schema_structured_output: "unknown"
  guided_decoding: "unknown"
  max_context_tokens: "확인 필요"
  reliable_multi_turn_tool_use: "향후 검증"
  code_language_strengths:
    python: "향후 검증"
    javascript: "향후 검증"
    java: "향후 검증"
    shell: "향후 검증"
  policy:
    use_native_tool_calling_when_available: true
    fallback_to_json_tool_envelope: true
    max_schema_retries: 1
```

## 13. Tool allowlist

MVP `resolve_runtime_command` allowlist:

```yaml
resolve_runtime_command:
  - search_code
  - read_source_range
  - inspect_entrypoint_script
  - find_command_target
```

보류:

- 범용 LSP 통합
- 전체 call graph
- 복잡한 data flow
- shell 실행
- network tool
- 파일 수정 tool
- 자동 dependency 설치

## 14. Agent budget

MVP 초기값:

```yaml
max_agent_turns: 4
max_tool_calls: 4
max_distinct_tools: 3
max_files_read: 5
max_source_lines: 400
max_schema_retries: 1
parallel_tool_calls: false
```

정책:

- budget 초과 시 `budget_exhausted`로 종료하고 기존 pipeline은 unresolved로 계속 진행한다.
- parallel tool calling은 기본적으로 사용하지 않는다.
- schema 검증 실패 시 최대 1회만 보정한다.
- 긴 대화 이력 누적 대신 매 turn 구조화 상태를 재구성한다.

## 15. Read-only 정책

허용:

- 코드 문자열 검색
- 관련 파일 목록 탐색
- 코드 범위 조회
- 심볼 정의/참조 조회
- entrypoint script 분석
- 외부 생성기 dry-run 결과 조회. 단 MVP에서는 보류

금지:

- 파일 생성, 수정, 삭제
- shell command 실행
- network 접근
- package install
- Docker build
- Kubernetes manifest 직접 생성
- Secret 값 읽기 또는 출력

## 16. Secret 차단 정책

- Secret 실제 값은 tool result, LLM input, SemanticCandidate, audit log에 포함하지 않는다.
- 이름 기반 패턴은 현재 구현의 `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, `CREDENTIAL`, `PRIVATE`를 출발점으로 한다.
- tool이 source range를 반환할 때 Secret 값이 포함될 가능성이 있으면 redaction 후 `contains_secret_value: true`를 기록한다.
- Secret 값이 candidate value나 reasoning summary에 포함되면 Verifier는 `rejected`로 판정한다.

## 17. Confidence 정책

| 출처 | 최대 confidence | 비고 |
|---|---|---|
| 명시적 결정론적 evidence | high | 예: Dockerfile `CMD`, `EXPOSE` |
| 규칙 기반 추론 | high 또는 medium 또는 low | 규칙 테이블이 결정 |
| LLM 기반 SemanticCandidate | medium | Verifier가 cap 적용 |
| framework convention | low | 직접 근거 없으면 high 금지 |
| unresolved | none | value 확정 금지 |

LLM은 기존 high-confidence 결정론적 후보를 임의로 덮어쓸 수 없다. 충돌은 Reconciliation 또는 user decision으로 라우팅한다.

## 18. 결과 채택 및 거부 규칙

Accepted 조건:

- schema valid
- task id 일치
- component id 일치
- target field 일치
- evidence reference 존재
- tool trace와 evidence 연결
- Secret 없음
- confidence cap 준수
- 기존 high-confidence 결정론 후보와 충돌하지 않거나, 충돌이 명시적으로 ambiguous 처리됨

Rejected 조건:

- 존재하지 않는 명령 생성
- 존재하지 않는 file path 또는 line range 인용
- task 범위 밖 field 반환
- Secret 값 포함
- allowlist 밖 tool 결과 사용
- tool trace 없이 최종 evidence만 주장
- JSON schema invalid 후 1회 보정에도 실패

## 19. Structured Output fallback

Native JSON Schema structured output이 지원되면 우선 사용한다. 지원되지 않으면 JSON envelope를 강제한다.

```yaml
fallback_output_contract:
  response_format: "json_object"
  required_top_level_keys:
    - "resolution"
    - "candidates"
    - "tool_request"
  repair_attempts: 1
```

1회 보정 후에도 schema가 깨지면 task는 `schema_error` 또는 `insufficient_evidence`로 종료한다. pipeline은 실패하지 않는다.

## 20. Native Tool Calling 미지원 모델 처리

Native Tool Calling이 없으면 tool call을 JSON tool envelope로 표현한다.

```yaml
ToolCallEnvelope:
  action: "call_tool"
  tool_name: "read_source_range"
  arguments:
    path: "backend/entrypoint.sh"
    start_line: 1
    end_line: 120
```

Agent runtime은 envelope를 검증한 뒤 allowlist와 budget을 확인하고 실제 tool을 호출한다. LLM이 임의 텍스트로 tool을 호출했다고 주장해도 runtime trace에 없으면 무효다.

## 21. Tool trace와 audit 정보

감사 정보는 재현성과 보안 검토를 위해 남긴다.

```yaml
SemanticAudit:
  task_id: "ST-0001"
  model_capability_profile_ref: "MCP-0001"
  prompt_template_version: "확인 필요"
  agent_budget:
    max_agent_turns: 4
    max_tool_calls: 4
  tool_trace:
    - tool_call_id: "TC-0001"
      tool_name: "read_source_range"
      args_hash: "sha256:확인 필요"
      result_hash: "sha256:확인 필요"
      files_read:
        - "backend/Dockerfile"
      redactions: []
  verification:
    status: "accepted"
    reasons:
      - "schema_valid"
      - "secret_absent"
```

Prompt 전문 저장 여부는 보안 정책상 `확인 필요`다. 최소한 template version, model id, tool trace, result hash는 남긴다.
