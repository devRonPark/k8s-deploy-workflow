You are Claude Fable 5.

Create a professional Korean technical workflow document for the following problem:

“Design a deterministic pre-analysis workflow for generating Kubernetes manifests by analyzing arbitrary GitHub repositories, using an On-Premise LLM or an OpenAI-compatible endpoint integration.”

The final document must be written in Korean and must be practical enough for engineers to implement.

---

## 1. Goal

I want a complete Korean architecture/design document that explains how to analyze arbitrary GitHub repositories before generating Kubernetes manifests.

The target system should generate Kubernetes manifests that are not merely syntactically valid, but are designed to make the application runnable on Kubernetes when the required runtime environment information is available.

However, the document must clearly explain that a GitHub source repository alone often does not contain all required runtime values, such as database connection information, credentials, external API endpoints, registry addresses, ingress hosts, storage classes, TLS secrets, and production resource policies.

Therefore, the workflow must distinguish between:

* Repository-only analysis
* Deployment Profile-based manifest generation
* Post-deployment validation

The core design principle is:

“The LLM must not directly guess Kubernetes YAML from raw repository content. Repository artifacts must first be parsed deterministically into intermediate models. Missing runtime values must be routed to questions, placeholders, or Deployment Profile fields.”

---

## 2. Target Audience

The document is for:

* Kubernetes engineers
* Platform engineers
* AI agent workflow designers
* DevOps engineers
* Technical sales / solution architects
* Enterprise customers evaluating an On-Premise AI-based Kubernetes migration or deployment assistant

The writing style should be clear, practical, and structured.
Use Korean explanations, but keep technical terms such as Deployment, Service, Ingress, ConfigMap, Secret, PVC, HPA, ServiceAccount, Dockerfile, Docker Compose, Helm, Kustomize, Buildpack, parser, renderer, validator, artifact, OpenAI-compatible endpoint, Chat Completions API, base_url, api_key, model, JSON Schema in English where natural.

---

## 3. Benchmark Open-Source Projects

Use the following open-source projects as benchmark references.

Do not merely summarize them.
For each one, explain what part of its design should be benchmarked and how that design maps to the proposed Kubernetes manifest generation workflow.

### 3.1 Kompose

Benchmark focus:

* Deterministic conversion from docker-compose.yml to Kubernetes resources
* Service, port, volume, environment variable, network, dependency mapping
* Compose service to Deployment/Service conversion
* Compose volume to PVC or volume candidate
* Compose environment to ConfigMap/Secret candidate

Use Kompose to define deterministic Compose-to-Kubernetes mapping rules.

### 3.2 Move2Kube

Benchmark focus:

* Source artifact analysis
* Planning model
* Transformation pipeline
* User question generation
* Multiple output formats such as Kubernetes YAML, Helm chart, or other deployment artifacts

Use Move2Kube as the strongest architectural reference for:

Collect → Analyze → Plan → Transform → Validate

### 3.3 Skaffold

Benchmark focus:

* Build/deploy workflow
* Artifact detection
* Image build target separation
* Multi-component repository handling
* Manifest render and deploy separation

Use Skaffold to separate:

* Build artifacts
* Container images
* Deployment manifests
* Development workflow
* Deployment workflow

### 3.4 Azure Draft

Benchmark focus:

* Automatic application detection
* User questions
* Template-based generation
* Dockerfile and Kubernetes manifest generation from app source

Use Azure Draft to define how uncertain information should be asked from the user instead of guessed by the model.

### 3.5 Cloud Native Buildpacks / Paketo

Benchmark focus:

* Detect phase
* Language and framework detection
* Runtime and build method detection
* File indicator-based analysis
* Build plan concept

Use Buildpacks/Paketo to design rule-based detection for language, framework, build system, and runtime.

---

## 4. Test Repository Set

The workflow document must include a benchmark test repository set.

Include at least the following repositories:

### 4.1 mybatis/jpetstore-6

Purpose:

* Single Java web application analysis

Test focus:

* Maven project detection
* Java web application structure detection
* Dockerfile absence or presence handling
* Runtime port uncertainty handling
* Build command inference from Maven files
* Whether the analyzer avoids guessing DB/runtime values

