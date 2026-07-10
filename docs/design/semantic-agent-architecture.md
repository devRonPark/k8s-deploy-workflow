# LLM 기반 Semantic Agent 아키텍처 설계

## 1. 배경과 문제 정의

현재 Repository는 Step 0~6의 결정론적 사전 분석(Phase 1)을 구현한 상태다. 구현된 체인은 `repository_snapshot -> artifact_inventory -> evidence_model -> rule_inference`이며, `src/preanalyzer/pipeline.py`의 `run_phase1_analysis(...)`가 `00-repository-snapshot.yaml`부터 `03-rule-inference.yaml`까지 산출한다.

현재 구현은 다음 입력에 강하다.

- Dockerfile의 `FROM`, `EXPOSE`, `CMD`, `ENTRYPOINT`, `USER`
- Compose service, image, build context, ports, environment, volumes, depends_on
- `pom.xml`, `package.json`, `pyproject.toml`, `requirements.txt` 같은 package/build 파일
- Compose override 1개 병합
- malformed package 파일의 warning 기록
- Secret 후보의 값 제외

그러나 결정론적 파서만으로는 코드 의미를 따라가야 하는 Repository를 충분히 분석하기 어렵다.

- Dockerfile `CMD`가 shell script를 가리키고 실제 runtime command가 script 내부에 있는 경우
- 하나의 package/build 파일 안에 API, Worker, Scheduler 실행 단위가 함께 있는 경우
- 포트가 Settings 객체, 함수 인자, 환경변수 조합을 거쳐 결정되는 경우
- factory pattern, dependency injection, 동적 import로 runtime entrypoint가 숨겨지는 경우
- 서로 다른 artifact의 후보가 충돌하고 코드 의미를 해석해야 하는 경우

이 문서는 Step 7 이후 Application Topology Model과 Kubernetes Intent Model로 가기 전에 필요한 bounded Semantic Agent의 책임과 경계를 고정한다. 프로덕션 구현은 이 문서의 범위 밖이다.

## 2. 현재 결정론적 파이프라인의 장점과 한계

### 장점

- 재현 가능하다. 같은 repository snapshot, 같은 rules version, 같은 clock 입력은 같은 Phase 1 산출물을 만든다.
- Evidence와 Candidate가 분리된다. `EvidenceFact.classification`은 `observed_fact`로 고정되고, Rule 후보는 `classification: rule_inference`를 가진다.
- Secret 값은 산출물에 포함하지 않는다. 현재 Compose environment fact도 Secret 이름이면 값 대신 `value_present`만 기록한다.
- 파서 failure가 전체 pipeline failure로 번지지 않는다. package 파서는 warning을 만들고 pipeline은 계속 진행한다.
- Dockerfile/Compose/package 파일처럼 명시적 선언이 있는 경우 runtime version, port, command, dependency edge 후보를 빠르게 만든다.

### 한계

- 현재 `RuntimeCommandCandidate`는 Dockerfile `CMD` 문자열을 직접 후보로 승격한다. `CMD ["./entrypoint.sh"]` 뒤의 실제 명령을 script 내부에서 추적하지 않는다.
- 현재 component boundary는 Compose service가 있으면 service 기준, 없으면 package fact 기반 root 후보에 가깝다. monorepo 내부의 다중 runtime entrypoint 해석은 제한적이다.
- 현재 `Tracked`는 `value/source/confidence/evidence_refs`만 가진다. 후보 dataclass에는 `classification`이 있지만, 향후 Semantic 계약은 `target_field`, `task_id`, tool trace, verification status를 별도 모델로 요구한다.
- 현재 Step 7 Application Topology Model과 Step 8 Kubernetes Intent Model은 구현되지 않았다.
- 현재 LLM Provider, Semantic Task, Semantic Agent, Deterministic Verifier는 구현되지 않았다.

## 3. 해결하려는 문제와 해결하지 않는 문제

### 해결하려는 문제

- 결정론적 Evidence와 Rule 후보만으로 확정할 수 없는 좁은 target field를 코드 의미 분석으로 보강한다.
- Semantic Agent가 Repository 전체를 자유 탐색하지 않고, 결정론적 코드가 생성한 하나의 Semantic Task만 처리하게 한다.
- LLM 결과를 최종 사실로 채택하지 않고 Deterministic Verifier가 검증 가능한 후보로만 취급한다.
- 20B~30B급 On-Premise LLM이 감당할 수 있는 짧은 context, 짧은 turn, 제한된 tool 구조를 정의한다.
- 실패해도 기존 pipeline이 unresolved 상태로 계속 진행하게 한다.

### 해결하지 않는 문제

