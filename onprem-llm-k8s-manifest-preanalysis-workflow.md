# On-Premise LLM 기반 Kubernetes Manifest 생성을 위한 결정론적 사전 분석 워크플로우

> 임의의 GitHub Repository를 분석하여 Kubernetes manifest를 생성하기 위한 사전 분석(pre-analysis) 워크플로우 설계 문서.
> On-Premise LLM 또는 OpenAI-compatible endpoint 연동을 전제로 하며, LLM의 추측이 아닌 결정론적 파싱과 중간 모델을 중심으로 설계한다.

---

# 1. 문제 재정의 및 설계 판단

## 1.1 해결하려는 문제

이 문서가 해결하려는 문제는 다음과 같이 재정의할 수 있다.

> "임의의 GitHub Repository가 주어졌을 때, 그 애플리케이션을 Kubernetes에서 실제로 구동 가능하게 만드는 manifest를 생성하되, **Repository에 존재하지 않는 정보를 LLM이 지어내지 않도록** 분석 파이프라인을 설계하는 것."

핵심은 두 가지다.

1. **입력의 불완전성**: GitHub Repository는 애플리케이션의 *소스*는 담고 있지만, *운영 환경 값*은 담고 있지 않은 경우가 대부분이다. DB 접속 정보, credential, 외부 API endpoint, image registry 주소, Ingress host, StorageClass, TLS Secret, 운영 리소스 정책 등은 Repository 밖에 존재한다.
2. **LLM의 비결정성**: LLM에게 Repository 원문을 던져 "Kubernetes YAML을 만들어줘"라고 요청하면, 존재하지 않는 값을 그럴듯하게 지어낸다(hallucination). 같은 입력에 대해 다른 출력이 나오며, 결과를 재현하거나 검증하기 어렵다.

## 1.2 핵심 설계 판단

이 문서 전체를 관통하는 설계 원칙은 다음 한 문장이다.

> **"LLM은 Repository 원문에서 Kubernetes YAML을 직접 추측해서는 안 된다. Repository artifact는 먼저 결정론적으로 파싱되어 중간 모델(intermediate model)이 되어야 하며, 누락된 runtime 값은 질문(unresolved question), placeholder, 또는 Deployment Profile 필드로 라우팅되어야 한다."**

이를 기준으로 사전에 내린 설계 판단은 다음과 같다.

| 판단 항목 | 결론 |
|---|---|
| 파일 존재 탐지, Dockerfile/Compose/package 파일 파싱 | **결정론적 코드**가 수행. LLM 사용 금지 |
| 언어/프레임워크/빌드 방식 탐지 | **규칙 기반(rule-based) detector**가 수행 |
| Kubernetes YAML 생성 | **템플릿 렌더링**으로 수행. LLM free-form 생성 금지 |
| 분석 요약, 충돌 설명, 질문 문안 생성, validation 오류 수리 제안 | **LLM 허용** (schema-constrained output) |
| 누락된 runtime 값 | 추측 금지. **unresolved_questions.yaml + Deployment Profile**로 라우팅 |
| 모델 백엔드 | **LLM Provider Interface**로 추상화. Local runtime / OpenAI-compatible endpoint 교체 가능 |

## 1.3 주요 설계 리스크

| 리스크 | 내용 | 대응 |
|---|---|---|
| Hallucination | LLM이 registry 주소, 도메인, Secret 값을 지어냄 | LLM에 원문 대신 정규화된 중간 모델만 전달, 생성은 템플릿으로 제한 |
| 비재현성 | 같은 Repo에 대해 매번 다른 manifest가 생성됨 | 결정론적 파서 + temperature 0 + schema-constrained output |
| 거짓 성공 | "YAML이 생성됨"을 "배포 가능함"으로 오인 | 배포 가능성 수준(Level 0~3)을 명시적으로 정의하고 산출물에 표기 |
| Runtime gap 은폐 | 누락 값이 기본값으로 조용히 채워짐 | 모든 추출 필드에 source/confidence 부여, 누락은 unresolved로 명시 |
| Secret 유출 | Repository 내 credential이 LLM으로 전송됨 | Secret 후보는 마스킹 후 이름/출처만 전달, 값은 전달 금지 |
| 벤더 종속 | 특정 모델 API에 파이프라인이 결합됨 | Provider Interface 분리, OpenAI-compatible 계약으로 표준화 |

## 1.4 결정론 영역과 LLM 허용 영역의 구분

```text
[결정론적 영역 — 반드시 코드로 처리]
  파일 스캔 / artifact 탐지 / Dockerfile·Compose·Helm·Kustomize 파싱
  언어·프레임워크·빌드 방식 규칙 기반 탐지
  포트·환경변수·볼륨·의존성 추출
  중간 모델 생성 / 템플릿 렌더링 / validation

[LLM 허용 영역 — schema-constrained 보조 역할]
  분석 결과 요약문 생성
  소스 간 충돌에 대한 설명문 생성
  unresolved question의 사용자向 문안 생성
  validator/runtime 오류에 대한 수리(patch) 제안
  사용자向 문서(checklist, README) 문안 생성
```

## 1.5 GitHub 소스만으로 Application-Runnable을 보장할 수 없는 이유

GitHub Repository는 "코드가 무엇을 필요로 하는지"는 말해주지만 "그 필요를 어느 환경의 어떤 값으로 채울지"는 말해주지 않는다.

- `application.yml`에 `${DB_HOST}`가 있다는 사실은 알 수 있으나, 실제 DB host 값은 알 수 없다.
- Dockerfile로 이미지를 빌드할 수 있다는 것은 알 수 있으나, 어느 registry에 push할지는 알 수 없다.
- Ingress가 필요하다는 것은 추론할 수 있으나, host 도메인과 TLS Secret 이름은 대상 클러스터 소유자만 안다.
- replica 수, resource requests/limits, StorageClass는 코드가 아니라 **운영 정책**의 영역이다.

따라서 Repository-only 분석의 정직한 목표는 "Kubernetes가 이해할 수 있는 manifest + 무엇이 비어 있는지에 대한 완전한 목록"이며, 실제 구동(Application-Runnable)은 Deployment Profile로 값이 공급되고 배포 후 검증이 통과한 뒤에만 선언할 수 있다.

## 1.6 Deployment Profile이 워크플로우를 바꾸는 방식

Deployment Profile은 "Repository에 없는 환경별 값"을 담는 입력 파일이다. 이것이 도입되면:

- unresolved question의 다수가 Profile 필드 값으로 **해소**된다.
- Kubernetes Intent Model이 **재생성**되어 placeholder가 실제 참조(Secret ref, ConfigMap 값)로 치환된다.
- 목표 수준이 Level 1(문법적 유효)에서 Level 2~3(Pod 구동, 애플리케이션 구동)으로 상향된다.
- 배포 후 검증(Pod Ready, smoke test)이 파이프라인의 정식 단계가 된다.

## 1.7 OpenAI-compatible endpoint 연동이 아키텍처를 바꾸는 방식

OpenAI-compatible endpoint(Chat Completions API 호환)를 연동 계약으로 채택하면:

- 분석 파이프라인은 `base_url`, `api_key`, `model`만 아는 **LLM Provider Interface** 뒤의 무엇이든 사용할 수 있다 — vLLM, TGI, llama.cpp server, Ollama-compatible gateway, LiteLLM proxy, 사내 LLM gateway 등.
- 모델 교체가 분석 파이프라인 변경 없이 설정 변경만으로 가능해진다.
- 단, 호환 endpoint 지원이 "OpenAI 호스팅 모델을 써야 한다"는 뜻이 아님을 명확히 해야 한다. On-Premise 모델 서버가 호환 API를 노출하는 구성이 1차 대상이다.

## 1.8 문서 구조

본 문서는 다음 순서로 구성된다: 설계 원칙(3장) → 벤치마킹(4장) → 테스트 Repository 세트(5장) → 배포 가능성 수준(6장) → Runtime Gap 정책(7장) → Deployment Profile(8장) → 16단계 통합 워크플로우(9장) → 신뢰도/충돌 정책(10장) → 중간 모델 스키마(11장) → LLM 연동 아키텍처(12장) → LLM 역할 제한(13장) → Manifest 생성 정책(14장) → Validation & Repair Loop(15장) → 산출물 구조(16장) → MVP 범위(17장) → 최종 아키텍처(18장) → 결론(19장).

---

# 2. 문서 목적

본 문서의 목적은 **Kubernetes manifest 생성 이전에 수행되어야 하는 결정론적 사전 분석 워크플로우**를 엔지니어가 구현 가능한 수준으로 정의하는 것이다.

manifest 생성을 LLM 프롬프트 한 번으로 처리하는 접근은 데모에서는 동작하는 것처럼 보이지만, 실제로는 다음 문제를 만든다.

1. **검증 불가능성**: 생성된 YAML의 각 필드가 어디에서 왔는지(source) 추적할 수 없다. `image: myapp:latest`가 Dockerfile에서 온 것인지 모델이 지어낸 것인지 구분되지 않는다.
2. **비재현성**: 같은 Repository에 대해 실행할 때마다 다른 결과가 나온다. 회귀 테스트가 불가능하다.
3. **거짓 완성도**: 누락된 DB host, registry 주소를 모델이 그럴듯한 값(`db.example.com`, `myregistry.io`)으로 채워, "생성 성공"이 "배포 실패"를 숨긴다.
4. **보안 리스크**: Repository 원문 전체(그 안의 `.env`, credential 포함)가 모델로 전송된다.

사전 분석 워크플로우는 이 문제를 다음과 같이 해소한다.

- Repository artifact를 **결정론적 파서**가 처리하여 **중간 모델**(component model, runtime model, dependency model, Kubernetes Intent Model)을 만든다.
- 모든 추출 필드는 `value / source / confidence / unresolved 여부`를 갖는다.
- 알 수 없는 값은 **unresolved_questions.yaml**로 라우팅되고, 환경별 값은 **Deployment Profile**로 공급받는다.
- 최종 YAML은 **템플릿 렌더링**으로 생성되고, **validator**(kubeconform, kubectl dry-run 등)를 통과한 뒤에만 전달된다.
- LLM은 요약·설명·질문 생성·수리 제안이라는 제한된 역할만 수행한다.

이 문서의 독자는 Kubernetes 엔지니어, 플랫폼 엔지니어, AI agent 워크플로우 설계자, DevOps 엔지니어, 기술영업/솔루션 아키텍트, 그리고 On-Premise AI 기반 Kubernetes 전환·배포 어시스턴트를 평가하는 엔터프라이즈 고객이다.

---

# 3. 전체 설계 원칙

