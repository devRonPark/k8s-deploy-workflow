# TASK-08 — 20B~30B On-Premise LLM Evaluation Harness

현재 구현된 `resolve_runtime_command` Semantic Agent가 실제 대상 모델에서 작동하는지 평가하는 Harness를 구현하라.

기능을 확장하지 말고 현재 설계의 성능과 실패 패턴을 측정한다.

## 평가 대상

설정으로 공급한다.

- Qwen3-Coder 20B급 또는 유사 모델 최소 1종
- Qwen3-Coder 30B급 또는 유사 모델 최소 1종
- Scripted Fake Provider baseline

특정 모델 이름이나 endpoint를 코드에 하드코딩하지 않는다.

## Fixture

최소:

```text
dockerfile-direct-cmd
dockerfile-shell-entrypoint
shell-to-package-script
node-multiple-scripts
python-module-entrypoint
compound-shell-command
ambiguous-runtime-command
insufficient-runtime-evidence
hallucinated-command-rejection
invalid-evidence-reference
budget-exhausted
```

각 Fixture는 기대 결과를 기계 판독 가능한 파일로 가진다.

예:

```text
expected_status
expected_command
allowed_commands
expected_evidence_paths
expected_tool_names
max_tool_calls
```

## 측정 지표

1. Task 생성 정확도
2. Runtime command 해결률
3. 정확한 command 선택률
4. Evidence reference 정확도
5. Grounded Candidate 비율
6. Hallucinated Candidate 비율
7. 올바른 Tool 선택률
8. 평균 Tool 호출 수
9. 평균 Agent Turn 수
10. Budget 내 종료율
11. Schema 첫 시도 성공률
12. Schema retry 후 성공률
13. 올바른 insufficient evidence 비율
14. 올바른 ambiguous 비율
15. 반복 실행 결과 일관성
16. 평균 입력 token
17. 평균 출력 token
18. latency
19. Provider 오류율
20. Verifier rejection 사유 분포

## 실행 분리

일반 단위 테스트와 분리한다.

예:

```text
python -m preanalyzer.evaluation.runtime_command ...
```

또는 별도 script/CLI.

환경변수가 없으면 일반 테스트에서 실행하지 않는다.

## 결과 파일

기계 판독 가능:

```text
evaluation-results.json
```

사람이 읽는 요약:

```text
evaluation-report.md
```

최소 보고:

- 모델/endpoint 식별자
- Capability Profile
- Fixture별 결과
- 지표 집계
- 실패 사유 분포
- 평균 Tool/Turn/Token/Latency
- 반복 실행 일관성
- MVP 통과 여부

Secret, API Key, 전체 Prompt, reasoning, Repository 절대 경로를 기록하지 않는다.

## MVP 통과 기준

초기값은 문서에 제안값으로 명시하고 실제 평가 후 조정한다.

예:

```text
grounded command accuracy >= 80%
hallucinated candidate rate <= 5%
evidence reference accuracy >= 90%
budget completion rate >= 90%
schema success after one retry >= 95%
```

`insufficient_evidence`를 무조건 실패로 계산하지 않는다.

Ground truth가 insufficient인 Fixture에서의 올바른 포기는 성공이다.

## 반복성

Fixture별 최소 3회 반복을 지원한다.

temperature 기본 0.

같은 결과 여부뿐 아니라 다음을 비교한다.

- Action sequence
- Tool 선택
- Candidate
- Evidence refs
- Verification status

## 테스트

단위 테스트:

1. Fixture expectation loading
2. Metric calculation
3. Hallucination 계산
4. Evidence accuracy 계산
5. Consistency 계산
6. Report 생성
7. Secret redaction
8. endpoint 미설정 skip
9. Fake baseline 실행
10. deterministic report ordering

실제 모델 실행은 integration/evaluation으로 분리한다.

## 비목표

- 새 Task Type
- Tool 확장
- Budget 증가
- Prompt 최적화
- Dockerfile/Kubernetes 생성
- 외부 Tool Adapter

## 완료 보고

1. 평가 실행 방법
2. Fixture 구성
3. 지표 정의
4. 결과 파일
5. Fake baseline 결과
6. 실제 모델별 결과
7. 공통 실패 패턴
8. MVP 통과 판단
9. 다음 최적화 우선순위