- LLM이 Dockerfile 또는 Kubernetes YAML을 자유 생성하는 경로는 만들지 않는다.
- 범용 Coding Agent처럼 repository를 수정하거나 dependency를 설치하거나 shell을 실행하지 않는다.
- 여러 component와 여러 target field를 하나의 Agent 실행에서 동시에 해결하지 않는다.
- 기존 high-confidence 결정론적 후보를 LLM 후보가 임의로 덮어쓰지 않는다.
- 외부 생성 도구(Draft, Move2Kube, Kompose, JKube)의 출력을 정답으로 취급하지 않는다.
- 실제 20B~30B 모델 평가 자동화는 MVP 구현 이후 integration 또는 evaluation 단계로 분리한다.

## 4. 전체 아키텍처

```text
Deterministic Analyzer
  Step 0 Repository Snapshot
  Step 1 Artifact Inventory
  Step 2 Artifact Parsing
  Step 3 Evidence Model
  Step 4~6 Rule Inference
      |
      v
Semantic Task Builder
  unresolved field / conflict / indirect entrypoint 감지
  component + target field 단위 task 생성
      |
      v
Bounded Tool-Using Semantic Agent
  On-Premise LLM + task별 allowlist tool
  짧은 순차 tool call
  SemanticCandidate 반환
      |
      v
Deterministic Verifier
  schema / evidence / target field / secret / confidence / trace 검증
      |
      v
Application Topology Model
      |
      v
Kubernetes Intent Model
      |
      v
Template Renderer
```

핵심 책임 문장은 다음과 같다.

> Semantic Agent 실행 여부는 결정론적 코드가 판단한다. Agent 실행 후 어떤 코드 분석 Tool을 호출할지는 LLM이 제한된 범위 안에서 판단한다.

## 5. 구성요소 책임

### Deterministic Analyzer

담당한다.

- 명시적 artifact 파싱
- `EvidenceFact`와 Rule 후보 생성
- 분석되지 않은 필드와 후보 충돌 탐지
- Semantic Task 생성 조건 판정
- Semantic Agent 실행 여부 판정

담당하지 않는다.

- LLM tool 선택
- 코드 의미의 자유 추론
- Semantic 후보의 최종 채택
- Kubernetes YAML 생성

현재 구현의 대응 모듈은 `src/preanalyzer/analyzer/scanner.py`, `src/preanalyzer/analyzer/parsers/`, `src/preanalyzer/analyzer/evidence_builder.py`, `src/preanalyzer/analyzer/rule_inference.py`, `src/preanalyzer/pipeline.py`다.

### Semantic Task Builder

결정론적 코드가 하나의 좁은 분석 과제를 생성한다.

- 하나의 task는 원칙적으로 하나의 `component_id`와 하나의 `target_field`만 대상으로 한다.
- MVP task type은 `resolve_runtime_command`를 첫 구현 대상으로 제한한다.
- task 생성 근거는 기존 Evidence와 Rule 후보에 있어야 한다.
- task 생성 조건 예시는 Dockerfile `CMD` 또는 `ENTRYPOINT`가 shell script, package script, module entrypoint 같은 간접 target을 가리키는 경우다.

### Bounded Tool-Using Semantic Agent

Agent는 이미 생성된 Semantic Task를 입력으로 받는다. LLM은 Agent 실행 여부를 결정하지 않는다.

Agent 내부에서 LLM이 할 수 있는 일은 제한된다.

- 현재 task 상태를 읽는다.
- allowlist 안의 tool 중 다음 호출을 선택한다.
- tool result를 바탕으로 후보를 비교한다.
- schema-constrained `SemanticCandidate` 또는 unresolved resolution을 반환한다.

Agent가 할 수 없는 일은 명시적으로 금지한다.

- Repository 전체를 context에 넣기
- allowlist 밖 tool 호출
- 파일 수정
- shell 실행
- network 접근
- dependency 설치
- 여러 target field 동시 수정
- 최종 Application Topology 또는 Kubernetes Intent 직접 수정

### Deterministic Verifier

Verifier는 Semantic Agent 결과를 최종 사실이 아니라 검증 대상 후보로 본다. 검증 결과는 다음 중 하나다.

```text
accepted
ambiguous
insufficient_evidence
rejected
budget_exhausted
tool_error
```

검증 기준은 다음과 같다.

- JSON 또는 Pydantic schema 준수
- `evidence_refs`가 실제 `EvidenceModel`에 존재
- 인용한 코드 위치가 후보 값을 실제로 뒷받침
- Repository와 기존 후보에 없는 값을 생성하지 않음
- 허용된 `target_field`만 대상으로 함
- Secret 값 미포함
- 기존 high-confidence 결정론적 증거를 임의로 덮어쓰지 않음
- tool trace와 최종 evidence가 연결됨