| # | 원칙 | 의미 |
|---|---|---|
| P1 | **Parser before LLM** | 모든 artifact(Dockerfile, docker-compose.yml, package 파일, Helm, Kustomize, 기존 manifest)는 LLM이 아닌 결정론적 parser가 먼저 처리한다. LLM은 parser의 출력(중간 모델)만 본다. |
| P2 | **Intermediate model before YAML** | Repository → YAML 직행을 금지한다. 반드시 repository_snapshot → artifact_inventory → component_model → runtime_model → kubernetes_intent의 중간 모델 체인을 거친다. |
| P3 | **Template rendering before free-form generation** | 최종 manifest는 검증된 템플릿에 Intent Model 값을 주입하여 렌더링한다. LLM의 자유 생성 YAML은 산출물이 될 수 없다. |
| P4 | **Validation before delivery** | 렌더링된 manifest는 YAML 문법 → Kubernetes schema(kubeconform) → dry-run → linter(kube-linter/kube-score) 검증을 통과한 뒤에만 사용자에게 전달된다. |
| P5 | **Ask user instead of guessing** | Repository와 Deployment Profile 어디서도 확인할 수 없는 값은 `unknown`으로 표기하고 사용자 질문을 생성한다. 기본값으로 조용히 채우지 않는다. |
| P6 | **Confidence scoring for every extracted field** | 모든 추출 필드는 `value / source / confidence(high·medium·low·none)`를 갖는다. confidence가 낮은 필드는 사용자 확인 대상이 된다. |
| P7 | **Deployment Profile before application-runnable guarantee** | Application-Runnable(Level 3)은 Deployment Profile로 runtime 값이 공급되고 배포 후 검증이 통과한 뒤에만 선언한다. Repository-only 모드에서 Level 3을 약속하지 않는다. |
| P8 | **LLM provider abstraction before model-specific implementation** | 분석 파이프라인은 LLM Provider Interface에만 의존한다. Local runtime이든 OpenAI-compatible endpoint든 설정으로 교체 가능해야 한다. |
| P9 | **Secrets never flow to the model** | Secret 후보의 값은 LLM에 전달하지 않는다. 이름·출처·분류 근거만 전달한다. |
| P10 | **Every output is reproducible** | 동일한 Repository commit + 동일한 Deployment Profile + 동일한 규칙 버전은 동일한 manifest를 생성해야 한다. |

---

# 4. 오픈소스별 벤치마킹 분석

각 프로젝트는 서로 다른 목적으로 벤치마킹한다. 요약이 아니라 "무엇을 가져오고, 무엇을 가져오지 않으며, 본 워크플로우의 어느 단계에 매핑되는가"를 기준으로 분석한다.

## 4.1 Kompose — 결정론적 Compose→Kubernetes 매핑 규칙

**무엇을 하는가**: `docker-compose.yml`을 Kubernetes 리소스(Deployment, Service, PVC 등)로 변환하는 CLI 도구.

**벤치마킹 포인트**
- Compose service → Deployment + Service 변환이 **완전히 결정론적 규칙**으로 정의되어 있다. 같은 입력은 항상 같은 출력을 낸다.
- `ports` → Service port 매핑, `volumes` → PVC 후보, `environment` → 컨테이너 env, `depends_on` → 의존 관계 힌트라는 명확한 필드 단위 매핑 테이블이 존재한다.
- 변환 불가능한 필드(예: `build` 컨텍스트, host 네트워크)를 경고로 명시한다 — "조용히 버리지 않는다".

**채택할 것**
- 본 워크플로우 Step 6(Port/Env/Volume/Dependency 분석)과 Step 8(Intent Model 생성)의 Compose 매핑 규칙표를 Kompose의 변환 규칙을 기준으로 작성한다.
  - Compose service → component (Deployment 후보 + Service 후보)
  - Compose named volume → PVC 후보 (StorageClass는 unresolved)
  - Compose environment → ConfigMap/Secret 후보 분류 입력
  - Compose `depends_on` → dependency_model의 내부 의존성 엣지

**직접 복사하지 않을 것**
- Kompose는 변환 결과를 **즉시 최종 YAML**로 낸다. 본 워크플로우는 Compose 분석 결과를 중간 모델에 먼저 적재하고, Deployment Profile 병합 후에 렌더링한다.
- Kompose는 누락 값을 질문으로 라우팅하지 않는다(예: 빌드 이미지의 registry). 이 gap 처리는 본 워크플로우가 추가하는 부분이다.

**워크플로우 매핑**: Step 2(기존 배포 artifact 분석)와 Step 6의 Compose parser 규칙 정의에 사용.

## 4.2 Move2Kube — Collect→Analyze→Plan→Transform→Validate 아키텍처

**무엇을 하는가**: 다양한 소스 artifact(Compose, Cloud Foundry, 소스코드)를 분석해 Kubernetes YAML, Helm chart 등으로 변환하는 IBM 오픈소스. 본 워크플로우의 **가장 강력한 아키텍처 참조**다.

**벤치마킹 포인트**
- **Planning model**: 변환을 즉시 수행하지 않고, 먼저 "무엇을 어떻게 변환할지"의 계획(plan) 파일을 생성한 뒤 사용자가 검토·수정하게 한다. 이는 본 워크플로우의 중간 모델(component_model, kubernetes_intent) 개념과 정확히 대응한다.
- **QA 엔진(사용자 질문 생성)**: 변환 중 결정 불가능한 항목(registry, ingress host 등)을 사용자 질문으로 라우팅한다. 본 워크플로우의 unresolved_questions.yaml의 원형이다.
- **Transformer 파이프라인**: 분석기와 변환기가 플러그인으로 분리되어 있어, 언어/프레임워크별 detector를 독립적으로 추가할 수 있다.
- **다중 출력 형식**: 같은 중간 표현에서 Kubernetes YAML, Helm chart 등 복수 형식을 렌더링한다 — 중간 모델과 렌더러 분리의 근거.

**채택할 것**
- Collect → Analyze → Plan → Transform → Validate 단계 구조를 본 워크플로우의 Step 0~15의 골격으로 사용.
- plan 파일 = 본 워크플로우의 kubernetes_intent.yaml (사용자 검토 가능한 중간 산출물).
- QA 엔진의 "질문에는 기본값·선택지·이유가 함께 있어야 한다"는 질문 스키마 설계.

**직접 복사하지 않을 것**
- Move2Kube의 대화형 CLI QA 흐름을 그대로 복사하지 않는다. 본 워크플로우는 질문을 **파일(unresolved_questions.yaml)과 Deployment Profile 템플릿**으로 산출하여 비대화형·자동화 파이프라인에서도 동작하게 한다.
- Move2Kube의 방대한 transformer 전체를 이식하지 않는다. MVP 범위(17장)의 언어·입력만 우선 구현한다.

**워크플로우 매핑**: 전체 파이프라인 구조(Step 0~15), Step 9(질문 생성), 중간 모델 설계(11장).

## 4.3 Skaffold — 빌드/배포 관심사 분리와 멀티 컴포넌트 처리

**무엇을 하는가**: 컨테이너 빌드→푸시→manifest 렌더→배포의 개발 루프를 자동화하는 Google 오픈소스.

**벤치마킹 포인트**
- **artifact 개념 분리**: Skaffold는 `build.artifacts`(무엇을 이미지로 빌드할지)와 `manifests`(무엇을 배포할지), `deploy`(어떻게 배포할지)를 설정에서 명확히 분리한다.
- **artifact detection**: `skaffold init`은 Repository에서 Dockerfile, Jib, Buildpacks 대상 등을 탐지해 빌드 대상 후보를 제안한다.
- **멀티 컴포넌트 Repository 처리**: 하나의 repo에서 여러 이미지 빌드 대상과 여러 manifest를 다룬다.
- **render와 deploy의 분리**: `skaffold render`는 배포 없이 최종 manifest만 산출한다.

**채택할 것**
- 본 워크플로우의 산출물 구분: **빌드 artifact(이미지 빌드 대상) / 컨테이너 이미지(registry 좌표) / 배포 manifest / 개발용 워크플로우 / 배포용 워크플로우**를 서로 다른 모델 필드로 분리.
- component_model에 `build`(dockerfile 경로, 빌드 방식)와 `deploy`(Intent Model 참조)를 별도 섹션으로 두는 설계.
- "render는 결정론, deploy는 환경 의존"이라는 단계 분리 — Step 11(렌더링)까지는 클러스터 없이 수행 가능, Step 13(Deployment Check)부터 클러스터가 필요.

**직접 복사하지 않을 것**
- Skaffold의 파일 감시 기반 개발 루프(hot reload)는 본 워크플로우 범위 밖이다.
- skaffold.yaml 형식 자체를 중간 모델로 쓰지 않는다(빌드 중심 스키마라 runtime gap 표현이 없음).

**워크플로우 매핑**: Step 3(컴포넌트 탐지), Step 8(Intent Model의 build/image 필드), Step 11(render)과 Step 13(deploy)의 분리.

## 4.4 Azure Draft — "추측 대신 질문" 패턴과 템플릿 기반 생성

**무엇을 하는가**: 애플리케이션 소스에서 언어를 탐지하고, 몇 가지 질문(포트, 앱 이름 등)에 대한 답을 받아 Dockerfile과 Kubernetes manifest를 **템플릿 기반**으로 생성하는 Microsoft 도구.

**벤치마킹 포인트**
- **자동 탐지 + 명시적 질문의 조합**: 언어는 파일 지표로 자동 탐지하되, 탐지할 수 없는 값(포트 등)은 사용자에게 **묻는다**. 모델이 추측하지 않는다.
- **템플릿 기반 생성**: 생성물은 언어별 검증된 템플릿에 변수를 주입한 결과다. 생성 품질이 템플릿 품질로 통제된다.
- 질문 항목이 적고 명확하다 — 질문 피로(question fatigue)를 관리한다.

**채택할 것**
- Step 9(질문 생성)의 원칙: "탐지 불가 항목은 질문으로", 질문에는 형식·기본 후보·이유를 포함.
- Step 11(렌더링)의 템플릿 정책: 리소스 종류별 템플릿 + 변수 주입 + 템플릿 버전 관리.
- 질문 수 최소화 정책: confidence가 high인 값은 질문하지 않고 확인 목록에만 표기.

**직접 복사하지 않을 것**
- Draft의 템플릿은 단일 컴포넌트·단순 웹앱 중심이다. 멀티 컴포넌트 topology, 의존성 그래프, Deployment Profile 병합은 본 워크플로우가 확장하는 영역이다.
- Draft는 confidence/source 추적이 없다. 본 워크플로우는 모든 필드에 이를 요구한다.

**워크플로우 매핑**: Step 9(unresolved question 설계), Step 11(템플릿 렌더링 정책, 14장).

## 4.5 Cloud Native Buildpacks / Paketo — 파일 지표 기반 detect 단계와 build plan

**무엇을 하는가**: 소스 코드에서 언어·프레임워크를 탐지(detect)하고 Dockerfile 없이 OCI 이미지를 빌드하는 표준(CNB)과 그 구현(Paketo).

**벤치마킹 포인트**
- **Detect phase**: 각 buildpack이 파일 지표(`pom.xml`, `package.json`, `go.mod`, `requirements.txt` 등)로 "내가 이 소스를 처리할 수 있는가"를 검사한다. 완전히 규칙 기반이며 LLM이 없다.
- **Build plan**: detect 결과가 "무엇이 필요하고 무엇을 제공하는가"의 계약(provides/requires)으로 표현된다. 본 워크플로우의 중간 모델 사상과 동일하다.
- 언어 → 프레임워크 → 런타임 버전 → 빌드 방법의 **계층적 탐지**.

