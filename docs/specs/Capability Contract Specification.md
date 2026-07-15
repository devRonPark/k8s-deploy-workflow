# Capability Contract Specification

**OpenShell ↔ Repository Assessment Engine**

Version: 0.1 (Draft)

## Purpose

본 문서는 OpenShell Planner와 Repository Assessment Engine 사이의 계약(Contract)을 정의한다.

OpenShell은 Assessment Run loop를 소유하고 Capability를 선택해 실행을 요청한다.

Capability는 계약된 입력과 출력만 사용한다.

Repository Fact를 생성하는 Capability는 결정론적(Deterministic) 실행을 수행한다.

OpenShell은 Capability 내부 구현을 알지 못한다.

## Capability Overview

Repository Discovery │ ▼ Repository Analysis │ ▼ Deployment Proposal │ ▼ Decision Management │ ▼ Manifest Generation

Capability는 순차적인 제품 Workflow를 나타낸다.

Capability 내부 Pipeline은 외부에 노출하지 않는다.

Repository Assessment는 Capability가 아니다.

Repository Assessment는 RepositoryUnderstanding의 Presentation Output이며 새로운 fact, proposal, decision을 생성하지 않는다.

## Capability 1

### Repository Discovery

#### Purpose

Repository의 기술적 특성을 식별한다.

Repository를 분석하는 것이 목적이 아니다.

어떤 분석이 필요한지 결정하기 위한 메타데이터를 생성한다.

#### Input

Repository Location

#### Output

DiscoveryResult

포함 정보

- Repository Type
- Language Candidates
- Framework Candidates
- Dockerfile 존재 여부
- Compose 존재 여부
- Kubernetes Manifest 존재 여부
- Monorepo 여부
- Candidate Components

#### Preconditions

Repository가 접근 가능해야 한다.

#### Postconditions

DiscoveryResult가 생성된다.

#### Invariants

절대 Repository Fact를 생성하지 않는다.

Repository를 이해했다고 판단하지 않는다.

## Capability 2

### Repository Analysis

#### Purpose

Repository를 실행 가능한 수준까지 이해한다.

#### Input

DiscoveryResult

#### Internal Pipeline

Pipeline은 Capability 내부 구현이다.

외부에서 호출하거나 제어할 수 없다.

예)

- Language Parser
- Framework Parser
- Rule Engine
- Evidence Builder
- Lifecycle Builder
- Topology Builder

#### Output

RepositoryUnderstanding

포함 정보

- ApplicationTopology
- LifecycleModel
- Confirmed Facts
- Unknowns
- Conflicts
- Evidence

#### Preconditions

DiscoveryResult가 존재한다.

#### Postconditions

RepositoryUnderstanding이 생성된다.

Unknown이 존재해도 성공할 수 있다.

Repository Analysis는 모든 field가 resolved 되었을 때가 아니라 complete understanding state를 만들었을 때 성공한다.

Complete understanding state는 supported scope 안에서 confirmed facts, unresolved unknowns, conflicts, evidence, coverage limits를 포함한다.

#### Invariants

Repository 밖의 정보를 포함하지 않는다.

Proposal Item을 생성하지 않는다.

사용자 질문을 생성하지 않는다.

## Capability 3

### Deployment Proposal

#### Purpose

RepositoryUnderstanding에서 배포 제안 묶음을 생성한다.

Repository에 존재하지 않는 값은 Repository Fact가 아니라 Proposal Item으로만 제안할 수 있다.

#### Input

RepositoryUnderstanding

#### Output

DeploymentProposal

Proposal 예시

- Base Image
- Build Strategy
- Run Command
- Runtime Port
- Dockerfile
- Deployment
- Service

각 Proposal Item은 다음 정보를 가진다.

- Proposed Value
- Reason
- Related Evidence
- Confidence
- Origin

Origin 예시

- deterministic_recommendation
- ai_assisted_proposal
- user_supplied_decision

#### Preconditions

RepositoryUnderstanding이 존재한다.

#### Postconditions

모든 Proposal Item은 origin을 가진다.

사용자가 승인하거나 수정하기 전까지 Proposal Item은 generation input으로 사용할 수 없다.

#### Invariants

Proposal Item은 Repository Fact가 아니다.

RepositoryUnderstanding을 변경하지 않는다.

모든 Proposal Item은 Evidence 또는 Reason을 포함해야 한다.

모든 Proposal Item은 Repository Fact와 분리되어야 한다.

## Capability 4

### Decision Management

#### Purpose

Proposal Item에 대한 사용자 결정을 관리한다.

#### Input

DeploymentProposal

User Decisions

#### Output

DecisionRegistry

Decision 상태

- Approved
- Modified
- Pending
- Rejected

#### Preconditions

DeploymentProposal이 존재한다.

#### Postconditions

사용자 결정이 DecisionRegistry에 기록된다.

Pending decision은 생성 보류의 근거로 남는다.

#### Invariants

Repository Fact를 변경하지 않는다.

DeploymentProposal 원본을 삭제하거나 수정하지 않는다.

Decision History를 보존한다.

## Capability 5

### Manifest Generation

#### Purpose

승인된 Decision만 사용하여 Kubernetes Manifest를 생성한다.

#### Input

DecisionRegistry

#### Output

GeneratedManifest

Generation Holds

MVP Output

- Deployment
- Service

#### Preconditions

필수 Decision이 승인되어야 한다.

#### Postconditions

생성 가능한 Resource만 생성된다.

생성할 수 없는 Resource 또는 Field는 Generation Hold로 기록된다.

#### Invariants

승인되지 않은 Proposal을 사용하지 않는다.

Repository Fact를 수정하지 않는다.

생성 불가능한 Resource 또는 Field는 Generation Hold 상태로 유지한다.

## OpenShell Responsibilities

OpenShell은 Assessment Run loop를 소유한다.

OpenShell은 다음만 수행한다.

- Capability 선택
- Capability 실행
- 현재 run state 관찰
- decision이 필요한 경우에만 사용자 질문
- 사용자 응답 전달
- run이 proceed, pause, hold 되는 이유 설명

OpenShell은 다음을 수행하지 않는다.

- Repository 분석
- Repository Fact 생성
- Proposal 생성
- Decision 생성
- Manifest 생성
- Validation

## Deterministic Engine Responsibilities

Engine은 다음을 수행한다.

- Discovery
- Analysis
- Proposal generation
- Decision Persistence
- Manifest Generation

Engine은 Repository Fact를 생성하는 경로에서 항상 동일 입력에 동일 RepositoryUnderstanding을 생성해야 한다.

Proposal generation은 AI-assisted proposal을 포함할 수 있지만, 그 결과는 origin이 분류된 Proposal Item이어야 하며 Repository Fact를 변경할 수 없다.

## Contract Rules

모든 Capability는 다음 계약을 만족해야 한다.

1. 입력 모델은 불변(Immutable)이다. 2. 출력 모델은 다음 Capability의 유일한 입력이 된다. 3. Capability는 자신의 출력 외 다른 모델을 수정하지 않는다. 4. Repository Fact와 Proposal Item은 절대 혼합하지 않는다. 5. Unknown은 오류가 아니라 정상 상태이다. 6. Conflict는 자동 해결하지 않는다. 7. Capability 내부 Pipeline은 외부에 노출하지 않는다. 8. OpenShell은 Capability만 호출하며 내부 Tool을 직접 호출하지 않는다. 9. 승인되지 않은 Proposal Item은 Manifest Generation input으로 사용할 수 없다.