## 6. Agent 실행 여부와 Tool 호출 여부의 차이

두 결정 지점은 다르다.

| 결정 | 주체 | 입력 | 결과 |
|---|---|---|---|
| Agent를 실행할지 | 결정론적 코드 | Evidence, Rule 후보, unresolved field, conflict | `SemanticTask` 생성 또는 미생성 |
| Agent 내부에서 어떤 Tool을 호출할지 | LLM, 단 allowlist와 budget 안에서 | `SemanticTask`, `SemanticAgentState`, 이전 tool result | 다음 tool call 또는 final candidate |

따라서 문서와 구현에서는 실행 여부와 내부 tool 선택을 같은 책임으로 묶어 표현하지 않는다. 정확한 표현은 “결정론적 코드가 Semantic Task와 Agent 실행 여부를 결정하고, Agent 내부에서 LLM이 허용된 코드 분석 Tool 호출을 선택한다”이다.

## 7. Application Topology와 Kubernetes Intent 연결

Semantic Agent의 출력은 Application Topology Model이나 Kubernetes Intent Model에 직접 쓰이지 않는다.

1. Deterministic Analyzer가 Rule 후보와 unresolved field를 만든다.
2. Semantic Task Builder가 좁은 task를 만든다.
3. Semantic Agent가 `SemanticCandidate`를 반환한다.
4. Deterministic Verifier가 `VerificationResult`를 만든다.
5. accepted 결과만 기존 candidate stream에 `classification: llm_interpretation` 또는 별도 semantic classification으로 추가된다.
6. Application Topology Model은 Rule 후보, verified Semantic 후보, user decision을 reconciliation 정책으로 승격한다.
7. Kubernetes Intent Model은 Application Topology를 기반으로 만든다.
8. Kubernetes YAML은 계속 Template Renderer가 만든다.

`resolve_runtime_command`의 경우 accepted 후보는 runtime command 후보를 보강할 수 있지만, image registry, namespace, ingress host, resource 수치 같은 운영환경 값은 만들 수 없다.

## 8. 실패와 fallback 흐름

```text
직접 결정론적으로 완전히 해석된 terminal runtime command 후보 있음
  -> Semantic Agent 실행 안 함

간접 entrypoint 또는 unresolved target field 감지
  -> Semantic Task 생성
  -> Agent 실행
  -> Verifier 검증
      accepted
        -> semantic candidate stream에 추가
      ambiguous / insufficient_evidence
        -> unresolved 유지, 질문 또는 profile field로 라우팅
      rejected
        -> candidate 폐기, audit 기록
      budget_exhausted / tool_error
        -> unresolved 유지, pipeline 계속
```

LLM 또는 tool 실패는 전체 pipeline 실패로 이어지지 않는다. 실패는 audit 정보와 함께 기록하고, 기존 Rule 후보와 unresolved 상태로 다음 단계가 계속 진행한다.

## 9. 향후 확장 지점

- `resolve_runtime_port`: Settings 객체, env var, CLI arg 전달 흐름 추적
- `resolve_component_role`: API, Worker, Scheduler, dependency, infrastructure 역할 해석
- `resolve_dependency_edge`: env var 조합, client factory, service discovery 코드에서 edge 후보 보강
- source evidence provider adapter: Kantra/analyzer-lsp, tree-sitter, ast-grep, LSP 결과를 tool result로 연결
- candidate generator adapter: Draft, Kompose, JKube 결과를 정답이 아닌 비교 후보로 연결
- evaluation harness: 실제 20B~30B On-Premise LLM에서 fixture별 성공률, evidence grounding, budget exhaustion 비율 측정

## 10. 명시적인 비목표

- LLM free-form Dockerfile 생성
- LLM free-form Kubernetes YAML 생성
- Repository 전체 context 입력
- 긴 자율 Agent loop
- parallel tool calling 기본 사용
- 파일 수정 tool, shell 실행 tool, network tool
- 외부 tool의 직접 Python dependency 채택
- Secret 실제 값의 LLM 입력 또는 산출물 포함
- LLM 기반 후보의 high confidence 승격
- 상용 대형 모델에서만 성공하는 기능을 완료로 판단

## 11. 관련 문서

- `README.md`
- `onprem-llm-k8s-manifest-preanalysis-workflow.md`
- `docs/architecture.md`
- `docs/design/semantic-agent-contracts-and-policies.md`
- `docs/decisions/ADR-004-bounded-onprem-semantic-agent.md`
- `docs/plans/semantic-agent-mvp-plan.md`
