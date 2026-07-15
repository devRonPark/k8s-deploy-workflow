# Architecture Decision Records (ADR)

**Repository Assessment Engine**

Status: Accepted

## ADR-001

### OpenShell is the Only Agent Runtime

#### Status

Accepted

#### Context

제품은 Agent 기반 사용자 경험을 제공해야 한다.

Repository마다 필요한 분석 과정이 다르므로, 고정된 Workflow보다 상황에 따라 적절한 Capability를 선택할 수 있는 Planner가 필요하다.

동시에 Repository Fact의 신뢰성과 재현성은 보장되어야 한다.

#### Decision

OpenShell을 제품의 유일한 Agent Runtime으로 채택한다.

OpenShell은 Assessment Run loop를 소유한다.

Assessment Run은 하나의 Repository revision에 대한 stateful agent session이다.

OpenShell은 다음 역할만 수행한다.

- Workflow Planning
- Capability Selection
- User Interaction
- Result Explanation

OpenShell은 현재 run state를 관찰하고 다음 허용 Capability를 선택하며, decision이 필요한 경우에만 사용자에게 질문한다.

Repository 분석, Proposal 생성, Decision 저장, Manifest 생성은 Engine Capability가 수행한다.

OpenShell은 Repository Fact, Proposal, Decision, Manifest를 직접 생성하지 않는다.

#### Consequences

장점

- Planner 교체(Qwen, GPT, Claude 등)가 쉬워진다.
- Repository Fact는 모델 품질에 영향을 받지 않는다.
- Agent와 Engine의 책임이 명확하다.

단점

- Planner와 Engine 사이의 Contract를 유지해야 한다.

## ADR-002

### Capability-Centric Architecture

#### Status

Accepted

#### Context

초기 설계는 Parser, Rule, Renderer 등의 Tool 중심 구조였다.

Planner가 세부 Tool을 직접 선택하면 Tool 수가 증가할수록 Prompt와 Workflow가 복잡해진다.

#### Decision

Planner는 Tool이 아니라 Capability를 선택한다.

Capability는 제품 수준 기능이며, 내부 Pipeline은 외부에 노출하지 않는다.

MVP Capability

- Repository Discovery
- Repository Analysis
- Deployment Proposal
- Decision Management
- Manifest Generation

#### Consequences

장점

- Planner Prompt 단순화
- Tool 추가 시 Planner 수정 최소화
- Capability 내부 구현 변경이 외부에 영향을 주지 않는다.

## ADR-003

### RepositoryUnderstanding is the Core Domain

#### Status

Accepted

#### Context

초기 구현은 Workflow 중심으로 데이터가 여러 계층을 이동하며 생성·변형되었다.

그 결과 preanalyzer와 k8s_agent 간 중복 모델과 책임이 발생했다.

#### Decision

RepositoryUnderstanding을 제품의 핵심 Domain Object로 정의한다.

RepositoryUnderstanding은 Repository만 설명하는 순수하고 불변(Immutable) 모델이다.

포함하지 않는다.

- Proposal Item
- User Decision
- Organization Policy
- Target Cluster
- Deployment Result

#### Consequences

장점

- 모든 Consumer가 동일한 Domain Model을 사용한다.
- 구현 변경과 무관하게 출력 계약이 유지된다.
- Repository 분석은 한 번만 수행하고 재사용할 수 있다.

## ADR-004

### Repository Facts and Proposal Items Must Be Separated

#### Status

Accepted

#### Context

제안을 Repository의 사실과 혼합하면 사용자는 무엇이 실제 Repository 정보인지 판단할 수 없다.

#### Decision

Repository Fact와 Proposal Item을 완전히 분리한다.

RepositoryUnderstanding

- Repository에서 확인된 사실만 저장한다.

DeploymentProposal

- RepositoryUnderstanding에서 파생된 제안 묶음을 저장한다.
- deterministic recommendation과 AI-assisted proposal을 포함할 수 있다.
- 모든 Proposal Item은 origin을 명시적으로 분류한다.

