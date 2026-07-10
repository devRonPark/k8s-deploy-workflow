# Source Analysis와 Generation 후보 도구 조사

## 1. 문서 목적

이 문서는 Semantic Agent MVP 전후에 사용할 수 있는 외부 오픈소스 도구를 평가한다. 결론은 도구 통합 자체가 아니라 내부 계약이다.

권장 결론:

- MVP 핵심은 자체 Semantic Task와 Deterministic Verifier 계약이다.
- 처음부터 모든 외부 Tool을 통합하지 않는다.
- Draft는 Candidate Generator 후보이다.
- Kantra/analyzer-lsp는 Source Evidence Provider 후보다.
- Move2Kube는 Reference Implementation과 Comparison Runner로 우선 활용한다.
- Kompose와 JKube는 조건부 Adapter 후보이다.

버전, 릴리스 주기, 유지보수 상태, 지원 언어의 최신성은 공식 repository에서 재확인해야 한다. 이 문서에서 확인하지 않은 항목은 `확인 필요`로 표기한다.

## 2. 평가 기준

| 기준 | 질문 |
|---|---|
| 역할 적합성 | Source Evidence Provider, Candidate Generator, Reference Implementation 중 어디에 속하는가 |
| 입력 | 어떤 artifact나 repository 구조를 요구하는가 |
| 출력 | code location, snippet, Dockerfile 후보, K8s manifest 후보, 비교 report 중 무엇을 내는가 |
| 검증 가능성 | 출력이 evidence reference나 source location으로 검증 가능한가 |
| 격리 가능성 | Python runtime dependency 없이 CLI Adapter로 격리 가능한가 |
| 보안 | Secret 값을 출력하거나 LLM 입력으로 흘릴 위험이 있는가 |
| 재현성 | 같은 commit과 같은 설정에서 같은 결과를 기대할 수 있는가 |
| MVP 필요성 | `resolve_runtime_command`에 직접 필요한가 |

## 3. 코드 분석 Tool과 생성 후보 Tool의 구분

코드 분석 Tool은 후보를 뒷받침하는 source evidence를 제공한다.

```text
search_code
read_source_range
symbol_definition
symbol_references
entrypoint_script_analysis
```

생성 후보 Tool은 Dockerfile, manifest, Helm, Kustomize, image build strategy 같은 후보 산출물을 만든다.

```text
Draft dry-run output
Kompose conversion output
JKube resource output
Move2Kube transform output
Buildpacks detect/build plan
```

생성 후보 Tool의 출력은 정답이 아니다. 내부 Evidence, Rule 후보, SemanticCandidate와 비교할 후보일 뿐이며, 최종 Dockerfile과 Kubernetes YAML은 계속 내부 Intent Model과 Template Renderer가 책임진다.

## 4. Draft

공식 repository 기준으로 Draft는 Kubernetes 시작을 돕는 도구이며, `draft create`가 Dockerfile과 Kubernetes manifest 또는 Helm/Kustomize 관련 파일을 만들 수 있고 dry-run 요약도 제공한다.

가능한 역할:

- 언어 탐지 결과 제공
- Dockerfile 생성 후보 제공
- Kubernetes manifest, Helm, Kustomize 생성 후보 제공
- dry-run 기반 비교 결과 제공

예상 입력:

- application source directory
- template variable 또는 create config
- deployment type 선택값

예상 출력:

- Dockerfile 후보
- manifest/Helm/Kustomize 파일 후보
- dry-run summary
- 지원 언어/필드 정보

프로젝트 내부 Adapter 책임:

- CLI 실행과 timeout 격리
- dry-run 결과만 수집
- 생성 파일을 최종 산출물로 쓰지 않음
- Draft 후보와 기존 Evidence/Rule 후보 비교
- Secret 또는 운영환경 값이 포함되면 redaction

채택 판단:

- MVP 직접 dependency로 채택하지 않는다.
- `Candidate Generator` 후보로 보류한다.
- `resolve_runtime_command`에는 직접 필요하지 않다.

확인 필요:

- 최신 지원 언어 목록
- dry-run JSON schema 안정성
- 유지보수 상태와 릴리스 호환성

## 5. Move2Kube

공식 repository 기준으로 Move2Kube는 source artifact와 환경을 분석해 Kubernetes/OpenShift용 IaC artifact 생성을 돕고, 필요한 경우 사용자에게 guidance를 묻는 command-line tool이다.