**채택할 것**
- Step 4(언어/프레임워크/빌드 방식 탐지)의 규칙 테이블을 buildpack detect 규칙 스타일로 설계:

```text
탐지 규칙 예시 (우선순위 순 평가)
  pom.xml 존재                    → language: java, build: maven      (confidence: high)
  build.gradle(.kts) 존재         → language: java|kotlin, build: gradle (high)
  package.json 존재               → language: nodejs                  (high)
  package.json.dependencies.next → framework: nextjs                 (high)
  go.mod 존재                     → language: go                      (high)
  requirements.txt|pyproject.toml → language: python                  (high)
  pyproject.toml에 fastapi 의존    → framework: fastapi                (high)
  *.csproj|*.sln 존재             → language: dotnet                  (high)
  src/main/resources/application.yml → framework: spring-boot 후보    (medium)
```

- Dockerfile이 없는 컴포넌트의 빌드 전략으로 "Buildpacks 빌드"를 Intent Model의 빌드 옵션 중 하나로 채택(Dockerfile 생성 대신 buildpack 빌드를 제안 가능).

**직접 복사하지 않을 것**
- CNB의 이미지 빌드 lifecycle(빌더 이미지, 레이어 재사용) 자체는 본 워크플로우 범위 밖이다. 본 워크플로우는 detect 사상만 가져온다.

**워크플로우 매핑**: Step 4(규칙 기반 탐지), Step 5(런타임 정보 추출)의 프레임워크 관례(convention) 데이터베이스.

## 4.6 벤치마킹 종합

| 프로젝트 | 가져오는 핵심 | 매핑되는 단계 |
|---|---|---|
| Kompose | Compose→K8s 결정론적 필드 매핑 규칙 | Step 2, 6, 8 |
| Move2Kube | Collect→Analyze→Plan→Transform→Validate 골격, plan 파일, QA 엔진 | 전체 구조, Step 9, 11장 |
| Skaffold | 빌드 artifact / 이미지 / manifest / 워크플로우 분리, 멀티 컴포넌트 | Step 3, 8, 11↔13 분리 |
| Azure Draft | 추측 대신 질문, 템플릿 기반 생성 | Step 9, 11, 14장 |
| Buildpacks/Paketo | 파일 지표 기반 detect, build plan 계약 | Step 4, 5 |

---

# 5. 테스트 대상 GitHub Repository 세트

분석기(analyzer)의 회귀 테스트를 위한 벤치마크 Repository 세트다. 각 Repository는 서로 다른 분석기 실패 모드(failure mode)를 드러내도록 선정했다.

## 5.1 mybatis/jpetstore-6 — 단일 Java 웹 애플리케이션

- **Repository 유형**: 단일 Maven 기반 Java 웹 애플리케이션(MyBatis + Spring, WAR 배포형).
- **선정 이유**: "컨테이너화 힌트가 거의 없는 전통적 Java 앱"의 대표. Dockerfile 유무 처리, 포트 불확실성 처리, Maven 빌드 추론을 검증하기에 적합하다.
- **탐지되어야 할 artifact**: `pom.xml`, `src/main/webapp`, MyBatis mapper 설정, DB 스키마 스크립트, (버전에 따라) Dockerfile 유무.
- **기대 component model**: 단일 컴포넌트. `language: java`, `build: maven`, packaging(war/jar) 탐지, 빌드 커맨드 `mvn clean package` 추론(source: pom.xml, confidence: high).
- **기대 Kubernetes Intent 특성**: Deployment 1개 + Service 1개 후보. containerPort는 **unresolved**(WAR 앱은 서블릿 컨테이너 포트에 의존 — 추측 금지, 질문 또는 낮은 confidence의 관례값 8080 제시). DB를 내장 HSQLDB로 쓰는 기본 구성과 외부 DB 구성의 분기 질문.
- **기대 unresolved questions**: 런타임 포트, 서블릿 컨테이너 선택(Tomcat 이미지 등), 외부 DB 사용 여부와 접속 정보, image registry, namespace, Ingress 필요 여부.
- **검증 항목**: 분석기가 DB 접속 값·포트를 **지어내지 않는지**, Maven multi-module이 아님을 정확히 판정하는지.
- **드러내는 실패 모드**: (a) Dockerfile 부재 시 빌드 전략 미제시, (b) 관례 포트를 high confidence로 오표기, (c) 내장 DB를 외부 의존성으로 오탐.

## 5.2 fastapi/full-stack-fastapi-template — 모던 풀스택 모노레포

- **Repository 유형**: FastAPI backend + React frontend + PostgreSQL + Traefik reverse proxy를 Docker Compose로 묶은 모노레포 템플릿.
- **선정 이유**: Compose 분석, backend/frontend 분리, Traefik 라벨 해석, 환경변수의 ConfigMap/Secret 분류, CI/CD 파일 탐지를 한 번에 검증할 수 있다.
- **탐지되어야 할 artifact**: `docker-compose.yml`(+override), backend/frontend 각각의 Dockerfile, `pyproject.toml`, `package.json`, `.env` 템플릿, GitHub Actions workflow, Traefik 라벨.
- **기대 component model**: 최소 3개 컴포넌트 — backend API(FastAPI), frontend(React/Vite), database(PostgreSQL: Compose service → 외부화 여부 질문 대상). Traefik은 "Ingress 의도"로 변환하되 Traefik 자체를 컴포넌트로 복제하지 않는다.
- **기대 Kubernetes Intent 특성**: backend/frontend 각각 Deployment+Service, DB는 `mode: external|in-cluster` 분기 질문, Compose environment → ConfigMap 후보와 Secret 후보(`POSTGRES_PASSWORD`, `SECRET_KEY` 등) 분리, Traefik 라벨 → Ingress 후보(host는 unresolved).
- **기대 unresolved questions**: Ingress host/class, TLS 여부, DB 외부화 여부, Secret 실제 값 공급 방식, frontend의 API base URL 주입 방식.
- **검증 항목**: Compose `depends_on` → dependency_model 엣지 생성, `.env` 값이 Secret 후보로 분류되되 값 자체는 마스킹되는지.
- **드러내는 실패 모드**: (a) Traefik을 배포 대상 컴포넌트로 오탐, (b) DB 컨테이너를 무조건 StatefulSet으로 생성(질문 없이), (c) `.env`의 개발용 기본 비밀번호를 확정 값으로 승격.

## 5.3 GoogleCloudPlatform/microservices-demo — Kubernetes 네이티브 마이크로서비스