Expected output:

* Single component model
* Java/Maven build method
* Runtime uncertainty list
* Deployment Profile requirements

### 4.2 fastapi/full-stack-fastapi-template

Purpose:

* Modern full-stack mono repo analysis

Test focus:

* Backend/frontend separation
* Docker Compose analysis
* Traefik/reverse proxy configuration
* Environment variable classification
* Secret candidate classification
* CI/CD file detection
* Multi-service dependency extraction

Expected output:

* Multiple components
* Backend API component
* Frontend component
* DB/cache/service dependencies if present
* ConfigMap/Secret placeholder separation
* Ingress/Traefik-related unresolved questions

### 4.3 GoogleCloudPlatform/microservices-demo

Purpose:

* Kubernetes-native microservices reference application

Test focus:

* Existing Kubernetes manifest analysis
* Multi-service topology extraction
* Multi-language component handling
* Service-to-service dependency detection
* Comparison between generated Kubernetes Intent Model and existing manifests

Expected output:

* Multiple service components
* Existing manifest inventory
* Kubernetes Intent Model derived from existing resources
* Minimal unresolved questions compared to source-only repositories

### 4.4 spring-petclinic/spring-petclinic-microservices

Purpose:

* Spring Boot / Spring Cloud microservices analysis

Test focus:

* Multiple Maven modules
* Spring Boot service detection
* API gateway pattern detection
* Config server pattern detection
* Service discovery pattern detection
* Internal service dependency extraction
* Docker Compose and Kubernetes artifact comparison if present

Expected output:

* Multi-component Spring service model
* Spring Boot port/config candidates
* Internal dependency graph
* Externalized configuration questions

### 4.5 dotnet/eShop or dotnet-architecture/eShopOnContainers

Purpose:

* .NET microservices and container-based application analysis

Test focus:

* .NET solution and project file detection
* Docker-based microservice structure
* Kubernetes or Azure Kubernetes deployment artifact analysis
* Archived repository handling if using eShopOnContainers
* Active vs archived reference source distinction

Expected output:

* Multi-component .NET service model
* Docker artifact mapping
* Registry/image naming questions
* External dependency and secret placeholder questions

### 4.6 Additional Optional Test Repositories

The document may add more test repositories if useful, such as:

* A Node.js Express app with Dockerfile
* A React/Vite frontend-only repository
* A Go microservice with go.mod
* A repository with Helm chart only
* A repository with Kustomize overlays only

For each test repository, include:

* Why this repository is useful
* What artifacts should be detected
* Expected component model
* Expected Kubernetes intent model characteristics
* Expected unresolved questions
* Expected validation checks
* What analyzer failure modes the repository can reveal

---

## 5. Critical Runtime Requirement

The generated Kubernetes manifests must aim to make the application actually runnable on Kubernetes.

However, the document must explicitly distinguish the following success levels:

### Level 0. Manifest Generated

Definition:

* YAML files are generated from templates.
* Required values may still be missing.
* This level does not guarantee Kubernetes validity or application startup.

### Level 1. Kubernetes-Valid Manifests

Definition:

* YAML syntax is valid.
* Kubernetes schema validation passes.
* Resources can pass client-side or server-side dry-run.
* Tools such as kubeconform, kubeval, or kubectl dry-run can validate the result.

This level answers:

“Can Kubernetes understand these resources?”

### Level 2. Pod-Runnable Manifests

Definition:

* Container image can be built.
* Image can be pushed to the configured registry.
* Deployment can be applied.
* Pod can reach Running state.
* Container does not immediately crash due to missing command, port, or image configuration.

This level answers:

“Can the container start on Kubernetes?”

### Level 3. Application-Runnable Manifests

Definition:

* Pod reaches Ready state.
* readinessProbe passes.
* Service routes traffic correctly.
* Ingress or internal access works.
* Required external dependencies are reachable.
* Required environment variables and Secret references are provided.
* Basic smoke test passes.

This level answers:

“Can the application actually work on Kubernetes?”

The document must clearly state:

* Repository-only mode can target Level 1 and partial Level 2.
* Deployment Profile mode can target Level 2 and Level 3.
* Level 3 cannot be guaranteed from GitHub source repository alone when required runtime values are missing.
* Level 3 requires user-provided runtime values and post-deployment validation.

