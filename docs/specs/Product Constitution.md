# Product Constitution

**Repository Assessment Agent**

Version: 0.1 (Draft) Status: Living Constitution

## 0. Spec Priority

`docs/specs` 문서 사이에 충돌이 있으면 다음 순서를 따른다.

1. Product Constitution
2. Architecture Decision Records
3. Domain Model Specification
4. Capability Contract Specification

## 1. Purpose

이 제품의 목적은 Kubernetes Manifest를 생성하는 것이 아니다.

이 제품의 목적은 처음 보는 Repository를 실행 가능한 수준까지 신뢰성 있게 이해하는 것이다.

Kubernetes Manifest는 그 이해 결과를 활용하는 첫 번째 출력물(Output) 이다.

## 2. Product Mission

Repository를 실행 가능한 수준까지 이해하고, 확인된 사실과 시스템 제안을 명확히 구분하여, 개발자가 신뢰할 수 있는 Kubernetes 배포 초안을 생성한다.

## 3. Core Principles

### Principle 1 — Repository Understanding First

모든 기능은 Repository를 이해하는 것에서 시작한다.

Manifest 생성은 Repository Understanding 이후에만 가능하다.

Repository를 이해하지 못한 상태에서 Manifest를 생성해서는 안 된다.

### Principle 2 — Maximize Confidence, Not Automation

이 Agent의 목표는 자동화를 극대화하는 것이 아니다.

목표는 신뢰도를 극대화하는 것이다.

항상 다음 세 가지를 명확하게 구분한다.

- Confirmed Facts
- Conflicts
- Unknowns

Unknown을 숨기거나 추측하지 않는다.

### Principle 3 — Never Guess

Repository에 존재하지 않는 사실을 만들어서는 안 된다.

다음은 절대 자동 생성하지 않는다.

- Runtime Port
- Image Reference
- Hostname
- Secret Strategy
- Storage Strategy

근거가 없다면 Unknown으로 유지한다.

Never Guess는 Repository Fact와 승인된 generation input에 적용된다.

시스템은 Repository에 존재하지 않는 값을 DeploymentProposal 항목으로 제안할 수 있다.

단, 그 항목은 사용자가 명시적으로 승인하거나 수정하기 전까지 승인되지 않은 상태로 남아야 한다.

### Principle 4 — Facts and Proposals Must Never Mix

Repository에서 확인한 사실과 시스템 제안은 완전히 분리한다.

RepositoryUnderstanding에는

- Repository에서 관측한 사실만 포함된다.

DeploymentProposal에는

- RepositoryUnderstanding에서 파생된 제안만 포함된다.

RepositoryUnderstanding은 Proposal Item으로 변경되어서는 안 된다.

DeploymentProposal은 RepositoryUnderstanding에서 파생된 proposal set이다.

DeploymentProposal은 deterministic recommendation과 AI-assisted proposal을 포함할 수 있다.

모든 Proposal Item은 origin이 명시적으로 분류되어야 하며 Repository Fact와 분리되어야 한다.

### Principle 5 — User Owns Final Decisions

시스템은 제안만 한다.

최종 결정은 항상 사용자가 한다.

모든 Proposal Item은 승인 전까지 Manifest 생성에 사용될 수 없다.

### Principle 6 — Approval is Granular

승인은 Proposal 전체가 아니라 항목 단위이다.

예)

- Base Image
- Build Strategy
- Run Command
- Runtime Port

각 항목은

- Approved
- Modified
- Pending
- Rejected

상태를 가진다.

### Principle 7 — Partial Generation is Allowed

승인된 정보만으로 생성 가능한 리소스는 생성한다.

미승인 정보 때문에 전체 생성을 중단하지 않는다.

단,

생성 불가능한 리소스는 Generation Hold 상태가 된다.

Generation Hold는 승인된 결정만으로 안전하게 생성할 수 없는 resource 또는 field에 대한 정상적인 생성 결과다.

Generation Hold는 누락되거나 충돌하는 decision, 영향을 받는 resource, 다음 사용자 행동을 식별해야 한다.

### Principle 8 — Repository Understanding is Pure

RepositoryUnderstanding에는 Repository 외부 정보가 들어갈 수 없다.

포함 금지

- Organization Policy
- Target Cluster
- User Decisions
- Proposal Item

RepositoryUnderstanding은 언제나 Repository만 설명한다.

### Principle 9 — OpenShell is the Only Agent Runtime

Agent Runtime은 OpenShell이다.

Python 구현체는 Agent가 아니라 Tool이다.

OpenShell은

- Assessment Run loop 소유
- 현재 run state 관찰
- 다음 허용 Capability 선택
- 필요한 경우에만 사용자 질문
- run이 proceed, pause, hold 되는 이유 설명

을 담당한다.