Proposal Item은 Repository Fact를 변경하지 않는다.

#### Consequences

장점

- Explainability 향상
- Audit 가능
- 잘못된 Proposal을 쉽게 식별 가능

## ADR-005

### User Owns Final Decisions

#### Status

Accepted

#### Context

Manifest 생성에 필요한 일부 값은 Repository에서 확인할 수 없다.

예)

- Base Image
- Runtime Port
- Hostname

시스템이 자동 결정하면 잘못된 Manifest를 생성할 위험이 있다.

#### Decision

시스템은 Proposal Item만 생성한다.

모든 Proposal Item은 사용자 승인 후에만 사용할 수 있다.

승인은 항목별(Granular)로 수행한다.

Decision 상태

- Approved
- Modified
- Pending
- Rejected

DecisionRegistry는 Proposal Item에 대한 사용자 결정을 history와 함께 저장한다.

DecisionRegistry는 Repository Fact를 저장하지 않고 DeploymentProposal 원본을 수정하지 않는다.

Never Guess는 Repository Fact와 승인된 generation input에 적용된다.

Repository에 존재하지 않는 값은 승인 전 Proposal Item으로만 존재할 수 있다.

#### Consequences

장점

- 안전성 향상
- 사용자 신뢰 확보
- 부분 생성(Partial Generation) 가능

## ADR-006

### Repository Assessment Belongs to Presentation Layer

#### Status

Accepted

#### Context

Repository Assessment는 새로운 Domain 정보를 생성하지 않는다.

RepositoryUnderstanding을 사람이 이해하기 쉬운 형태로 표현하는 역할이다.

#### Decision

Repository Assessment는 Capability도 Domain Object도 아니다.

Presentation Layer에서 RepositoryUnderstanding을 Rendering한 결과이다.

Repository Assessment는 새로운 fact, proposal, decision을 생성하지 않는다.

Repository Assessment는

- CLI
- HTML
- VSCode
- Markdown

등 다양한 View에서 동일한 Domain을 표현한다.

#### Consequences

장점

- Domain과 UI 분리
- 다양한 출력 형태 지원
- Assessment 변경이 Domain에 영향을 주지 않는다.

## ADR-007

### Planner Model Acts as Bounded Planner and Explainer

#### Status

Accepted

#### Context

소형 로컬 모델은 장기 자유 계획(Long-horizon Planning)과 복잡한 Tool 조합에서 불안정할 수 있다.

특정 모델명은 교체될 수 있으므로 Architecture Decision은 Qwen 같은 구현 이름보다 Planner Model의 책임을 정의한다.

#### Decision

Primary local model은 bounded planner와 explainer로 동작한다.

Planner Model은 현재 상태에서 허용된 Capability 중 다음 행동을 선택한다.

Planner Model은 Proposal Generation을 Engine Capability를 통해 요청할 수 있다.

Planner Model은 직접 수행하지 않는다.

- Repository Fact 확정
- Conflict 해결
- Proposal 승인
- Manifest 생성
- Validation 결과 판정

Engine Capability가 해당 책임을 가진다.

#### Consequences

장점

- 로컬 모델에서도 안정적인 동작
- Planner 교체 용이
- 토큰 사용량 감소
- 동일 입력에 대한 재현성 향상

## Architecture Summary

제품은 다음 계층으로 구성된다.

Presentation Layer

↓

OpenShell Planner

↓

Capability Layer

↓

Domain Layer

↓

Deterministic Engine

↓

Infrastructure

각 계층은 상위 계층의 계약을 준수하며, Domain Model을 중심으로 느슨하게 결합한다.

## Guiding Principle

Planner는 다음 행동을 선택한다.

Engine은 사실을 증명한다.

Domain은 제품의 진실을 보존한다.

Presentation은 그 진실을 이해하기 쉽게 보여준다.
