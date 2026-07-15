# Domain Model Specification

**Repository Assessment Engine**

Version: 0.1 (Draft)

## Purpose

본 문서는 제품의 핵심 Domain Model을 정의한다.

Domain Model은 제품의 유일한 진실(Source of Truth)이다.

Capability는 Domain Model을 생성하거나 소비한다.

Presentation은 Domain Model을 표시한다.

Domain Model은 UI, OpenShell, CLI, Python 구현과 독립적이어야 한다.

Repository Assessment는 Domain Object가 아니다.

Assessment Run은 Domain Object가 아니라 OpenShell이 소유하는 stateful agent session이다.

## Domain Overview

Repository │ ▼ RepositoryUnderstanding │ ▼ DeploymentProposal │ ▼ DecisionRegistry │ ▼ GeneratedManifest

모든 Workflow는 위 Domain Object만 전달한다.

Capability끼리는 직접 데이터를 공유하지 않는다.

## Domain Object 1

### Repository

#### 의미

사용자가 분석을 요청한 원본 Repository.

#### 포함

- Source Location
- Commit / Revision
- Repository Metadata

#### 포함하지 않음

- 분석 결과
- AI 판단
- 사용자 입력

Repository는 영구적으로 변경되지 않는다.

## Domain Object 2

### RepositoryUnderstanding

#### 목적

Repository를 실행 가능한 수준까지 이해한 결과.

제품에서 가장 중요한 Domain Object이다.

#### 구성

ApplicationTopology

프로그램의 구조

예)

- Components
- Dependencies
- Runtime Relationships

LifecycleModel

프로그램을 어떻게 빌드하고 실행하는가

예)

- Build Strategy
- Execution Strategy
- Container Strategy

ConfirmedFacts

Evidence가 존재하는 사실.

예)

- Runtime Port
- Build Tool
- Framework
- Container Entry Point

Unknowns

Repository에서 확인되지 않은 정보.

Unknown은 실패가 아니다.

Conflicts

둘 이상의 근거가 충돌하는 정보.

자동 해결하지 않는다.

Evidence

모든 Confirmed Fact의 근거.

반드시 Repository 안에서 추적 가능해야 한다.

Coverage Limits

지원 범위 안에서 해석하지 못했거나 결론에 영향을 줄 수 있는 artifact 제한 사항.

Repository Analysis는 모든 field가 resolved 되었을 때가 아니라 complete understanding state를 만들었을 때 성공한다.

Complete understanding state는 confirmed facts, unresolved unknowns, conflicts, evidence, coverage limits를 포함한다.

#### Invariants

Repository 밖의 정보는 포함하지 않는다.

Proposal Item을 포함하지 않는다.

사용자 입력을 포함하지 않는다.

회사 정책을 포함하지 않는다.

Target Cluster 정보를 포함하지 않는다.

RepositoryUnderstanding은 Immutable이다.

## Domain Object 3

### DeploymentProposal

#### 목적

RepositoryUnderstanding에서 파생된 배포 제안 묶음.

Repository의 사실이 아니다.

DeploymentProposal은 deterministic recommendation과 AI-assisted proposal을 포함할 수 있다.

#### 구성

Proposal Item

예)

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

#### Invariants

Repository Fact를 수정하지 않는다.

Proposal Item은 반드시 Fact와 구분된다.

Proposal Item은 사용자 승인 전까지 적용되지 않는다.

모든 Proposal Item은 origin이 명시적으로 분류되어야 한다.

## Domain Object 4

### DecisionRegistry

#### 목적

Proposal Item에 대한 사용자 결정을 저장한다.

DecisionRegistry는 approved, modified, rejected, pending decision과 history를 보존한다.

DecisionRegistry는 Repository Fact를 저장하지 않고 DeploymentProposal을 변경하지 않는다.

#### Decision 상태

- Approved
- Modified
- Pending
- Rejected

#### Decision Item

예)

Field

container.base_image

Original Proposal

node:20-alpine

Final Value

node:22-alpine

Status

Modified

#### Invariants

Decision History를 보존한다.

RepositoryUnderstanding을 수정하지 않는다.

DeploymentProposal 원본을 수정하지 않는다.

## Domain Object 5

### GeneratedManifest

#### 목적

승인된 Decision만 사용하여 생성된 결과.

승인된 결정만으로 안전하게 생성할 수 없는 resource 또는 field는 Generation Hold로 남긴다.

#### MVP

- Deployment
- Service

#### Invariants

승인되지 않은 Proposal Item은 사용하지 않는다.

부분 생성이 가능하다.

생성 불가능한 Resource 또는 Field는 Generation Hold 상태를 유지한다.

GeneratedManifest는 RepositoryUnderstanding을 변경하지 않는다.

Generation Hold는 누락되거나 충돌하는 decision, 영향을 받는 resource, 다음 사용자 행동을 식별해야 한다.

## Domain Relationships

Repository

↓

RepositoryUnderstanding

↓

DeploymentProposal

↓

DecisionRegistry

↓

GeneratedManifest

위 방향 외의 참조는 허용하지 않는다.

## Domain Ownership

- Repository: Repository Discovery Capability
- RepositoryUnderstanding: Repository Analysis Capability
- DeploymentProposal: Deployment Proposal Capability
- DecisionRegistry: Decision Management Capability
- GeneratedManifest: Manifest Generation Capability

Capability는 자신의 Domain Object만 생성한다.

## Presentation Rule

Presentation Layer는 Domain Model을 변경하지 않는다.

Repository Assessment는 RepositoryUnderstanding의 presentation이다.

Repository Assessment는 Domain Object가 아니며 Engine Capability도 아니다.

Repository Assessment는 새로운 fact, proposal, decision을 생성해서는 안 된다.

예)

- Repository Assessment
- HTML Report
- CLI Summary
- Markdown Report

모두 RepositoryUnderstanding을 읽기만 한다.

## Constitutional Rules

1. Domain Object는 Immutable을 기본 원칙으로 한다. 2. Domain Object는 서로의 내부 상태를 변경하지 않는다. 3. Repository Fact와 Proposal Item은 절대 혼합하지 않는다. 4. Unknown은 정상 상태이다. 5. Conflict는 자동 해결하지 않는다. 6. Domain Model은 UI나 OpenShell에 의존하지 않는다. 7. 새로운 기능은 가능하면 Domain Object를 추가하지 않고 기존 Domain을 소비(Consume)하는 방향으로 설계한다.

## Design Philosophy

Flow는 변경될 수 있다.

Capability는 교체될 수 있다.

Planner는 바뀔 수 있다.

하지만

Domain Model은 제품의 가장 안정적인 자산이어야 한다.
