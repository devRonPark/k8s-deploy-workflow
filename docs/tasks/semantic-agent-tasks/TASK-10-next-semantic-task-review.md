# TASK-10 — 다음 Semantic Task Type 확장 여부 검토

`resolve_runtime_command` MVP와 실제 20B~30B 모델 평가 결과를 리뷰하라.

이번 단계에서는 새 기능을 구현하지 않는다.

## 검토 질문

1. Runtime command 해결률은 목표에 도달했는가
2. Hallucination 비율은 허용 가능한가
3. Evidence 정확도는 충분한가
4. 평균 Tool Call 수는 Budget에 적합한가
5. 20B와 30B 모델의 차이는 무엇인가
6. Prompt 문제는 무엇인가
7. Tool 문제는 무엇인가
8. 결정론적 Resolver 부족은 무엇인가
9. unresolved로 유지해야 할 문제는 무엇인가
10. 현재 State Machine과 Verifier를 재사용할 수 있는가

## 다음 후보

```text
resolve_runtime_port
resolve_component_role
resolve_dependency_edge
```

각 후보 평가 항목:

- 사용자 가치
- 실제 발생 빈도
- 결정론적으로 해결되지 않는 비율
- 필요한 Tool
- 20B~30B 모델 난이도
- Grounding 및 검증 가능성
- Hallucination 위험
- 구현 비용
- Fixture 작성 난이도
- 기존 계약 재사용성

## 추천 원칙

- 다음 Task Type은 하나만 추천
- 가장 작은 범위 우선
- 검증 가능한 값 우선
- 새 범용 Agent 프레임워크 금지
- 기존 MVP가 통과하지 못했다면 확장 대신 재작업 추천

## 산출물

권장:

```text
docs/plans/next-semantic-task-review.md
```

포함:

1. MVP 통과/재작업 판단
2. 근거 지표
3. 유지할 구조
4. 재설계할 구조
5. 다음 Task 추천
6. 작은 단계 구현 계획
7. 명시적 비목표

코드는 수정하지 않는다.