---

## 6. Runtime Gap Handling Policy

Add a dedicated section called:

# Runtime Gap 처리 정책

This section must explain how to handle missing runtime and environment-specific values.

Examples of values that are usually not present in GitHub repositories:

* DB_HOST
* DB_PORT
* DB_NAME
* DB_USER
* DB_PASSWORD
* JDBC_URL
* DATABASE_URL
* REDIS_URL
* KAFKA_BROKERS
* API_TOKEN
* JWT_SECRET
* OAUTH_CLIENT_SECRET
* SMTP_HOST
* SSO_URL
* external API endpoints
* image registry
* namespace
* ingress host
* ingress class
* TLS secret name
* storage class
* resource requests and limits
* node selector / toleration / affinity
* production replica count

The workflow must not guess these values.

If these values are missing, the analyzer must generate:

* unresolved_questions.yaml
* secret.placeholder.yaml
* deployment-profile.template.yaml
* deployment-readiness-checklist.md
* smoke-test-plan.yaml

Classify environment variables into:

* ConfigMap candidates
* Secret candidates
* Required unresolved values
* Optional unresolved values
* Framework defaults with low confidence
* User-confirmation-required values

Include an example like:

```yaml
env_classification:
  configmap_candidates:
    - name: APP_ENV
      source: docker-compose.yml
      confidence: high
    - name: LOG_LEVEL
      source: application.yml
      confidence: medium
  secret_candidates:
    - name: DB_PASSWORD
      reason: "Variable name contains PASSWORD"
      confidence: high
    - name: JWT_SECRET
      reason: "Variable name contains SECRET"
      confidence: high
  unresolved_required:
    - name: DB_HOST
      reason: "Required database host is not available in repository"
      blocking_level: application_runnable
  unresolved_optional:
    - name: SMTP_HOST
      reason: "Email feature may be optional"
      blocking_level: feature_partial
```

---

## 7. Deployment Profile Requirement

Add a dedicated section called:

# Deployment Profile 기반 보정 흐름

The document must introduce the concept of a Deployment Profile.

A Deployment Profile is an environment-specific input file that provides values not available in source repositories.

The document must include this example schema:

```yaml
deployment_profile:
  target_cluster:
    namespace: myapp-dev
    image_registry: harbor.internal.local/team
    ingress_class: nginx
    storage_class: longhorn

  exposure:
    type: ingress
    host: myapp.dev.company.local
    tls:
      enabled: false
      secret_name: null

  external_dependencies:
    database:
      mode: external
      type: postgresql
      host: postgres.internal.local
      port: 5432
      database: myapp
      username_secret_ref:
        name: myapp-db-secret
        key: username
      password_secret_ref:
        name: myapp-db-secret
        key: password
    cache:
      mode: external
      type: redis
      host: redis.internal.local
      port: 6379

  runtime_config:
    configmap_values:
      APP_ENV: dev
      LOG_LEVEL: info
    secret_refs:
      JWT_SECRET:
        name: myapp-secret
        key: jwt-secret

  resource_policy:
    default_requests:
      cpu: "100m"
      memory: "256Mi"
    default_limits:
      cpu: "500m"
      memory: "512Mi"

  smoke_test:
    path: /health
    expected_status: 200
```

Explain this correction flow:

1. Repository analysis generates unresolved questions.
2. User or platform team fills deployment_profile.yaml.
3. Analyzer merges repository analysis with Deployment Profile.
4. Kubernetes Intent Model is regenerated.
5. Template renderer generates Kubernetes manifests.
6. Validator checks Kubernetes validity.
7. Deployment checker verifies Pod Running and Ready.
8. Smoke test confirms application-level availability.

---

## 8. Model Integration Architecture

Add a dedicated section for model integration architecture.

The system must support two model integration options.

### Option A. Local On-Premise LLM Runtime

Requirements:

* The model runs inside the enterprise network.
* The analyzer calls the local inference server.
* Discuss model placement, network isolation, GPU resource planning, latency, security, and audit logging at a high level.
* The model must not receive secrets unless explicitly allowed by security policy.
* The model should receive normalized intermediate models rather than raw repository dumps.