가능한 역할:

- Artifact와 Transformer 구조의 설계 참고
- 동일 Repository에 대한 비교 실행
- acceptance test baseline
- 지원 Repository 유형 조사

예상 입력:

- source directory
- 기존 deployment artifact
- 사용자 답변 또는 config

예상 출력:

- plan 또는 transform 결과
- Kubernetes/OpenShift artifact
- 질문/응답 흐름 결과

프로젝트 내부 Adapter 책임:

- 직접 runtime dependency가 아니라 별도 comparison runner로 실행
- 출력 manifest를 내부 Intent Model과 비교 가능한 summary로 정규화
- 질문 항목을 내부 unresolved question 정책과 비교
- tool 실패가 core pipeline 실패로 번지지 않게 격리

채택 판단:

- MVP 핵심 dependency로 채택하지 않는다.
- `Reference Implementation`과 `Comparison Runner`로 우선 활용한다.

확인 필요:

- 현재 transformer coverage
- headless 실행 안정성
- output schema와 버전 호환성

## 6. Kantra / analyzer-lsp

공식 repository 기준으로 `analyzer-lsp`는 Konveyor rule engine에서 LSP 기반 언어 provider를 사용하는 분석 엔진 성격을 가진다.

가능한 역할:

- 소스 코드 위치와 snippet 수집
- 언어별 dependency와 framework usage 탐지
- 사용자 정의 분석 규칙 실행
- 코드 근거 보강

예상 입력:

- source directory
- rule set
- provider 설정

예상 출력:

- rule match
- code location
- dependency/framework usage signal
- provider별 분석 result

프로젝트 내부 Adapter 책임:

- CLI Adapter 또는 격리된 Tool Adapter로 실행
- source range와 evidence reference를 내부 `ToolResult`로 변환
- Secret redaction
- task별 allowlist tool 뒤에 숨김
- Agent가 analyzer-lsp를 직접 자유 호출하지 않게 함

채택 판단:

- `Source Evidence Provider` 후보로 평가한다.
- MVP 첫 구현에는 전체 통합하지 않는다.
- `resolve_runtime_command` 이후 `resolve_component_role`, `resolve_dependency_edge`에서 검토한다.

확인 필요:

- Kantra CLI와 analyzer-lsp의 현재 관계
- language provider별 coverage
- rule output schema 안정성
- on-prem 고객 환경 설치 가능성

## 7. Kompose

공식 repository 기준으로 Kompose는 Compose Specification 파일을 Kubernetes resource로 변환하는 도구다.

가능한 역할:

- Compose가 존재하는 Repository의 Kubernetes 변환 결과 비교
- Compose service, port, volume, env mapping baseline

예상 입력:

- `docker-compose.yml`, `compose.yaml` 등 Compose 파일

예상 출력:

- Kubernetes Deployment, Service, PVC 등 manifest 후보
- 변환 warning

프로젝트 내부 Adapter 책임:

- Kompose 출력을 최종 manifest로 쓰지 않음
- 내부 Compose parser와 Rule 후보가 놓친 mapping을 비교
- warning을 evidence 또는 research report로 정규화
- Compose가 없는 repo에서는 실행하지 않음

채택 판단:

- `compose conversion baseline`으로 조건부 Adapter 후보.
- MVP `resolve_runtime_command`에는 직접 필요하지 않다.

확인 필요:

- 지원 Compose spec 범위
- warning 구조와 exit code 정책
- 최신 Kubernetes resource mapping

## 8. Eclipse JKube

공식 repository 기준으로 Eclipse JKube는 Java application을 대상으로 Docker, JIB, S2I build strategy를 사용해 image를 만들고 Kubernetes/OpenShift manifest를 생성/배포하는 Maven/Gradle plugin collection이다.

가능한 역할:

- Maven 또는 Gradle 기반 Java Repository의 image 및 Kubernetes 산출물 후보 생성
- Java-specific runtime/build/deployment candidate generator

예상 입력:

- Maven 또는 Gradle Java project
- plugin 설정
- build environment

예상 출력:

- image build 후보
- Kubernetes/OpenShift manifest 후보
- plugin execution report

프로젝트 내부 Adapter 책임:

- Java repo에만 조건부 실행
- build 실행이 필요한 경우 MVP에서는 실행하지 않고 dry-run 또는 resource generation 가능성만 조사
- output manifest를 내부 Intent Model과 비교
- final manifest로 직접 채택하지 않음

채택 판단:

- `language-specific candidate generator` 후보.
- MVP에서는 보류한다.

확인 필요:

- dry-run 또는 resource-only generation 방식
- Maven/Gradle plugin 실행의 side effect
- 최신 Java framework coverage

## 9. Buildpacks

Cloud Native Buildpacks는 source에서 image build 전략을 제공하는 생태계다. 공식 spec은 Buildpack, Distribution, Platform API 등을 정의한다.

가능한 역할:

- Dockerfile 생성이 어려운 경우의 별도 image build strategy 후보
- buildpack detect 결과를 language/framework/build strategy signal로 참고

오해하면 안 되는 점:

- Buildpacks는 Dockerfile 생성 도구가 아니다.
- Kubernetes manifest 생성 도구도 아니다.
- Intent Model에서는 `build_strategy: buildpacks` 후보로 표현해야 한다.

예상 입력:

- source directory
- builder image 또는 platform 설정

예상 출력:

- detect/build plan
- OCI image. 실제 build는 MVP 범위 밖

채택 판단:

- MVP에서는 직접 실행하지 않는다.
- Dockerfile이 없고 build strategy 후보가 필요한 단계에서 보류 후보로 둔다.

확인 필요:

- 고객 환경의 builder image 사용 가능성
- offline/on-prem registry 요건
- detect 결과를 기계적으로 읽는 방법

## 10. tree-sitter, ast-grep, ripgrep, LSP

### ripgrep

역할:

- 빠른 코드 문자열 검색
- `search_code` tool의 초기 구현 후보

장점:

- 설치가 간단하고 빠르다.
- 언어별 parser 없이도 entrypoint script, package script, port literal 검색에 충분하다.

한계:

- 문자열 matching이므로 symbol resolution이나 data flow를 제공하지 않는다.

### tree-sitter

역할:

- 언어별 syntax tree 기반 source range와 구조 검색
- 향후 `read_source_range`, `find_command_target` 보강

장점:

- syntax error가 있어도 어느 정도 tree를 만들 수 있다.
- runtime library embed 가능성이 있다.

한계:

- 언어별 grammar 관리가 필요하다.
- Python dependency로 직접 채택할지 CLI/별도 adapter로 둘지는 `확인 필요`다.

### ast-grep

역할:

- AST 구조 기반 code search
- language-specific pattern rule 실행

장점:

- 단순 grep보다 구조적이다.
- CLI adapter로 격리하기 쉽다.

한계:

- 지원 언어와 rule syntax 안정성은 `확인 필요`다.

### LSP

역할:

- symbol definition/reference
- call hierarchy 또는 type-aware navigation

장점:

- 동적 import가 아닌 일반 symbol 추적에는 강하다.

한계:

- language server 설치와 indexing 비용이 크다.
- on-prem 고객 환경에서 언어별 server 설치 가능성이 `확인 필요`다.
- MVP 첫 구현에는 과하다.

## 11. MVP 도입과 보류

MVP에 도입:

- 자체 Semantic Task 모델
- 자체 Deterministic Verifier
- `search_code`
- `read_source_range`
- `inspect_entrypoint_script`
- `find_command_target`
- 필요 시 ripgrep 기반 검색. 실제 binary dependency 정책은 `확인 필요`

MVP에서 보류:

- Draft runtime 통합
- Move2Kube runtime 통합
- Kantra/analyzer-lsp 전체 통합
- Kompose adapter
- JKube adapter
- Buildpacks 실행
- 범용 LSP
- 전체 call graph
- 복잡한 data flow

## 12. 참고 출처

- Draft: https://github.com/Azure/draft
- Move2Kube: https://github.com/konveyor/move2kube
- Kantra/analyzer-lsp: https://github.com/konveyor/analyzer-lsp
- Kompose: https://github.com/kubernetes/kompose
- Eclipse JKube: https://github.com/eclipse/jkube
- Cloud Native Buildpacks spec: https://github.com/buildpacks/spec
- tree-sitter: https://github.com/tree-sitter/tree-sitter
- ast-grep: https://github.com/ast-grep/ast-grep