OpenShell은 Repository Fact, Proposal, Decision, Manifest를 생성하지 않는다.

Python Tool은

- 분석
- 생성
- 검증

만 수행한다.

### Principle 10 — Single Source of Truth

Repository를 분석한 결과는 하나의 RepositoryUnderstanding만 존재한다.

모든 Consumer는 동일한 RepositoryUnderstanding을 사용한다.

## 4. Domain Model

Repository │ ▼ RepositoryUnderstanding │ ├── ApplicationTopology ├── LifecycleModel ├── ConfirmedFacts ├── Conflicts ├── Unknowns └── Evidence

RepositoryUnderstanding은 Repository를 설명하는 순수 모델이다.

## 5. Proposal Pipeline

RepositoryUnderstanding │

▼ DeploymentProposal │ ▼ DecisionRegistry │ ▼ GeneratedManifest

Proposal Item은 Repository를 변경하지 않는다.

## 5.1 Assessment Run

Assessment Run은 하나의 Repository revision에 대한 stateful agent session이다.

Assessment Run은 Repository에서 시작해 OpenShell의 제어 아래 허용된 Capability를 진행하고, Proposal과 Decision을 기록하며, GeneratedManifest, Generation Hold, 또는 둘 모두로 끝난다.

## 6. Repository Assessment

사용자에게는 내부 모델 대신 Repository Assessment를 제공한다.

Assessment에는 다음 정보가 포함된다.

- Execution Understanding
- Architecture Understanding
- Coverage
- Unknowns
- Conflicts
- Evidence Count
- Proposal Items
- Generation Capability

Repository Assessment는 사용자가 Repository의 현재 이해 수준을 평가할 수 있는 보고서이다.

Repository Assessment는 RepositoryUnderstanding의 presentation이다.

Repository Assessment는 Domain Object가 아니며 Engine Capability도 아니다.

Repository Assessment는 새로운 fact, proposal, decision을 생성해서는 안 된다.

## 7. MVP Scope

MVP는 다음만 지원한다.

Outputs

- Deployment
- Service

지원 대상

- Dockerfile 존재
- Dockerfile 미존재 Repository (DeploymentProposal 생성)

제외 대상

- ConfigMap
- Secret
- Ingress
- PVC
- ServiceAccount
- Organization Policy
- Target Cluster Profile
- Cluster Deployment
- Runtime Verification

### MVP Demo Commitments

MVP demo는 하나의 full Assessment Run을 보여줘야 한다.

이 run은 repository discovery, repository understanding, assessment presentation, proposal generation, granular user decision, partial manifest generation, 그리고 pending 또는 conflicting decision 때문에 발생한 최소 하나의 Generation Hold를 포함해야 한다.

## 8. Analyze Definition

Analyze는 Repository를 읽는 작업이 아니다.

Analyze는 RepositoryUnderstanding을 생성하는 작업이다.

Analyze가 성공하려면

- Structure를 이해해야 한다.
- Lifecycle을 이해해야 한다.
- Unknown을 식별해야 한다.
- Conflict를 식별해야 한다.
- Evidence를 연결해야 한다.

Unknown이 존재해도 Analyze는 성공할 수 있다.

Repository Analysis는 모든 field가 resolved 되었을 때가 아니라 complete understanding state를 만들었을 때 성공한다.

Complete understanding state는 supported scope 안에서 confirmed facts, unresolved unknowns, conflicts, evidence, coverage limits를 포함한다.

## 9. Success Criteria

이 제품은 다음 기준으로 평가한다.

- Unknown을 숨기지 않는다.
- False Facts는 0개이다.
- 모든 Confirmed Fact는 Evidence를 가진다.
- Conflict는 자동 해결하지 않는다.
- Proposal Item은 Repository Fact와 분리된다.
- RepositoryUnderstanding은 재사용 가능하다.
- 동일 Repository는 동일 Understanding을 생성한다.

성공적인 Agent Demo는 agent boundary를 명확히 보여줘야 한다.

즉, Repository가 증명한 것, 시스템이 제안한 것, 사용자가 결정한 것, 생성 가능한 것, Hold로 남아야 하는 것이 구분되어야 한다.

## 10. Future Vision

RepositoryUnderstanding은 제품의 핵심 자산이다.

Kubernetes는 첫 번째 Consumer일 뿐이다.

향후 Consumer 예시

- Kubernetes
- Helm
- Docker Compose
- Architecture Diagram
- Documentation
- ADR
- Migration Assistant

RepositoryUnderstanding을 기반으로 다양한 개발자 경험을 제공한다.

## Constitutional Rule

새로운 기능을 추가하기 전에 반드시 다음 질문에 답해야 한다.

"이 변경이 Product Constitution의 원칙을 위반하는가?"

위반한다면 기능보다 Constitution을 우선한다.