### Option B. OpenAI Endpoint API-Compatible Integration

Requirements:

* The model server exposes an OpenAI-compatible API endpoint.

* The analyzer can call the model using an OpenAI-style client configuration.

* The integration should support configurable:

  * base_url
  * api_key
  * model name
  * timeout
  * max_tokens
  * temperature
  * top_p
  * response_format or JSON schema mode if supported

* Recommend deterministic generation settings:

  * temperature: 0
  * top_p: 1
  * fixed system prompt
  * schema-constrained output
  * retry with validation feedback only

Important clarification:

OpenAI-compatible endpoint support does not mean the model must be OpenAI-hosted.

It may be:

* vLLM
* TGI
* llama.cpp server
* Ollama-compatible gateway
* LiteLLM proxy
* an internal LLM gateway
* any model server exposing compatible endpoint behavior

The system must separate the “LLM Provider Interface” from the “Repository Analyzer” so that model backends can be replaced without changing the deterministic analysis pipeline.

Include this example configuration:

```yaml
llm_provider:
  mode: openai_compatible
  base_url: "https://llm-gateway.internal.example.com/v1"
  api_key_env: "LLM_API_KEY"
  model: "internal-k8s-manifest-assistant-30b"
  request_defaults:
    temperature: 0
    top_p: 1
    max_tokens: 4096
    timeout_seconds: 60
  output_contract:
    format: json_schema
    schema_name: unresolved_questions_or_patch_suggestion
```

Also include a local runtime option example:

```yaml
llm_provider:
  mode: local_runtime
  endpoint: "http://vllm.k8s-ai.svc.cluster.local:8000/v1"
  model: "qwen-or-llama-based-30b"
  network_policy: internal_only
  audit_logging: enabled
  request_defaults:
    temperature: 0
    top_p: 1
    max_tokens: 4096
```

Include this text-based architecture diagram:

```text
Repository Analyzer
  ↓
Intermediate Models
  ↓
LLM Provider Interface
  ↓
Provider A: Local Runtime
Provider B: OpenAI-Compatible Endpoint
  ↓
Schema-Constrained LLM Output
  ↓
Template Renderer / Validator
```

---

## 9. Deterministic Design Constraints

Important constraints:

* Do not write a generic Kubernetes article.

* Do not simply summarize the benchmark projects.

* The final output must be a practical workflow document.

* The workflow must prioritize deterministic parsing, rule-based detection, intermediate models, template rendering, and validation.

* LLM usage must be limited to:

  * analysis summary
  * conflict explanation
  * unresolved question generation
  * validation error repair suggestions
  * user-facing documentation

* LLM must not be used for:

  * file existence detection
  * Docker Compose parsing
  * Dockerfile parsing
  * package file parsing
  * direct secret generation
  * arbitrary registry/domain/namespace creation
  * final unvalidated YAML generation

* Do not invent:

  * secret values
  * registry addresses
  * domains
  * namespaces
  * resource limits
  * production topology
  * external dependency addresses

* When information cannot be verified from repository artifacts or Deployment Profile, mark it as unknown and generate a user question.

* Include concrete YAML schema examples where helpful.

* Every extracted field must have:

  * value
  * source
  * confidence
  * unresolved status if applicable

---

## 10. Required Pre-Writing Reasoning

Before writing the final document, do the following internally and then include a concise “문제 재정의 및 설계 판단” section at the beginning:

1. Restate the problem you believe you are solving.
2. Identify key design risks.
3. Identify which parts must be deterministic.
4. Identify which parts may use the LLM.
5. Identify why GitHub source alone cannot guarantee application-runnable manifests.
6. Identify how Deployment Profile changes the workflow.
7. Identify how OpenAI-compatible endpoint integration changes the architecture.
8. Propose the document structure.
9. Then write the final document.

---

## 11. Required Final Document Sections

The final Korean document must include the following sections.

# 1. 문제 재정의 및 설계 판단

Include:

* What problem is being solved
* Why direct LLM-based YAML generation is risky
* Why deterministic pre-analysis is required
* Why runtime gaps must be explicitly handled
* Why Deployment Profile is required for application-runnable deployment