- **Repository 유형**: 10여 개 다언어(Go, Java, Python, Node.js, C#) 마이크로서비스 + **기존 Kubernetes manifest 완비**(kubernetes-manifests/, Helm, Kustomize 변형 포함).
- **선정 이유**: "기존 manifest가 있는 Repository"의 대표. 기존 리소스 인벤토리 구축, manifest에서 역방향으로 Intent Model 도출, 소스 분석 결과와의 대조를 검증한다.
- **탐지되어야 할 artifact**: 기존 Deployment/Service YAML 전체, 각 서비스 디렉터리의 Dockerfile, 언어별 package 파일, gRPC 서비스 간 의존(환경변수 `*_SERVICE_ADDR` 패턴).
- **기대 component model**: 10+개 컴포넌트, 언어 혼합. 각 컴포넌트의 이미지·포트·env는 **기존 manifest에서 high confidence로 추출**.
- **기대 Kubernetes Intent 특성**: 기존 manifest 인벤토리가 Intent Model의 1차 소스(우선순위 최상). unresolved question이 소스-only Repository 대비 **현저히 적어야 한다**(namespace, registry 재지정 정도).
- **기대 unresolved questions**: 대상 클러스터 namespace, 이미지 registry 재태깅 여부, LoadBalancer→Ingress 전환 여부 정도.
- **검증 항목**: 소스 우선순위 규칙(기존 manifest > Dockerfile > 소스 스캔)이 작동하는지, 생성된 Intent Model과 기존 manifest의 diff가 최소인지.
- **드러내는 실패 모드**: (a) 기존 manifest를 무시하고 소스에서 재추론하여 정보 손실, (b) 서비스 간 의존(gRPC 주소 env)을 외부 의존성으로 오분류, (c) 다언어 컴포넌트 수 폭증 시 성능/모델 크기 문제.

## 5.4 spring-petclinic/spring-petclinic-microservices — Spring Cloud 마이크로서비스

- **Repository 유형**: Maven multi-module의 Spring Boot/Spring Cloud 마이크로서비스(api-gateway, config-server, discovery-server, 도메인 서비스들, Docker Compose 동봉).
- **선정 이유**: Maven multi-module 분해, Spring 특유의 패턴(Config Server, Eureka discovery, Gateway) 탐지, 외부화된 설정(externalized configuration)의 질문 라우팅을 검증한다.
- **탐지되어야 할 artifact**: 루트 `pom.xml`과 모듈별 `pom.xml`, 각 모듈의 `application.yml`, `docker-compose.yml`, Spring Cloud 의존성(`spring-cloud-starter-netflix-eureka-client` 등).
- **기대 component model**: 모듈별 컴포넌트(7±개). 각 컴포넌트에 Spring Boot 포트 후보(`server.port`, source: application.yml, confidence: high/medium), config-server/discovery-server는 **인프라 패턴 컴포넌트**로 태깅.
- **기대 Kubernetes Intent 특성**: 내부 의존성 그래프(서비스→discovery→config), gateway가 진입점(Service/Ingress 후보). "Kubernetes 전환 시 Eureka를 유지할지 Kubernetes Service discovery로 대체할지"는 **아키텍처 결정 질문**으로 라우팅(분석기가 임의 결정 금지).
- **기대 unresolved questions**: config-server의 Git backend 주소, discovery 패턴 유지 여부, DB(모듈별 MySQL) 외부화, registry/namespace/ingress host.
- **검증 항목**: multi-module 경계가 컴포넌트 경계로 정확히 매핑되는지, Compose와 소스 분석 결과의 교차 검증(포트 충돌 시 우선순위 규칙 적용).
- **드러내는 실패 모드**: (a) 루트 pom만 보고 단일 컴포넌트로 오판, (b) Eureka/Config Server를 일반 웹앱으로 오분류, (c) Spring 관례 포트 8080을 모든 모듈에 무조건 부여.

## 5.5 dotnet/eShop — .NET 마이크로서비스 (참조: dotnet-architecture/eShopOnContainers)

- **Repository 유형**: .NET 솔루션(.sln) 기반 마이크로서비스, Docker 중심, .NET Aspire 구성 포함. 전신인 eShopOnContainers는 **archived** 상태로 Kubernetes/Helm artifact를 포함한다.
- **선정 이유**: .sln/.csproj 파싱, Docker 기반 멀티서비스 구조, 그리고 **archived repository 처리**(활성 소스 vs 보관된 참조 소스 구분)를 검증한다.
- **탐지되어야 할 artifact**: `.sln`, 프로젝트별 `.csproj`, Dockerfile들, (eShopOnContainers의 경우) Helm chart와 Kubernetes manifest, repository metadata의 archived 플래그.
- **기대 component model**: .csproj 단위 다중 컴포넌트, 웹 API/워커/프론트 구분, 컨테이너 대상 여부 판별(Dockerfile 또는 `<ContainerRepository>` 속성).
- **기대 Kubernetes Intent 특성**: 서비스별 Deployment/Service, 메시지 브로커·DB 등 외부 의존성의 placeholder, 이미지 이름·registry 질문.
- **기대 unresolved questions**: image registry와 이미지 네이밍 규칙, 외부 의존성(SQL Server, Redis, RabbitMQ 등) 접속 정보와 Secret placeholder, Aspire 오케스트레이션을 K8s로 어떻게 대응할지.
- **검증 항목**: repository가 archived인 경우 snapshot 메타데이터에 `archived: true`를 기록하고 "참조용 분석"임을 산출물에 명시하는지.
- **드러내는 실패 모드**: (a) .sln 없이 .csproj만 훑어 컴포넌트 누락, (b) archived repo의 오래된 manifest를 최신 관행으로 오인, (c) Aspire 전용 구성을 K8s 리소스로 무리하게 직역.

## 5.6 추가 선택 테스트 Repository

| Repository 유형 | 유용한 이유 | 드러내는 실패 모드 |
|---|---|---|
| Node.js Express + Dockerfile | 가장 단순한 단일 컨테이너 경로의 baseline. Dockerfile `EXPOSE`/`CMD` 추출 검증 | EXPOSE 없는 Dockerfile에서 포트 추측 여부 |
| React/Vite frontend-only | 정적 자산 앱. "서버가 아니라 정적 서빙 대상"이라는 판별 필요 | SPA를 백엔드 서비스로 오탐, nginx 서빙 전략 미제시 |
| Go 마이크로서비스(go.mod) | 단일 바이너리·멀티스테이지 빌드 관례, 포트가 코드 내 상수인 경우 | 소스 스캔 없이 포트 unresolved 처리 실패(추측으로 대체) |
| Helm chart-only repository | 소스 없이 배포 정의만 있는 경우. values.yaml의 미설정 값 추출 | chart를 렌더링하지 않고 template 원문을 파싱하려다 실패 |
| Kustomize overlays-only | base/overlay 구조 해석, 환경별 patch 인식 | overlay 병합 없이 base만 분석하여 환경 차이 누락 |

각 추가 Repository도 5.1~5.5와 동일하게 "기대 artifact / 기대 component model / 기대 Intent 특성 / 기대 unresolved questions / 기대 validation 체크"를 테스트 케이스로 문서화하여 회귀 스위트에 포함한다.

---

# 6. 배포 가능성 수준 정의

"manifest가 생성되었다"와 "애플리케이션이 구동된다"는 전혀 다른 명제다. 본 워크플로우는 모든 산출물에 다음 4단계 수준을 표기한다.

## Level 0. Manifest Generated — 생성됨

- 템플릿으로부터 YAML 파일이 생성된 상태.
- 필수 값이 placeholder(`__UNRESOLVED__`)로 남아 있을 수 있다.
- Kubernetes 유효성도, 애플리케이션 기동도 **보장하지 않는다**.
- 답하는 질문: *"파일이 존재하는가?"*

## Level 1. Kubernetes-Valid — Kubernetes가 이해 가능

- YAML 문법이 유효하다.
- Kubernetes schema 검증을 통과한다 (kubeconform / kubeval).
- client-side 또는 server-side `kubectl apply --dry-run`을 통과한다.
- 답하는 질문: *"Kubernetes가 이 리소스를 이해할 수 있는가?"*

## Level 2. Pod-Runnable — 컨테이너 기동 가능

- 컨테이너 이미지를 빌드할 수 있다.
- 설정된 registry에 이미지를 push할 수 있다.
- Deployment를 apply할 수 있다.
- Pod가 `Running` 상태에 도달한다.
- command/port/image 설정 누락으로 즉시 crash하지 않는다.
- 답하는 질문: *"컨테이너가 Kubernetes 위에서 시작될 수 있는가?"*

## Level 3. Application-Runnable — 애플리케이션 동작

- Pod가 `Ready` 상태에 도달한다 (readinessProbe 통과).
- Service가 트래픽을 올바르게 라우팅한다.
- Ingress 또는 내부 접근이 동작한다.
- 필요한 외부 의존성(DB, cache, 외부 API)에 도달 가능하다.
- 필요한 환경변수와 Secret 참조가 모두 공급되었다.
- 기본 smoke test가 통과한다.
- 답하는 질문: *"애플리케이션이 Kubernetes 위에서 실제로 동작하는가?"*

## 6.1 모드별 도달 가능 수준

| 모드 | 도달 가능 수준 | 근거 |
|---|---|---|
| **Repository-only 분석** | **Level 1 + 부분적 Level 2** | 문법·schema 유효성과 이미지 빌드 가능성까지는 Repository만으로 판정 가능. 그러나 registry, 누락 env 등으로 완전한 Level 2는 보장 불가 |
| **Deployment Profile 모드** | **Level 2 + Level 3** | Profile이 registry, namespace, 외부 의존성, Secret 참조, smoke test endpoint를 공급하면 Level 2 확정과 Level 3 검증이 가능 |

**명시적 한계 선언**:

- Level 3은 **GitHub 소스 Repository만으로는 보장할 수 없다.** 필수 runtime 값이 소스에 존재하지 않기 때문이다.
- Level 3은 (a) 사용자가 제공한 runtime 값(Deployment Profile)과 (b) **배포 후 검증**(Pod Ready + smoke test 통과)이라는 두 조건이 모두 충족되어야만 선언할 수 있다.
- 분석기는 각 산출물에 `target_level`과 `achieved_level`을 분리 기록하여 거짓 성공을 방지한다.

---
# 7. Runtime Gap 처리 정책

## 7.1 Runtime Gap의 정의

Runtime Gap이란 "애플리케이션 구동에 필요하지만 GitHub Repository에는 존재하지 않는(존재해서도 안 되는) 값"이다. 대표 예:

- **DB 접속 정보**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `JDBC_URL`, `DATABASE_URL`
- **미들웨어/브로커**: `REDIS_URL`, `KAFKA_BROKERS`
- **Credential**: `API_TOKEN`, `JWT_SECRET`, `OAUTH_CLIENT_SECRET`
- **외부 서비스**: `SMTP_HOST`, `SSO_URL`, 외부 API endpoint
- **클러스터/플랫폼 값**: image registry, namespace, ingress host, ingress class, TLS secret name, storage class
- **운영 정책**: resource requests/limits, node selector / toleration / affinity, 운영 replica 수

## 7.2 절대 규칙: 추측 금지

워크플로우는 위 값들을 **절대 추측하지 않는다.** 값이 누락되면 분석기는 다음 산출물을 생성한다.

| 산출물 | 역할 |
|---|---|
| `unresolved_questions.yaml` | 누락 값 각각에 대한 구조화된 질문 (형식, 후보, 이유, blocking level 포함) |
| `secret.placeholder.yaml` | Secret 후보의 키 구조만 담은 placeholder manifest (값은 `__REPLACE_ME__`) |
| `deployment-profile.template.yaml` | 사용자/플랫폼팀이 채워야 할 환경별 입력 템플릿 (누락 필드가 미리 배치됨) |
| `deployment-readiness-checklist.md` | 배포 전 확인 항목 체크리스트 (사람이 읽는 문서) |
| `smoke-test-plan.yaml` | 값이 공급된 뒤 Level 3 검증에 사용할 smoke test 계획 |

## 7.3 환경변수 분류 정책

추출된 모든 환경변수는 다음 6개 범주로 분류한다.

| 범주 | 판정 기준 | 처리 |
|---|---|---|
| **ConfigMap candidates** | 비밀 아님 + 값이 Repository에서 확인됨 (Compose, application.yml 등) | ConfigMap 템플릿에 포함, source/confidence 기록 |
| **Secret candidates** | 이름 패턴(`PASSWORD`, `SECRET`, `TOKEN`, `KEY`, `CREDENTIAL`, `PRIVATE`) 또는 사용 문맥이 비밀 | placeholder만 생성. **값은 절대 기록·전송하지 않음** |
| **Required unresolved** | 코드가 참조하지만 값이 어디에도 없음 + 없으면 기동 불가 | 질문 생성, `blocking_level: application_runnable` |
| **Optional unresolved** | 값이 없지만 기능 일부만 영향 (예: SMTP) | 질문 생성, `blocking_level: feature_partial` |
| **Framework defaults (low confidence)** | 프레임워크 관례상 기본값 존재 (예: Spring `server.port=8080`) | 기본값을 **low/medium confidence로 제시**하되 사용자 확인 목록에 포함 |
| **User-confirmation-required** | 소스 간 충돌, archived repo 출처, 개발용 기본값 등 확정 불가 | 후보 값과 함께 확인 질문 생성 |

분류 결과 예시:

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

## 7.4 항목별 Gap 처리 규칙

| 누락 항목 | 처리 |
|---|---|
| DB 접속 정보 | Secret placeholder + Profile의 `external_dependencies.database` 필드로 라우팅. 질문에 "external DB / in-cluster DB" 분기 포함 |
| Secret 값 전반 | placeholder 생성. 값 생성·제안 금지. Profile은 값이 아닌 **Secret 리소스 참조**(name/key)를 받는 것을 권장 |
| 외부 API endpoint | ConfigMap 후보 + required/optional 판정 후 질문 |
| image registry | Intent Model에 `image.registry: unresolved` 기록, Profile `target_cluster.image_registry`로 공급 |
| namespace | 템플릿 변수로 유지, Profile로 공급. 임의 생성 금지 |
| ingress host / class / TLS | Ingress 리소스는 "후보"로만 생성, host가 공급되기 전에는 렌더링 보류 또는 placeholder 표기 |
| storage class | PVC 후보에 `storageClassName: unresolved`, Profile로 공급 |
| resource requests/limits | 미기재. Profile `resource_policy`의 기본값을 적용. 분석기가 임의 수치 부여 금지 |
| 운영 topology (replica, affinity 등) | 기본 replica 1(개발 편의, low confidence 명시) + 운영값은 Profile/질문으로 |

---

# 8. Deployment Profile 기반 보정 흐름

## 8.1 Deployment Profile의 목적

Deployment Profile은 **환경별 입력 파일**이다. 소스 Repository가 제공할 수 없는 값 — 대상 클러스터, 노출 방식, 외부 의존성, runtime 설정, 리소스 정책, smoke test 기준 — 을 사용자 또는 플랫폼팀이 구조화된 형식으로 공급한다. 하나의 Repository 분석 결과에 대해 환경(dev/stage/prod)별로 여러 Profile을 적용할 수 있다.

## 8.2 예시 스키마

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

주목할 설계: 비밀 값은 Profile에 평문으로 넣지 않고 **기존 Secret 리소스에 대한 참조**(`*_secret_ref`)로 공급한다. Profile 파일 자체가 유출되어도 credential이 노출되지 않는다.

## 8.3 보정(correction) 흐름

```text
1. Repository 분석  →  unresolved_questions.yaml 생성
2. 사용자/플랫폼팀   →  deployment_profile.yaml 작성 (질문에 대응하는 필드 채움)
3. Analyzer         →  Repository 분석 결과 + Deployment Profile 병합 (merge)
4. Kubernetes Intent Model 재생성 (unresolved 필드가 Profile 값으로 치환)
5. Template Renderer →  Kubernetes manifest 생성
6. Validator        →  Kubernetes 유효성 검증 (Level 1 확정)
7. Deployment Checker → Pod Running / Ready 확인 (Level 2 확정)
8. Smoke Test       →  애플리케이션 수준 가용성 확인 (Level 3 확정)
```

## 8.4 병합 규칙과 질문 감소

- 병합 시 **Deployment Profile 값이 Repository 추론값보다 우선**한다(환경 소유자의 명시적 선언이므로). 단, Profile 값이 Repository의 high confidence 값과 모순되면 조용히 덮지 않고 `validation_report`에 충돌 경고를 남긴다.
- 병합 후 unresolved_questions.yaml을 재계산한다. Profile이 채운 항목은 `resolved_by: deployment_profile`로 이동하고, 남은 질문만 유지된다.
- 남은 질문 중 `blocking_level: application_runnable`이 0이 되어야 Level 3 검증 단계로 진입할 수 있다.

## 8.5 Level 3의 조건

Level 3(Application-Runnable)은 다음이 **모두** 충족될 때만 선언된다.

1. Deployment Profile로 모든 required 값이 공급됨
2. 렌더링된 manifest가 validation 통과 (Level 1)
3. 실제 클러스터에서 Pod Running + Ready (Level 2)
4. smoke-test-plan.yaml의 검사(예: `GET /health` → 200) 통과

즉, Level 3은 "생성 시점의 약속"이 아니라 **"배포 후 검증의 결과"**다.

---

# 9. 통합 사전 분석 워크플로우

전체 16단계(Step 0~15). 각 단계는 목적 / 입력 / 결정론적 규칙 / 출력 / LLM 사용 여부 / 기여하는 성공 수준으로 정의한다.

## Step 0. Repository Snapshot

- **목적**: 분석 대상을 불변(immutable) 스냅샷으로 고정하여 재현성 확보.
- **입력**: Repository URL, ref(branch/tag/commit).
- **결정론적 규칙**: 지정 commit으로 clone/checkout. commit SHA, 분석 시각, repo 메타데이터(archived 여부, 기본 브랜치, 크기) 기록. `.git`, 바이너리, 초대형 파일 제외 규칙 적용.
- **출력**: `00-repository-snapshot.yaml`
- **LLM 사용**: ❌ 불허
- **기여 수준**: 전 수준의 기반 (재현성)

## Step 1. Artifact Inventory

- **목적**: 분석에 의미 있는 파일 전수 목록화.
- **입력**: snapshot 파일 트리.
- **결정론적 규칙**: 파일명/경로 패턴 매칭 — Dockerfile*, docker-compose*.yml, Helm(`Chart.yaml`), Kustomize(`kustomization.yaml`), K8s manifest(YAML 내 `apiVersion`+`kind` 감지), package 파일(pom.xml, build.gradle, package.json, go.mod, requirements.txt, pyproject.toml, *.csproj, *.sln), CI/CD(.github/workflows, .gitlab-ci.yml, Jenkinsfile), 설정 파일(application*.yml, .env*), 문서(README 등). 각 항목에 경로·유형·크기 기록.
- **출력**: `01-artifact-inventory.yaml`
- **LLM 사용**: ❌ 불허 (파일 존재 탐지는 결정론 영역)
- **기여 수준**: Level 1 기반

## Step 2. Existing Deployment Artifact Analysis

- **목적**: 이미 존재하는 배포 정의(K8s manifest, Helm, Kustomize, Compose)를 최우선 정보 소스로 파싱.
- **입력**: artifact inventory 중 배포 artifact.
- **결정론적 규칙**: K8s YAML → 리소스 인벤토리(kind/name/image/port/env/volume). Helm → `helm template`(기본 values)로 렌더 후 파싱 + values.yaml의 미설정 키 추출. Kustomize → `kustomize build`로 overlay별 병합 결과 파싱. Compose → Kompose 스타일 필드 매핑(4.1절 규칙). 모든 추출값 `source: existing_manifest|helm|kustomize|compose`, confidence: high.
- **출력**: 기존 리소스 인벤토리 (component/runtime/intent 모델의 입력)
- **LLM 사용**: ❌ 불허 (파싱은 결정론 영역)
- **기여 수준**: Level 1~2 (기존 정의 재활용으로 unresolved 최소화)

## Step 3. Component / Service Candidate Detection

- **목적**: Repository를 배포 단위(component) 후보로 분해.
- **입력**: artifact inventory + 기존 배포 artifact 분석 결과.
- **결정론적 규칙**: (우선순위) ① 기존 manifest/Compose의 서비스 단위 → ② 빌드 파일 경계(모듈별 pom.xml, .csproj, package.json 위치) → ③ Dockerfile 위치. 모노레포는 디렉터리 경계로 분리. 인프라성 서비스(DB, cache, reverse proxy)는 `role: dependency|infrastructure`로 태깅하여 앱 컴포넌트와 구분.
- **출력**: `02-component-model.yaml` (초안)
- **LLM 사용**: ❌ 불허
- **기여 수준**: Level 1~2

## Step 4. Language / Framework / Build Method Detection

- **목적**: 컴포넌트별 언어·프레임워크·빌드 방식 판정.
- **입력**: component 후보 + 파일 지표.
- **결정론적 규칙**: Buildpacks detect 스타일 규칙 테이블(4.5절). 파일 지표 → 언어(high), 의존성 선언 → 프레임워크(high/medium), 빌드 파일 → 빌드 커맨드 추론(예: pom.xml → `mvn -B package`). Dockerfile 있으면 `build_strategy: dockerfile`, 없으면 `buildpacks|dockerfile_needed` 후보 제시.
- **출력**: component_model의 language/framework/build 섹션
- **LLM 사용**: ❌ 불허 (규칙 기반 탐지)
- **기여 수준**: Level 2 (이미지 빌드 가능성)

## Step 5. Runtime Information Extraction

- **목적**: 실행 커맨드, 포트, 헬스 endpoint, 런타임 버전 등 실행 정보 추출.
- **입력**: Dockerfile(`EXPOSE`, `CMD`, `ENTRYPOINT`, `USER`), 애플리케이션 설정(application.yml의 `server.port`, `management.endpoints`), package.json `scripts.start`, 프레임워크 관례 DB.
- **결정론적 규칙**: 소스 우선순위(10장)에 따라 추출. 관례 기반 값(Spring 8080, FastAPI/uvicorn 8000 등)은 confidence: low~medium으로만 기록. actuator/healthz 등 헬스 endpoint 지표가 있으면 probe 후보로 기록.
- **출력**: `03-runtime-model.yaml`
- **LLM 사용**: ❌ 불허
- **기여 수준**: Level 2~3 (probe, 기동 커맨드)

## Step 6. Port / Env / Volume / Dependency Analysis

- **목적**: 네트워크·설정·스토리지·의존성 상세 분석과 환경변수 분류.
- **입력**: Compose, Dockerfile, 앱 설정, 소스 내 env 참조 스캔(`os.getenv`, `process.env`, `@Value` 등의 정적 패턴 매칭).
- **결정론적 규칙**: 포트 소스별 대조(충돌 시 10장 우선순위). 환경변수 → 7.3절 6분류. named volume/영속 경로 → PVC 후보. `depends_on`·접속 URL 패턴 → 의존성 엣지(내부 서비스 vs 외부 시스템 구분).
- **출력**: `04-dependency-model.yaml` + env_classification
- **LLM 사용**: ❌ 불허
- **기여 수준**: Level 2~3

## Step 7. Application Topology Model Generation

- **목적**: 컴포넌트·의존성·진입점을 하나의 애플리케이션 토폴로지로 통합.
- **입력**: component/runtime/dependency 모델.
- **결정론적 규칙**: 그래프 구성(노드=컴포넌트·외부 시스템, 엣지=의존). 진입점(gateway, frontend, reverse proxy 의도) 식별. 순환 의존·고아 컴포넌트 감지 시 경고.
- **출력**: topology 모델 (kubernetes_intent의 입력)
- **LLM 사용**: ⭕ 제한적 허용 — 토폴로지의 **사람 대상 요약문** 생성만. 그래프 자체는 결정론적으로 생성.
- **기여 수준**: Level 3 (서비스 간 라우팅 정확성)

## Step 8. Kubernetes Intent Model Generation

- **목적**: 토폴로지를 Kubernetes 리소스 의도(무엇을 만들 것인가)로 변환. **아직 YAML이 아니다.**
- **입력**: topology 모델 + 기존 manifest 인벤토리.
- **결정론적 규칙**: 컴포넌트 → Deployment 의도(stateless 기본; 영속 상태+순서 필요 시 StatefulSet 질문). 포트 노출 → Service 의도. 진입점 → Ingress 후보(host: unresolved). env 분류 → ConfigMap/Secret placeholder 의도. 볼륨 → PVC 의도(storageClass: unresolved). 모든 필드에 value/source/confidence/unresolved 기록.
- **출력**: `05-kubernetes-intent.yaml`
- **LLM 사용**: ❌ 불허 (매핑은 규칙)
- **기여 수준**: Level 1~3의 설계도

## Step 9. Unresolved Question Generation

- **목적**: Intent Model의 unresolved/low-confidence 필드를 구조화된 사용자 질문으로 변환.
- **입력**: Intent Model, env_classification.
- **결정론적 규칙**: unresolved 필드 → 질문 항목(id, 대상 필드 경로, 형식, 후보값, blocking_level) 기계적 생성. 중복 질문 병합(예: 여러 컴포넌트의 registry → 단일 질문).
- **출력**: `06-unresolved-questions.yaml`, `07-deployment-profile.template.yaml`(질문에 대응하는 빈 필드 배치)
- **LLM 사용**: ⭕ 허용 — 질문의 **자연어 문안**과 이유 설명 생성(schema-constrained). 질문 목록 자체(무엇을 물을지)는 결정론적으로 결정.
- **기여 수준**: Level 2→3 전환의 관문

## Step 10. Deployment Profile Merge

- **목적**: 사용자가 채운 deployment_profile.yaml을 분석 결과와 병합.
- **입력**: Intent Model + deployment_profile.yaml.
- **결정론적 규칙**: 8.4절 병합 규칙 — Profile 우선, 모순 시 경고, unresolved 재계산, `resolved_by` 기록. Profile 스키마 자체를 JSON Schema로 검증(잘못된 Profile은 병합 전 거부).
- **출력**: 갱신된 kubernetes_intent.yaml + 축소된 unresolved-questions
- **LLM 사용**: ⭕ 제한적 허용 — Profile 값과 Repository 추론값의 **충돌 설명문** 생성만.
- **기여 수준**: Level 2~3 진입 조건

## Step 11. Template-based Manifest Rendering

- **목적**: Intent Model → 실제 Kubernetes YAML 생성.
- **입력**: 병합된 Intent Model + 버전 관리되는 리소스 템플릿.
- **결정론적 규칙**: 리소스별 템플릿(14장 정책)에 Intent 값 주입. unresolved 필드가 남은 리소스는 (a) 렌더 보류 또는 (b) `__UNRESOLVED__` placeholder + Level 0 표기. 렌더 결과에 생성 메타데이터(annotation: 분석 버전, commit SHA) 삽입.
- **출력**: `08-generated-manifests/` (deployment.yaml, service.yaml, ingress.yaml, configmap.yaml, secret.placeholder.yaml, pvc.yaml, hpa.yaml, serviceaccount.yaml)
- **LLM 사용**: ❌ 불허 (free-form YAML 생성 금지)
- **기여 수준**: Level 0→1

## Step 12. Kubernetes Validation

- **목적**: 렌더 결과의 Kubernetes 유효성 검증.
- **입력**: 생성된 manifest.
- **결정론적 규칙**: YAML 파싱 → kubeconform(대상 K8s 버전 지정) → `kubectl apply --dry-run=client`(가능 시 `--dry-run=server`) → kube-linter/kube-score → (선택) 조직 정책 엔진. 모든 결과를 구조화 리포트로 기록.
- **출력**: `09-validation-report.yaml`
- **LLM 사용**: ⭕ 제한적 허용 — validator **오류 메시지의 해석·수리 제안**(15장). 판정 자체는 도구가 수행.
- **기여 수준**: Level 1 확정

## Step 13. Deployment Check

- **목적**: 실제 클러스터 적용 후 Pod 기동 확인.
- **입력**: 검증 통과 manifest + 대상 클러스터(Profile).
- **결정론적 규칙**: apply → rollout status 대기 → Pod phase 확인(Running) → 컨테이너 상태 확인(CrashLoopBackOff, ImagePullBackOff, OOMKilled 감지) → Ready 조건 확인. 실패 시 이벤트·로그 수집.
- **출력**: deployment check 결과 (validation_report에 병합)
- **LLM 사용**: ⭕ 제한적 허용 — 수집된 이벤트/로그 기반 **원인 설명·수리 제안**.
- **기여 수준**: Level 2 확정, Level 3 전제

## Step 14. Smoke Test

- **목적**: 애플리케이션 수준 가용성 검증.
- **입력**: `11-smoke-test-plan.yaml`(Profile의 smoke_test 필드 기반) + 배포된 서비스.
- **결정론적 규칙**: Service/Ingress 경유 HTTP 요청 → 기대 status 대조. (확장) 핵심 경로 다중 체크, 의존성 도달성 체크. 결과를 pass/fail로 기록.
- **출력**: smoke test 결과 (Level 3 판정 근거)
- **LLM 사용**: ❌ 불허 (판정은 결정론) — 실패 시 리포트 요약만 Step 15에서 허용
- **기여 수준**: Level 3 확정

## Step 15. Repair Loop

- **목적**: validation/deployment/smoke 실패를 수정 제안으로 환류.
- **입력**: validation_report, 클러스터 이벤트/로그, smoke 결과.
- **결정론적 규칙**: 알려진 오류 패턴(ImagePullBackOff→registry/credential, schema 오류→필드 경로)은 규칙 기반 수리 우선. 규칙으로 못 잡는 오류만 LLM에 전달. LLM 제안은 **Intent Model 또는 Profile에 대한 patch** 형식(JSON Schema 강제)으로만 수용 → patch 적용 → Step 11부터 재실행. 최대 반복 횟수 제한. 원본 YAML을 LLM이 직접 수정하지 않는다.
- **출력**: `12-repair-suggestions.yaml`
- **LLM 사용**: ⭕ 허용 — 단, **오류 증거가 있는 경우에만**, schema-constrained patch 제안으로만.
- **기여 수준**: Level 1~3 회복

## 단계별 요약표

| Step | 이름 | LLM | 기여 수준 |
|---|---|---|---|
| 0 | Repository Snapshot | ❌ | 기반 |
| 1 | Artifact Inventory | ❌ | L1 |
| 2 | 기존 배포 Artifact 분석 | ❌ | L1~2 |
| 3 | Component 탐지 | ❌ | L1~2 |
| 4 | 언어/프레임워크/빌드 탐지 | ❌ | L2 |
| 5 | Runtime 정보 추출 | ❌ | L2~3 |
| 6 | Port/Env/Volume/의존성 분석 | ❌ | L2~3 |
| 7 | Topology 모델 생성 | ⭕ 요약만 | L3 |
| 8 | Kubernetes Intent Model | ❌ | 설계도 |
| 9 | Unresolved Question 생성 | ⭕ 문안만 | L2→3 관문 |
| 10 | Deployment Profile 병합 | ⭕ 충돌 설명만 | L2~3 |
| 11 | 템플릿 렌더링 | ❌ | L0→1 |
| 12 | Kubernetes Validation | ⭕ 오류 해석만 | L1 확정 |
| 13 | Deployment Check | ⭕ 원인 설명만 | L2 확정 |
| 14 | Smoke Test | ❌ | L3 확정 |
| 15 | Repair Loop | ⭕ patch 제안 | 회복 |

---

# 10. 신뢰도 및 충돌 해결 정책

## 10.1 Confidence 수준 정의

| 수준 | 정의 | 예 |
|---|---|---|
| **high** | 명시적 선언에서 직접 추출 | 기존 manifest의 `containerPort`, Dockerfile `EXPOSE`, Compose `ports` |
| **medium** | 신뢰할 수 있는 설정에서 간접 추출 또는 단일 소스 | application.yml의 `server.port`, CI 파일의 빌드 커맨드 |
| **low** | 프레임워크 관례·휴리스틱 기반 | "Spring Boot는 보통 8080", 소스 코드 정규식 스캔 결과 |
| **none** | 근거 없음 → **unresolved** | DB host, registry, ingress host |

정책: high는 그대로 채택, medium은 채택하되 확인 목록 표기, low는 후보로만 제시하고 사용자 확인 질문 생성, none은 반드시 unresolved 처리.

## 10.2 소스 우선순위 (충돌 해결)

동일 필드에 대해 복수 소스가 다른 값을 줄 때, 아래 우선순위로 결정한다 (위가 우선).

```text
1. Deployment Profile            (환경 소유자의 명시적 선언 — 병합 단계에서 최우선)
2. 기존 Kubernetes manifest      (배포 의도의 직접 증거)
3. Helm / Kustomize              (렌더링된 배포 정의)
4. Docker Compose                (컨테이너 실행 정의)
5. Dockerfile                    (이미지 수준 정의)
6. CI/CD workflow                (빌드·배포 절차의 증거)
7. Package/빌드 파일              (pom.xml, package.json 등)
8. 애플리케이션 설정 파일          (application.yml, .env 템플릿)
9. 소스 코드 정적 스캔            (env 참조, 포트 상수)
10. 프레임워크 관례               (convention — 항상 low confidence)
```

## 10.3 충돌 처리 규칙

- 상위 소스 값을 채택하되, **하위 소스의 상충 값을 폐기하지 않고** `conflicts` 필드에 보존한다.
- 충돌이 있는 필드는 confidence를 한 단계 강등하고 사용자 확인 질문을 생성한다.
- 예:

```yaml
container_port:
  value: 8080
  source: dockerfile_expose
  confidence: medium        # 충돌로 인해 high → medium 강등
  conflicts:
    - value: 8081
      source: application.yml(server.port)
  question_ref: Q-PORT-001
```

- LLM은 충돌의 **설명문**("Dockerfile은 8080을 노출하지만 application.yml은 8081을 지정합니다…")만 생성할 수 있고, 어느 값을 채택할지 결정할 수 없다.

---

# 11. 중간 모델 설계

각 중간 모델의 최소 스키마와 예시. 모든 추출 필드는 `value / source / confidence`를 갖고, 필요 시 `unresolved: true`를 갖는다.

## 11.1 repository_snapshot.yaml

```yaml
repository_snapshot:
  url: https://github.com/mybatis/jpetstore-6
  ref: main
  commit_sha: "a1b2c3d..."
  analyzed_at: "2026-07-10T09:00:00Z"
  archived: false
  default_branch: main
  analyzer_version: "0.3.0"
  rules_version: "2026.07"
  file_count: 412
  excluded_patterns: [".git/**", "**/*.png", "**/node_modules/**"]
```

## 11.2 artifact_inventory.yaml

```yaml
artifact_inventory:
  build_files:
    - path: pom.xml
      type: maven
  container_files:
    - path: Dockerfile
      type: dockerfile
      present: false          # 부재도 명시적으로 기록
  compose_files: []
  kubernetes_manifests: []
  helm_charts: []
  kustomize_dirs: []
  ci_cd:
    - path: .github/workflows/ci.yml
      type: github_actions
  app_configs:
    - path: src/main/resources/application.properties
      type: java_properties
  docs:
    - path: README.md
```

## 11.3 component_model.yaml

```yaml
components:
  - id: backend-api
    role: application            # application | dependency | infrastructure
    root_path: backend/
    language: { value: python, source: pyproject.toml, confidence: high }
    framework: { value: fastapi, source: pyproject.toml, confidence: high }
    build:
      strategy: { value: dockerfile, source: backend/Dockerfile, confidence: high }
      dockerfile: backend/Dockerfile
      command: { value: null, unresolved: false }
    image:
      name_candidate: backend-api
      registry: { value: null, unresolved: true, profile_field: target_cluster.image_registry }
```

## 11.4 runtime_model.yaml

```yaml
runtime:
  - component: backend-api
    ports:
      - value: 8000
        source: dockerfile_expose
        confidence: high
    start_command: { value: "uvicorn app.main:app", source: dockerfile_cmd, confidence: high }
    health_endpoints:
      - path: /health
        source: source_scan
        confidence: medium
    runtime_version: { value: "python3.11", source: dockerfile_base_image, confidence: high }
```

## 11.5 dependency_model.yaml

```yaml
dependencies:
  internal:                      # repo 내 컴포넌트 간
    - from: frontend
      to: backend-api
      kind: http
      source: compose_depends_on
      confidence: high
  external:                      # repo 밖 시스템
    - component: backend-api
      type: postgresql
      evidence: "env DATABASE_URL referenced"
      source: source_scan
      confidence: high
      connection: { unresolved: true, profile_field: external_dependencies.database }
```

## 11.6 kubernetes_intent.yaml

```yaml
kubernetes_intent:
  - component: backend-api
    workload:
      kind: Deployment
      replicas: { value: 1, source: default_dev, confidence: low }
      container:
        image: { registry: { unresolved: true }, name: backend-api, tag: { unresolved: true } }
        port: { value: 8000, source: dockerfile_expose, confidence: high }
        env_from: [configmap: backend-api-config, secret: backend-api-secret]
        probes:
          readiness: { path: /health, port: 8000, confidence: medium }
      resources: { unresolved: true, profile_field: resource_policy }
    service: { type: ClusterIP, port: 8000 }
    ingress:
      candidate: true
      host: { unresolved: true, profile_field: exposure.host }
    configmap: { keys: [APP_ENV, LOG_LEVEL] }
    secret_placeholder: { keys: [DB_PASSWORD, JWT_SECRET] }
```

## 11.7 unresolved_questions.yaml

```yaml
unresolved_questions:
  - id: Q-DB-001
    field: external_dependencies.database.host
    question: "backend-api가 참조하는 PostgreSQL의 접속 host는 무엇입니까?"
    reason: "DATABASE_URL 환경변수가 소스에서 참조되지만 값이 Repository에 없습니다."
    answer_type: hostname
    candidates: []
    blocking_level: application_runnable
    profile_field: external_dependencies.database.host
  - id: Q-ING-001
    field: exposure.host
    question: "외부 노출 도메인(Ingress host)은 무엇입니까?"
    answer_type: fqdn
    blocking_level: application_runnable
```

## 11.8 deployment-profile.template.yaml

8.2절 스키마에서 값 부분이 비워지고, 각 필드에 대응하는 질문 id가 주석으로 연결된 형태.

```yaml
deployment_profile:
  target_cluster:
    namespace: ""                # Q-NS-001
    image_registry: ""           # Q-REG-001
  external_dependencies:
    database:
      host: ""                   # Q-DB-001
```

## 11.9 validation_report.yaml

```yaml
validation_report:
  manifest_set: 08-generated-manifests
  yaml_syntax: pass
  kubeconform: { result: pass, kubernetes_version: "1.29" }
  dry_run: { client: pass, server: skipped, reason: "no cluster in repo-only mode" }
  linter:
    kube-linter: { warnings: 2, details: [...] }
  deployment_check: { status: not_run }
  smoke_test: { status: not_run }
  achieved_level: 1
  target_level: 2
```

## 11.10 deployment-readiness-checklist.md (구조)

```markdown
# 배포 준비 체크리스트: backend-api
- [ ] image registry 접근 및 push 권한 확인 (Q-REG-001)
- [ ] namespace 생성 및 RBAC 확인
- [ ] Secret 리소스(myapp-db-secret) 사전 생성
- [ ] DB 네트워크 도달성 확인 (postgres.internal.local:5432)
- [ ] Ingress controller(class: nginx) 존재 확인
- [ ] smoke test endpoint(/health) 응답 확인 계획
```

## 11.11 smoke-test-plan.yaml

```yaml
smoke_test_plan:
  - component: backend-api
    checks:
      - name: health-endpoint
        method: GET
        path: /health
        via: ingress            # ingress | service | port-forward
        expected_status: 200
        timeout_seconds: 10
      - name: readiness-gate
        type: pod_ready
        min_ready_seconds: 30
```

---
# 12. LLM 연동 아키텍처

## 12.1 설계 목표

분석 파이프라인(결정론 영역)과 모델 백엔드를 완전히 분리한다. 파이프라인은 **LLM Provider Interface**라는 단일 추상화에만 의존하고, 그 뒤의 구현은 설정으로 교체된다.

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

## 12.2 Option A. Local On-Premise LLM Runtime

모델이 **기업 네트워크 내부**에서 실행되고, 분석기가 사내 inference 서버를 직접 호출하는 구성.

**고려 사항 (high-level)**

| 항목 | 설계 지침 |
|---|---|
| 모델 배치 | 분석기와 같은 클러스터의 전용 namespace 또는 별도 GPU 노드풀. inference 서버(vLLM 등)를 내부 Service로 노출 |
| 네트워크 격리 | NetworkPolicy로 분석기→모델 단방향 허용, 모델의 외부 egress 차단(`network_policy: internal_only`) |
| GPU 리소스 계획 | 모델 크기(예: 30B급) 기준 GPU 메모리 산정, 동시 분석 작업 수에 따른 배치/큐잉 설계 |
| 지연 시간 | 분석 파이프라인의 LLM 호출 지점(Step 7/9/10/12/13/15)은 모두 비차단 보조 경로 — LLM 지연이 결정론 단계를 막지 않도록 설계 |
| 보안 | 보안 정책이 명시적으로 허용하지 않는 한 **모델은 secret을 받지 않는다.** 모델에는 원문 dump가 아닌 **정규화된 중간 모델**만 전달 |
| 감사 로깅 | 모든 요청/응답을 audit log로 기록(`audit_logging: enabled`) — 어떤 중간 모델이 전달되었고 어떤 제안이 반환되었는지 추적 가능 |

**설정 예시**

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

## 12.3 Option B. OpenAI Endpoint API-Compatible Integration

모델 서버가 **OpenAI-compatible API**(Chat Completions API 형태)를 노출하고, 분석기가 OpenAI 스타일 클라이언트 설정으로 호출하는 구성.

**중요한 명확화**: OpenAI-compatible endpoint 지원은 **OpenAI 호스팅 모델을 써야 한다는 뜻이 아니다.** 호환 API를 노출하는 어떤 서버든 가능하다:

- vLLM
- TGI (Text Generation Inference)
- llama.cpp server
- Ollama-compatible gateway
- LiteLLM proxy
- 사내 LLM gateway
- 그 외 호환 endpoint 동작을 노출하는 모든 모델 서버

즉 Option A의 On-Premise 서버가 동시에 Option B의 연동 계약을 만족하는 것이 가장 흔한 구성이며, 두 옵션의 차이는 "어디서 실행되는가"(배치)와 "무엇으로 호출하는가"(API 계약)의 관심사 차이다.

**설정 가능 항목**: `base_url`, `api_key`, `model` 이름, `timeout`, `max_tokens`, `temperature`, `top_p`, `response_format`(지원 시 JSON Schema mode).

**설정 예시**

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

`api_key`는 파일이 아닌 환경변수 참조(`api_key_env`)로 공급하여 설정 파일 유출 시에도 credential이 노출되지 않게 한다.

## 12.4 결정론적 추론 설정

LLM 출력의 재현성을 최대화하기 위한 권장 설정:

- `temperature: 0`
- `top_p: 1`
- **고정된 system prompt** (버전 관리 대상 — rules_version과 함께 기록)
- **schema-constrained output** (`response_format: json_schema` 또는 프롬프트 내 schema 강제 + 파서 검증)
- **재시도는 validation 피드백이 있을 때만** — 출력이 schema 검증에 실패하면 실패 사유를 포함해 재요청, 그 외의 "다시 생성" 반복 금지

## 12.5 요청/응답 스키마 통제

- 모든 LLM 호출은 **용도별 output contract**(JSON Schema)를 갖는다: `question_wording`, `conflict_explanation`, `patch_suggestion`, `summary_text`.
- 응답은 반환 즉시 schema validator를 통과해야 하며, 실패 시 해당 호출은 "결과 없음"으로 처리된다 — 파이프라인은 LLM 결과 없이도 진행 가능해야 한다(질문 문안은 기계 생성 기본 문구로 대체).
- `patch_suggestion`은 Intent Model/Profile의 필드 경로에 대한 patch 목록으로 제한되며, 최종 YAML 텍스트를 직접 담을 수 없다.

## 12.6 재시도 및 수리 전략

```text
LLM 호출 → schema 검증 실패 → 실패 사유 첨부 1회 재시도 → 재실패 시 기계 생성 기본값 사용
patch 제안 → patch를 Intent Model에 적용 → Step 11 재렌더 → Step 12 재검증
           → 검증 실패 지속 시 최대 N회(권장 3회) 후 사람에게 escalate
```

## 12.7 벤더 종속(vendor lock-in) 회피

- 파이프라인 코드는 Provider Interface의 4개 연산만 사용: `generate_question_wording`, `explain_conflict`, `suggest_patch`, `summarize`.
- OpenAI-compatible 계약을 표준 wire format으로 채택하되, provider 구현체를 플러그인으로 두어 비호환 API(사내 독자 gateway 등)도 어댑터로 수용.
- 모델 이름·프롬프트·schema 버전을 산출물 메타데이터에 기록하여, 모델 교체 시 회귀 테스트(5장 Repository 세트)로 동등성을 검증.

---

# 13. LLM 역할 제한 정책

## 13.1 LLM이 할 수 있는 것

| 허용 작업 | 단계 | 출력 계약 |
|---|---|---|
| 분석 결과 요약문 생성 | Step 7 | summary_text |
| 소스 간 충돌 설명문 생성 | Step 10 | conflict_explanation |
| unresolved question의 자연어 문안 생성 | Step 9 | question_wording |
| validation/runtime 오류에 대한 수리 제안 | Step 12/13/15 | patch_suggestion |
| 사용자向 문서(checklist, README 문안) 생성 | 산출물 단계 | summary_text |

## 13.2 LLM이 해서는 안 되는 것

- 파일 존재 탐지
- Docker Compose 파싱
- Dockerfile 파싱
- package 파일(pom.xml, package.json 등) 파싱
- Secret 값 직접 생성
- registry/도메인/namespace의 임의 생성
- 검증되지 않은 최종 YAML 직접 생성
- 충돌 값 중 어느 것을 채택할지 **결정**
- confidence 등급 부여(등급은 규칙이 결정)

## 13.3 반드시 결정론적 코드가 처리해야 하는 것

파일 스캔, 모든 artifact 파싱, 언어/프레임워크/빌드 탐지, 포트·env·볼륨·의존성 추출, 중간 모델 생성, Profile 병합, 템플릿 렌더링, 모든 validation 판정, smoke test 실행과 pass/fail 판정.

## 13.4 반드시 사용자에게 물어야 하는 것

Repository와 Deployment Profile 어디서도 확인되지 않는 모든 값: DB 접속 정보, credential 공급 방식, 외부 endpoint, registry, namespace, ingress host/TLS, storage class, 운영 리소스 정책, 아키텍처 결정(예: Eureka 유지 여부, DB 외부화 여부).

## 13.5 LLM 추측 방지 메커니즘

1. **입력 통제**: LLM은 Repository 원문이 아니라 정규화된 중간 모델만 받는다. 모델이 "못 본 값"을 지어낼 표면적을 줄인다.
2. **출력 통제**: 모든 출력은 JSON Schema로 강제된다. patch 제안은 필드 경로 화이트리스트(unresolved 필드만) 안에서만 유효하다.
3. **값 필터**: LLM 출력에 등장한 hostname/registry/도메인 형태의 문자열은 Profile·Repository에 근거가 없으면 자동 거부한다.
4. **결정권 박탈**: LLM 출력은 언제나 "제안"이며, 채택은 규칙(schema 검증 + 근거 확인) 또는 사용자가 한다.

## 13.6 Schema-constrained output 처리

- 지원 서버(vLLM 등)에서는 `response_format: json_schema`(guided decoding)를 사용한다.
- 미지원 서버에서는 프롬프트에 schema를 포함하고, 응답을 파서로 검증한다.
- 검증 실패 → 실패 사유 포함 1회 재시도 → 재실패 시 결과 폐기(파이프라인은 기본 문구로 진행).

---

# 14. Manifest 생성 정책

최종 YAML은 특정 앱에 대한 예시가 아니라, **Kubernetes Intent Model + Deployment Profile → 템플릿 렌더링**의 규칙으로 정의한다. 모든 템플릿은 버전 관리되며, 렌더 결과에는 분석 메타데이터 annotation(commit SHA, analyzer/rules 버전, achieved_level)이 삽입된다.

| 리소스 | 생성 규칙 |
|---|---|
| **Deployment** | 컴포넌트당 1개(stateless 기본). image = Profile registry + Intent name/tag. port/probe/env는 Intent에서, replicas/resources는 Profile `resource_policy`에서. resources 미공급 시 필드 생략(임의 수치 금지). readinessProbe는 헬스 endpoint confidence가 medium 이상일 때만 생성, 아니면 질문 |
| **Service** | 포트가 확인된 컴포넌트당 ClusterIP 기본. 노출 유형 변경(NodePort/LoadBalancer)은 Profile `exposure.type`으로만 |
| **Ingress** | 진입점 컴포넌트에 한해 후보 생성. `host`·`ingressClassName`은 Profile 값이 있을 때만 렌더. TLS는 `tls.enabled`+`secret_name`이 공급될 때만 블록 생성 |
| **ConfigMap** | env_classification의 configmap_candidates로 구성. 값의 source/confidence를 annotation으로 기록 |
| **Secret placeholder** | secret_candidates의 **키 구조만** 생성, 값은 `__REPLACE_ME__`. Profile이 `secret_refs`를 주면 Secret 생성 대신 기존 Secret 참조(envFrom/valueFrom)로 전환하고 placeholder 파일은 제거 |
| **PVC** | 볼륨 후보당 1개. `storageClassName`·용량은 Profile에서. 미공급 시 렌더 보류(Level 0 표기) |
| **HPA** | 기본 생성하지 않음. Profile에 autoscaling 정책이 명시된 경우에만 생성(metrics/min/max는 Profile 값) |
| **ServiceAccount** | 컴포넌트당 전용 SA 생성 + Deployment에 연결(default SA 사용 회피). 추가 RBAC은 범위 밖, 필요 시 질문 |

공통 정책:

- 모든 리소스에 일관된 label 세트(`app.kubernetes.io/name`, `app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by`) 적용.
- `namespace`는 manifest에 하드코딩하지 않고 Profile 값으로 주입(미공급 시 필드 생략 + kubectl `-n` 안내).
- unresolved 필드가 남은 리소스는 렌더 보류가 기본, 사용자가 요청하면 `__UNRESOLVED__` placeholder와 Level 0 표기로 렌더.
- 템플릿 변경은 rules_version을 올리며, 5장 회귀 세트로 스냅샷 테스트한다.

---

# 15. Validation & Repair Loop

## 15.1 검증 체인

```text
① YAML 문법 검증          (파서)
② Kubernetes schema 검증  (kubeconform 권장 / kubeval — 대상 K8s 버전 명시)
③ kubectl dry-run          (client-side → 클러스터 가능 시 server-side)
④ Linter                   (kube-linter / kube-score: probe 누락, latest 태그, root 실행 등)
⑤ 정책 검증                (조직 정책 엔진 — OPA/Gatekeeper·Kyverno 규칙이 있는 경우)
⑥ Pod Running 확인         (apply 후 rollout/phase 감시)
⑦ Pod Ready 확인           (readiness 조건)
⑧ Smoke test              (smoke-test-plan.yaml 실행)
```

①~⑤는 클러스터 없이(또는 dry-run만으로) 수행 가능하며 Level 1을 확정한다. ⑥~⑦은 Level 2, ⑧은 Level 3을 확정한다. 각 단계 결과는 `09-validation-report.yaml`에 누적 기록된다.

## 15.2 Repair Loop 규칙

- **LLM은 validator 또는 runtime의 실제 오류 출력이 있을 때만 개입한다.** 오류 없이 "더 좋게 고쳐줘" 식의 개입은 없다.
- 1차는 규칙 기반 수리: 알려진 패턴 매핑 테이블(예: `ImagePullBackOff` → registry 주소/credential/이미지 태그 점검, `CrashLoopBackOff` + exit code → command/env 점검, schema 오류 → 필드 경로 자동 수정).
- 규칙으로 해결되지 않는 오류만 LLM에 전달: 입력 = 오류 메시지 + 관련 Intent Model 조각(secret 값 제외), 출력 = `patch_suggestion`(schema 강제).
- patch는 Intent Model 또는 Profile에 적용 → Step 11 재렌더 → 검증 재실행. **LLM이 YAML을 직접 수정하는 경로는 없다.**
- 최대 반복 횟수(권장 3회) 초과 시 사람에게 escalate하고, 시도 내역을 `12-repair-suggestions.yaml`에 남긴다.

---

# 16. 최종 산출물 구조

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

- `00~05`: 결정론적 분석의 중간 모델 (재현 가능, diff 가능).
- `06~07`: runtime gap의 명시적 표현 (질문과 입력 템플릿).
- `08`: 템플릿 렌더링 결과 (멀티 컴포넌트는 컴포넌트별 하위 디렉터리).
- `09~12`: 검증·준비·테스트·수리 기록. `09`의 `achieved_level`이 이 산출물 세트의 공식 배포 가능성 수준이다.

---

# 17. MVP 구현 범위

## 17.1 우선 지원 범위

| 축 | MVP 포함 | 근거 |
|---|---|---|
| **입력** | Dockerfile, docker-compose.yml, 단순 디렉터리 구조 모노레포 | 가장 흔하고 파싱 규칙이 명확(Kompose 준용) |
| **언어** | Java(Maven), Node.js(npm), Python(pip/poetry) | 테스트 세트(5장)의 핵심 커버 + detect 규칙 단순 |
| **생성 리소스** | Deployment, Service, ConfigMap, Secret placeholder, Ingress(후보) | Level 1~2 달성의 최소 세트 |
| **모델 연동** | **OpenAI-compatible endpoint 1종** (Provider Interface 뒤에) | On-Premise vLLM부터 사내 gateway까지 단일 계약으로 커버 |
| **Validation** | YAML 파서 + kubeconform + kubectl dry-run(client) | 클러스터 없이 Level 1 확정 가능 |
| **산출물** | 16장 구조 중 00~09 + 10, 11 | repair loop 자동화(12) 이전에도 가치 제공 |

## 17.2 MVP에서 제외

- Helm chart / Kustomize **입력** 파싱 (2단계 로드맵)
- Helm chart **출력** 형식
- Go/.NET detector, Buildpacks 빌드 실행
- HPA/PVC/StatefulSet 자동 생성 (질문으로만 라우팅)
- server-side dry-run 이상의 자동 배포·smoke test 실행(Level 3 자동화) — MVP에서는 plan 파일 생성까지
- 규칙 기반을 넘어서는 LLM repair loop (MVP는 question wording + 오류 설명까지)
- Local runtime 전용 어댑터(비호환 API) — OpenAI-compatible로 충분한 동안 보류

## 17.3 MVP 목표 수준

- **Repository-only 모드**: Level 1 + 부분적 Level 2 (이미지 빌드 가능성 판정 포함)
- **Deployment Profile 모드**: Level 2
- **Level 3**: runtime 값과 smoke test endpoint가 공급되고 배포 후 검증이 수행된 경우에만 (MVP에서는 수동 실행 절차를 checklist로 안내)

## 17.4 MVP 완료 판정

5장의 테스트 세트 중 jpetstore-6(단일 Java), full-stack-fastapi-template(모노레포+Compose)에 대해: (a) 산출물 12종 생성, (b) 모든 필드에 source/confidence 존재, (c) DB/registry/host 값이 결과물 어디에도 추측으로 등장하지 않음, (d) kubeconform 통과 — 를 회귀 테스트로 자동 검증한다.

---

# 18. 최종 권장 아키텍처

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

구성 요소 책임 요약:

| 구성 요소 | 책임 | 결정론 여부 |
|---|---|---|
| Repository Scanner | snapshot 고정, 파일 인벤토리 | 결정론 |
| Artifact Parser | Dockerfile/Compose/Helm/Kustomize/manifest/package 파싱 | 결정론 |
| Rule-based Detector | 언어/프레임워크/빌드/포트/env/의존성 탐지 | 결정론 |
| Topology / Intent Model | 중간 모델 생성, source/confidence 부여 | 결정론 |
| Deployment Profile Merge | 환경값 병합, unresolved 재계산 | 결정론 |
| LLM Provider Interface | 모델 백엔드 추상화 (local runtime / OpenAI-compatible) | 계약 고정 |
| Question Generator / Repair Advisor | 질문 문안·충돌 설명·patch 제안 (schema-constrained) | LLM 보조 |
| Template Renderer | Intent → YAML 렌더링 | 결정론 |
| Kubernetes Validator | kubeconform/dry-run/linter/정책 | 결정론 |
| Deployment Checker | Pod Running/Ready 판정 | 결정론 |
| Smoke Test | 애플리케이션 가용성 판정 (Level 3) | 결정론 |
| Repair Loop | 오류 → patch → 재렌더 → 재검증 환류 | 규칙 우선 + LLM 보조 |

---

# 19. 결론

LLM에게 "이 Repository로 Kubernetes YAML을 만들어줘"라고 요청하는 접근보다 본 워크플로우가 안정적인 이유는 다음과 같다.

1. **결정론적 분석이 hallucination을 줄인다.** 파일 탐지·파싱·매핑을 코드가 수행하므로, 존재하지 않는 registry·도메인·credential이 결과물에 등장할 경로 자체가 차단된다.
2. **중간 모델이 결과를 재현 가능하게 만든다.** 같은 commit + 같은 Profile + 같은 규칙 버전은 같은 manifest를 생성하며, 모든 필드가 source/confidence로 추적된다. diff와 회귀 테스트가 가능해진다.
3. **Deployment Profile이 runtime gap을 처리한다.** GitHub 소스에 없는 값은 추측이 아니라 질문과 구조화된 입력으로 해소되며, 환경별(dev/stage/prod) 배포가 하나의 분석 결과에서 파생된다.
4. **템플릿 렌더링이 manifest 품질을 통제한다.** 산출물 품질이 모델의 그날 컨디션이 아니라 버전 관리되는 템플릿과 규칙에 의해 결정된다.
5. **Validation과 smoke test가 진짜 배포 준비 상태를 정의한다.** "생성됨(Level 0)"과 "Kubernetes가 이해함(Level 1)", "Pod가 뜸(Level 2)", "애플리케이션이 동작함(Level 3)"을 구분하고, 각 수준을 도구와 실제 배포 검증으로 확정하므로 거짓 성공이 없다.
6. **LLM은 유용하지만, 제약된 보조자로만 유용하다.** 요약·설명·질문 문안·오류 기반 수리 제안이라는 명확한 경계 안에서, schema-constrained output과 Provider 추상화(local runtime / OpenAI-compatible endpoint) 위에서 동작할 때 LLM은 파이프라인의 신뢰성을 해치지 않으면서 사용자 경험을 개선한다.

요약하면, 이 설계의 본질은 "LLM을 더 똑똑하게 쓰는 법"이 아니라 **"LLM이 몰라도 되는 것을 LLM에게 묻지 않는 구조"**를 만드는 것이다. Repository가 말해줄 수 있는 것은 파서가 읽고, 환경만 아는 것은 Deployment Profile이 공급하고, 아무도 모르는 것은 사용자에게 질문하며, 마지막 판정은 언제나 validator와 실제 클러스터가 내린다.
