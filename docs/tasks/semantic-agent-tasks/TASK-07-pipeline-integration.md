# TASK-07 — Semantic Agent의 기존 Pipeline 선택적 연동

현재 구현된 다음 계층을 기존 Phase 1 Pipeline에 선택적으로 연결하라.

```text
EvidenceModel
→ RuleInferenceSet
→ RuntimeCommandAnalysis
→ SemanticTaskBuildResult
→ Bounded Semantic Agent
→ VerificationResult
→ Semantic Analysis Audit Output
```

## 핵심 원칙

- 기존 Phase 1 기본 동작을 깨지 않는다.
- Semantic 기능은 명시적으로 활성화된 경우에만 실행한다.
- 비활성화 시 기존 00~03 결과가 byte-level 또는 의미상 동일해야 한다.
- Semantic 실패가 전체 Pipeline 실패로 이어지지 않는다.
- Verifier를 통과한 Candidate도 기존 RuleInference를 자동으로 덮어쓰지 않는다.
- 아직 최종 Runtime Command reconciliation을 구현하지 않는다.

## 작업 전 확인

- `src/preanalyzer/pipeline.py`
- 현재 CLI/config 구조
- 모든 Semantic 모델과 실행 함수
- 기존 acceptance tests
- Phase 1 YAML writer 방식

## 설정

최소 실행 모드:

```text
disabled
fake
openai_compatible
```

초기 기본값:

```text
disabled
```

Provider 객체는 dependency injection을 우선한다.

테스트에서 Fake Provider를 쉽게 주입할 수 있어야 한다.

실제 endpoint 설정을 Pipeline 전역에 하드코딩하지 않는다.

## 삽입 위치

현재 흐름:

```text
snapshot
→ inventory
→ parsed artifacts
→ evidence
→ rules
→ 00~03 YAML
```

권장 삽입:

```text
rules = infer(evidence)
runtime_analysis = analyze_runtime_commands(evidence, rules)
task_build_result = build_runtime_command_semantic_tasks(runtime_analysis)

if semantic enabled:
    run tasks
else:
    record disabled status
```

기존 00~03 쓰기 순서와 내용을 변경하지 않는다.

## 산출물

초기에는 단일 파일을 사용한다.

```text
04-semantic-analysis.yaml
```

최소 내용:

```text
schema_version
enabled
provider
model
runtime_command_analysis
task_build_result
runs
summary
```

### Run Audit

Task별 최소 기록:

```text
task_id
component_id
target_field
run_status
turn_count
tool_call_count
distinct_tools_used
files_read
source_lines_returned
tool_call_records
resolution
verification_result
```

### 기록 금지

- Repository 절대 경로
- API Key
- Secret 실제 값
- 전체 Prompt
- 전체 모델 응답
- reasoning/thinking
- exception traceback
- Tool이 반환하지 않은 원문 파일 내용

## 실패 Fallback

다음 실패가 발생해도 기존 Pipeline은 계속된다.

- Context build 실패
- Provider 오류
- Tool 오류
- Budget 초과
- Verification rejected
- insufficient evidence
- ambiguous

모든 실패는 `04-semantic-analysis.yaml` audit에 남긴다.

## 실행 정책

- resolved command만 있고 gap이 없으면 Task 없음
- Task가 없으면 Agent 호출 없음
- excluded/not actionable gap은 Agent 호출 없음
- Task별 실행은 독립적
- 하나의 Task 실패가 다른 Task 실행을 막지 않음
- Task 순서는 안정적으로 정렬
- 동일 입력, Fake Provider에서는 동일 산출물

## 테스트

최소 acceptance cases:

1. Semantic disabled → 기존 결과 동일
2. direct runtime command → Agent 미실행
3. shell entrypoint → Task와 Fake Agent 실행
4. valid Candidate → Verification accepted
5. hallucinated Candidate → rejected audit
6. insufficient evidence → Pipeline 계속
7. ambiguous → Pipeline 계속
8. Tool error → Pipeline 계속
9. Provider error → Pipeline 계속
10. Budget exhausted → Pipeline 계속
11. 여러 Task 중 하나 실패, 나머지 실행
12. `04-semantic-analysis.yaml` Secret 미포함
13. 절대 경로 미포함
14. API Key 미포함
15. 동일 Fake 실행 결과 재현
16. 기존 전체 테스트 통과

## 비목표

- 기존 RuleInference 자동 수정
- Runtime Command 최종 reconciliation
- Application Topology
- Kubernetes Intent
- Dockerfile/Kubernetes 렌더링
- Prompt 최적화
- 평가 통계
- 외부 생성 Tool

## 완료 보고

1. Pipeline 삽입 위치
2. 설정과 Provider 주입 방식
3. Agent 실행 조건
4. `04-semantic-analysis.yaml` 구조
5. 실패 Fallback
6. 기존 출력 회귀
7. 테스트 결과
8. 실제 Qwen 실행 방법
9. 제외 항목