# 2. 문서 목적

Explain why a deterministic pre-analysis workflow is needed before Kubernetes manifest generation.

# 3. 전체 설계 원칙

Include principles such as:

* Parser before LLM
* Intermediate model before YAML
* Template rendering before free-form generation
* Validation before delivery
* Ask user instead of guessing
* Confidence scoring for every extracted field
* Deployment Profile before application-runnable guarantee
* LLM provider abstraction before model-specific implementation

# 4. 오픈소스별 벤치마킹 분석

For each project, include:

* What it does
* What to benchmark
* What to adopt
* What not to copy directly
* How it maps to the proposed manifest generation workflow

Cover:

* Kompose
* Move2Kube
* Skaffold
* Azure Draft
* Cloud Native Buildpacks / Paketo

# 5. 테스트 대상 GitHub Repository 세트

Include at least:

* mybatis/jpetstore-6
* fastapi/full-stack-fastapi-template
* GoogleCloudPlatform/microservices-demo
* spring-petclinic/spring-petclinic-microservices
* dotnet/eShop or dotnet-architecture/eShopOnContainers

For each repository, describe:

* Repository type
* Why it is useful
* Expected artifacts
* Expected component detection result
* Expected Kubernetes intent characteristics
* Expected unresolved questions
* What analyzer failures this repository can reveal

# 6. 배포 가능성 수준 정의

Define:

* Level 0. Manifest Generated
* Level 1. Kubernetes-Valid
* Level 2. Pod-Runnable
* Level 3. Application-Runnable

Explain clearly:

* Repository-only mode can target Level 1 and partial Level 2.
* Deployment Profile mode can target Level 2 and Level 3.
* Level 3 requires runtime values and post-deployment validation.

# 7. Runtime Gap 처리 정책

Explain how to handle missing:

* DB connection info
* Secret values
* external API endpoints
* image registry
* namespace
* ingress host
* TLS certificate
* storage class
* resource policies
* production topology

Include environment variable classification policy.

# 8. Deployment Profile 기반 보정 흐름

Include:

* Deployment Profile purpose
* Example schema
* Merge flow between repository analysis and Deployment Profile
* How unresolved questions are reduced
* How Level 3 deployment becomes possible only after Deployment Profile and validation

# 9. 통합 사전 분석 워크플로우

Create a deterministic workflow with these phases:

Step 0. Repository Snapshot
Step 1. Artifact Inventory
Step 2. Existing Deployment Artifact Analysis
Step 3. Component / Service Candidate Detection
Step 4. Language / Framework / Build Method Detection
Step 5. Runtime Information Extraction
Step 6. Port / Env / Volume / Dependency Analysis
Step 7. Application Topology Model Generation
Step 8. Kubernetes Intent Model Generation
Step 9. Unresolved Question Generation
Step 10. Deployment Profile Merge
Step 11. Template-based Manifest Rendering
Step 12. Kubernetes Validation
Step 13. Deployment Check
Step 14. Smoke Test
Step 15. Repair Loop

For each step, describe:

* Purpose
* Input
* Deterministic rules
* Output
* LLM usage allowed or not allowed
* Which success level the step contributes to

# 10. 신뢰도 및 충돌 해결 정책

Define confidence levels:

* high
* medium
* low
* none

Also define priority rules for conflicting data sources, for example:

* existing Kubernetes manifest
* Helm / Kustomize
* Docker Compose
* Dockerfile
* CI/CD workflow
* package files
* application config
* source code scan
* framework convention

# 11. 중간 모델 설계

Define example schemas for:

* repository_snapshot.yaml
* artifact_inventory.yaml
* component_model.yaml
* runtime_model.yaml
* dependency_model.yaml
* kubernetes_intent.yaml
* unresolved_questions.yaml
* deployment-profile.template.yaml
* validation_report.yaml
* deployment-readiness-checklist.md
* smoke-test-plan.yaml

Use concise YAML examples.

# 12. LLM 연동 아키텍처

Include:

* Local On-Premise LLM Runtime option
* OpenAI Endpoint API-Compatible option
* LLM Provider Interface
* Security considerations
* Audit logging
* Request/response schema control
* Deterministic inference settings
* Retry and repair strategy
* How to avoid vendor lock-in

