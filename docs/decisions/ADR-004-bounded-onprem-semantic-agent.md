# ADR-004: Bounded On-Premise Semantic Agent

## 상태

제안됨.

이 ADR은 구현 전 설계 결정이다. 실제 20B~30B급 On-Premise LLM 평가 결과에 따라 재검토될 수 있다.

## 배경

현재 Repository는 Step 0~6의 결정론적 Phase 1 분석을 구현했다. 구현된 흐름은 `repository_snapshot -> artifact_inventory -> evidence_model -> rule_inference`이며, Dockerfile, Compose, package 파일의 명시적 선언을 기반으로 후보를 만든다.

다음 유형은 결정론적 파서만으로 충분하지 않다.

- Dockerfile `CMD`가 shell script를 가리키고 실제 실행 명령은 script 내부에 있음
- package/build 파일 하나에 API, Worker, Scheduler 등 여러 실행 단위가 있음
- 런타임 포트나 dependency 주소가 설정 객체와 함수 전달 흐름을 거쳐 결정됨
- factory pattern, dependency injection, 동적 import가 runtime entrypoint를 숨김
- 여러 artifact 후보가 충돌하고 코드 의미 해석이 필요함

대상 LLM은 외부 상용 대형 모델이 아니라 고객사 또는 사내 환경에서 실행되는 20B~30B급 On-Premise LLM이다. 예상 서빙 환경은 vLLM 등의 OpenAI-compatible endpoint다. Native Tool Calling, JSON Schema Structured Output, Guided Decoding, 긴 context, 다단계 tool 사용 성능은 모델과 서빙 구성에 따라 다르다.

## 결정

Semantic Agent는 20B~30B급 On-Premise LLM을 기준으로 설계하며, 단일 과제, 제한된 Tool, 짧은 Agent Loop, 구조화 상태, 결정론적 검증을 사용한다.

채택한다.

- Deterministic First
- Bounded Tool-Using Agent
- 하나의 Task와 하나의 target field
- 과제별 Tool allowlist
- 짧은 순차 Tool Calling
- 도메인 중심 Tool
- Candidate 비교
- ModelCapabilityProfile
- Deterministic Verifier
- 실제 온프레미스 모델 평가

아키텍처 책임은 다음과 같이 나눈다.

```text
Deterministic Analyzer
  -> Semantic Task Builder
  -> Bounded Tool-Using Semantic Agent
  -> Deterministic Verifier
  -> Application Topology Model
  -> Kubernetes Intent Model
```

정확한 책임 문장은 다음과 같다.

> Semantic Agent 실행 여부는 결정론적 코드가 판단한다. Agent 실행 후 어떤 코드 분석 Tool을 호출할지는 LLM이 제한된 범위 안에서 판단한다.

## 대안

### 대안 1: Repository 전체를 LLM Context에 넣기

기각한다.

이 방식은 구현은 빠르지만 Secret 유출, context 초과, hallucination, 비재현성 위험이 크다. 20B~30B 모델에서 긴 context 코드 이해 성능을 완료 조건으로 삼을 수 없다.

### 대안 2: 자유로운 범용 Coding Agent 사용

기각한다.

범용 Coding Agent는 repository 탐색, shell 실행, 파일 수정, dependency 설치까지 연결되기 쉽다. 이 프로젝트의 목적은 Kubernetes manifest 생성 전 근거 있는 후보를 만드는 것이며, repository 수정이 아니다.

### 대안 3: 긴 자율 Agent Loop

기각한다.

긴 loop는 비용과 실패 모드가 커지고, On-Premise LLM에서 tool 사용 안정성이 낮을 수 있다. MVP는 `max_agent_turns: 4`, `max_tool_calls: 4`를 초기값으로 제한한다.

### 대안 4: 외부 생성 도구를 핵심 runtime으로 직접 결합

연기한다.

Draft, Move2Kube, Kompose, JKube는 유용한 후보를 만들 수 있지만, 출력은 정답이 아니다. MVP 핵심은 Semantic Task와 Verifier 계약이다.

### 대안 5: LLM이 최종 confidence와 Kubernetes YAML을 결정

기각한다.

confidence는 출처와 검증 정책이 정한다. LLM 기반 후보의 최대 confidence는 medium이다. Kubernetes YAML은 계속 Intent Model과 Template Renderer가 만든다.

## 채택 이유

- 현재 Phase 1의 결정론적 원칙을 유지한다.
- Secret 값이 LLM 또는 산출물로 흐르는 경로를 차단한다.
- On-Premise LLM의 불확실한 capability를 ModelCapabilityProfile과 fallback으로 흡수한다.
- Agent 실패가 전체 pipeline 실패가 되지 않는다.
- 실제 구현과 테스트를 task 단위로 작게 자를 수 있다.
- Fake Agent로 acceptance test를 재현할 수 있다.

## 장점

- 재현성과 감사 가능성이 높다.
- 실패가 unresolved로 남아 사용자가 확인할 수 있다.
- LLM이 잘하는 후보 비교와 좁은 코드 의미 해석에 집중한다.
- 도메인 tool을 통해 context 크기를 제한한다.
- 외부 도구를 adapter로 점진 도입할 수 있다.

## 단점과 비용

- 자유로운 Agent보다 구현해야 할 계약과 verifier가 많다.
- 초기에는 task type coverage가 작다.
- source location, snippet, tool trace를 연결하는 audit 모델이 필요하다.
- 실제 20B~30B 모델 평가 harness가 별도로 필요하다.
- 일부 Repository는 `insufficient_evidence`로 남을 수 있다.

## 결과

- 첫 MVP는 `resolve_runtime_command` 전용 Bounded Semantic Agent로 제한한다.
- Agent 실행 여부는 Semantic Task Builder가 결정한다.
- Agent는 task별 allowlist tool만 호출한다.
- Agent 출력은 `SemanticResolution`과 `SemanticCandidate` 계약을 따른다.
- Deterministic Verifier가 accepted, ambiguous, insufficient_evidence, rejected, budget_exhausted, tool_error를 판정한다.
- accepted 후보도 high confidence가 될 수 없다.
- 실패 시 기존 pipeline은 unresolved 상태로 계속 진행한다.

## 기각 또는 연기한 항목

- Repository 전체 Context 입력
- 자유로운 범용 Coding Agent
- 긴 자율 Agent Loop
- 무제한 Tool 호출
- Parallel Tool Calling 기본 사용
- 여러 필드 동시 해결
- LLM의 최종 confidence 결정
- LLM의 최종 Dockerfile 또는 Kubernetes YAML 자유 생성
- 상용 대형 모델만을 기준으로 한 설계
- Kantra, Move2Kube, Draft, Kompose, JKube의 MVP runtime 직접 통합

## 재검토 조건

다음 조건 중 하나가 발생하면 이 ADR을 재검토한다.

- 실제 20B~30B On-Premise LLM 평가에서 `max_agent_turns: 4`, `max_tool_calls: 4`로 `resolve_runtime_command` 성공률이 수용 기준에 미달
- Native Tool Calling 또는 JSON Schema Structured Output을 안정적으로 지원하지 않는 모델이 주요 대상이 됨
- 고객 환경에서 CLI tool 실행이 불가해 source evidence provider 전략을 바꿔야 함
- Secret redaction 또는 audit 요구사항이 더 엄격해짐
- Step 7 Application Topology Model이 SemanticCandidate보다 다른 입력 계약을 요구함
- 실제 구현 중 Verifier가 source line 근거를 판정하기 어렵다는 것이 확인됨
