# TASK-09 — 실제 평가 기반 Prompt 및 Tool 계약 최적화

최신 On-Premise Evaluation Report를 기준으로 `resolve_runtime_command` Agent의 Prompt, Tool 설명, Decision Context를 개선하라.

## 원칙

개선 우선순위:

1. Hallucination 감소
2. 잘못된 Evidence Reference 감소
3. 올바른 insufficient evidence 판단
4. Tool 선택 정확도
5. Tool 호출 수 감소
6. Schema 성공률
7. Context token 감소
8. Latency 감소

다음 방식부터 사용하지 않는다.

- Agent Turn 증가
- Tool Call Budget 증가
- Repository Context 확대
- 긴 Few-shot 예시 추가
- Verifier 완화
- 모델별 완전히 별도 Prompt

## 작업 방식

각 변경을 하나의 실험으로 취급한다.

```text
baseline
→ single change
→ evaluation
→ metric comparison
→ keep or revert
```

효과가 확인되지 않은 변경은 유지하지 않는다.

## 분석할 실패 유형

- 잘못된 Tool 선택
- 반복 Tool 호출
- Evidence를 읽고도 잘못된 Candidate 생성
- Evidence ID 누락
- Grounding 불충분
- ambiguous 대신 억지 resolved
- insufficient 대신 억지 resolved
- malformed Action
- schema retry 반복
- Tool 설명 오해
- Context 과다
- Observation 구조 불명확

## 개선 가능 영역

### Prompt

- 역할 설명 축소
- Action 선택 규칙 명확화
- 종료 조건 명확화
- insufficient/ambiguous 판단 규칙
- Candidate grounding 규칙
- Tool 사용 우선순위

### Tool Description

- 입력 조건
- 반환하는 증거
- 사용하지 말아야 할 상황
- no_match와 unsupported 의미
- 다른 Tool과의 역할 차이

### Decision Context

- 중복 Evidence 제거
- Observation 필드 정리
- Known Candidate 순서 안정화
- 남은 Budget 표현 간소화
- 불필요한 hash/metadata 제외

### Domain Tool

저수준 Tool 조립이 반복 실패한다면 기존 Tool을 무제한 추가하지 말고, 작은 도메인 Tool 도입을 평가한다.

예:

```text
trace_runtime_entrypoint
```

단, 실제 평가에서 필요성이 확인된 경우만 추가한다.

## 테스트 및 평가

각 변경 전후로 같은 Fixture와 반복 횟수를 사용한다.

비교 지표:

- 정확도
- Hallucination
- Evidence 정확도
- Tool calls
- Agent turns
- Token
- Latency
- Schema retry
- 일관성

결과를 Markdown과 JSON으로 남긴다.

## 비목표

- 새 Semantic Task Type
- Pipeline 구조 변경
- Verifier 완화
- 외부 Tool Adapter
- Runtime reconciliation
- Kubernetes 생성

## 완료 보고

1. 실패 유형
2. 시도한 변경
3. 변경 전후 수치
4. 유지한 변경
5. 되돌린 변경
6. 남은 한계
7. 다음 Task Type 확장 준비 여부