# 13. LLM 역할 제한 정책

Clearly define:

* What the LLM can do
* What the LLM must not do
* What must always be handled by deterministic code
* What must be asked to the user
* How to prevent LLM guessing
* How to handle schema-constrained output

# 14. Manifest 생성 정책

Explain how these resources should be generated from Kubernetes Intent Model and Deployment Profile:

* Deployment
* Service
* Ingress
* ConfigMap
* Secret placeholder
* PVC
* HPA
* ServiceAccount

Do not generate final Kubernetes YAML for a specific app.
Instead, define generation rules and template policies.

# 15. Validation & Repair Loop

Explain the validation process:

* YAML syntax validation
* Kubernetes schema validation
* kubeconform / kubeval
* kubectl dry-run
* kube-linter / kube-score
* policy validation
* Pod Running check
* Pod Ready check
* Smoke test

Explain how LLM can assist only after validator or runtime errors are available.

# 16. 최종 산출물 구조

The final artifact structure must include:

```text
repo-analysis-output/
  00-repository-snapshot.yaml
  01-artifact-inventory.yaml
  02-component-model.yaml
  03-runtime-model.yaml
  04-dependency-model.yaml
  05-kubernetes-intent.yaml
  06-unresolved-questions.yaml
  07-deployment-profile.template.yaml
  08-generated-manifests/
    deployment.yaml
    service.yaml
    ingress.yaml
    configmap.yaml
    secret.placeholder.yaml
    pvc.yaml
    hpa.yaml
    serviceaccount.yaml
  09-validation-report.yaml
  10-deployment-readiness-checklist.md
  11-smoke-test-plan.yaml
  12-repair-suggestions.yaml
```

# 17. MVP 구현 범위

Recommend a practical MVP scope.

Include:

* Inputs to support first
* Languages to support first
* Kubernetes resources to generate first
* Model integration option to support first
* Validation tools to support first
* What to exclude from MVP

The MVP should target:

* Repository-only mode: Level 1 and partial Level 2
* Deployment Profile mode: Level 2
* Level 3 only when runtime values and smoke test endpoints are provided

# 18. 최종 권장 아키텍처

Provide a final architecture diagram in text form, such as:

```text
Repository Scanner
  ↓
Artifact Parser
  ↓
Rule-based Detector
  ↓
Application Topology Model
  ↓
Kubernetes Intent Model
  ↓
Deployment Profile Merge
  ↓
LLM Provider Interface
  ↓
LLM-assisted Question Generator / Repair Advisor
  ↓
Template Renderer
  ↓
Kubernetes Validator
  ↓
Deployment Checker
  ↓
Smoke Test
  ↓
Repair Loop
```

# 19. 결론

Summarize why this approach is more stable than asking an LLM to directly generate manifests.

The conclusion must emphasize:

* Deterministic analysis reduces hallucination.
* Intermediate models make results reproducible.
* Deployment Profile handles runtime gaps.
* Template rendering controls manifest quality.
* Validation and smoke tests define real deployment readiness.
* LLM is useful, but only as a constrained assistant.

---

## 12. Verification Requirements

Before returning the final answer, verify that:

* Every benchmark project is used for a distinct purpose.
* At least five test repositories are included.
* The workflow does not rely on LLM guessing.
* Every generated field has a source or confidence level.
* Uncertain values are routed to unresolved_questions.yaml.
* Runtime environment gaps are handled explicitly.
* Deployment Profile is included.
* Final manifest generation is template-based.
* Validation is included before delivery.
* Pod-running and application-running are distinguished.
* Smoke test planning is included.
* OpenAI-compatible endpoint integration is included as a replaceable provider option.
* OpenAI-compatible endpoint support is not described as requiring OpenAI-hosted models.
* The final document is practical enough for an engineer to implement the analyzer.

---

## 13. Return Format

Return only the final Korean document.

Do not include generic commentary.
Do not include implementation code unless it is schema, configuration, or pseudocode.
Use clear headings, tables, YAML examples, and text-based architecture diagrams.
Make the document practical enough that an engineer could implement the analyzer from it.

