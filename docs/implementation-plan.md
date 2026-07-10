# On-Prem LLM K8s Manifest 사전 분석 파이프라인 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `onprem-llm-k8s-manifest-preanalysis-workflow.md`(이하 "설계 문서")가 정의한 16단계 사전 분석 워크플로우 중 MVP 범위(설계 문서 17장)를 실행 가능한 CLI 파이프라인으로 구현한다.

**Architecture:** Repository를 결정론적으로 파싱해 중간 모델 체인(snapshot → inventory → component → runtime → dependency → intent)을 만들고, 템플릿 렌더링으로 manifest를 생성한 뒤 validator로 Level 1을 확정한다. LLM은 Provider Interface 뒤에서 질문 문안·요약·충돌 설명만 생성하며, LLM 없이도 파이프라인 전체가 완주된다.

**Tech Stack:** Python 3.11+, pydantic v2(중간 모델 + JSON Schema), Jinja2(템플릿 렌더링), PyYAML(ruamel 불필요 — 주석 없는 산출물), httpx(OpenAI-compatible 호출), typer(CLI), pytest(테스트), 외부 바이너리: `kubeconform`, `kubectl`(선택).

---

## Global Constraints

설계 문서에서 그대로 가져온 프로젝트 전역 제약. 모든 Task의 요구사항에 암묵적으로 포함된다.

- **P1 Parser before LLM**: 파일 탐지·파싱·탐지 규칙에 LLM 사용 금지. LLM은 중간 모델만 본다.
- **P2 Intermediate model before YAML**: repository_snapshot → artifact_inventory → component_model → runtime_model → dependency_model → kubernetes_intent 체인을 반드시 거친다. Repository → YAML 직행 금지.
- **P3 Template rendering only**: 최종 manifest는 버전 관리되는 템플릿 렌더링 결과만 허용. LLM free-form YAML 금지.
- **P4 Validation before delivery**: YAML 문법 → kubeconform → `kubectl apply --dry-run=client` 통과 후에만 전달.
- **P5 Ask instead of guess**: 확인 불가 값은 `unresolved` + 질문 생성. 기본값으로 조용히 채우지 않는다.
- **P6 모든 추출 필드는 `value / source / confidence(high|medium|low|none)`를 갖는다.** confidence 등급은 규칙이 부여하며 LLM이 부여할 수 없다.
- **P8 LLM Provider 추상화**: 파이프라인은 Provider Interface의 4개 연산(`generate_question_wording`, `explain_conflict`, `suggest_patch`, `summarize`)만 사용.
- **P9 Secret 값은 LLM으로도, 산출물로도 흐르지 않는다.** 이름·출처·분류 근거만 기록. placeholder 값은 `__REPLACE_ME__` 고정.
- **P10 재현성**: 동일 commit + 동일 Profile + 동일 rules_version → 동일 산출물. LLM 호출은 `temperature: 0`, `top_p: 1`.
- **소스 우선순위(설계 문서 10.2)**: Deployment Profile > 기존 K8s manifest > Helm/Kustomize > Compose > Dockerfile > CI/CD > package 파일 > 앱 설정 > 소스 스캔 > 프레임워크 관례(항상 low).
- **산출물 파일명**: 설계 문서 16장의 `00-repository-snapshot.yaml` ~ `11-smoke-test-plan.yaml` 명명을 그대로 사용.
- **unresolved placeholder 문자열**: manifest 내 `__UNRESOLVED__`, Secret 값 `__REPLACE_ME__` (설계 문서 6장, 7.2절 표기 준수).

---

# 1. Architecture Plan

## 1.1 파이프라인과 모듈 경계

```text
                        ┌──────────────────────────────────────────────┐
 repo URL/path, ref ──▶ │  [A] Deterministic Analyzer                  │
 (선택) profile.yaml    │   scanner → parsers → detector → builders    │
                        │   Step 0~6, 8 + Step 9 질문 골격 + Step 10 병합│
                        └──────────────┬───────────────────────────────┘
                                       │ 중간 모델 (pydantic 객체)
                        ┌──────────────▼──────────────┐   ┌───────────────────────────┐
                        │  [B] LLM Provider Interface │◀──│ OpenAI-compatible endpoint │
                        │   질문 문안 / 요약 / 충돌 설명  │   │ (vLLM, TGI, gateway, …)    │
                        │   실패 시 기계 생성 문구 폴백    │   └───────────────────────────┘
                        └──────────────┬──────────────┘
                                       │ 문안이 채워진 Intent/질문 모델
                        ┌──────────────▼──────────────┐
                        │  [C] Template Renderer      │  Step 11
                        │   Jinja2 + 렌더 정책(14장)   │
                        └──────────────┬──────────────┘
                                       │ 08-generated-manifests/
                        ┌──────────────▼──────────────┐
                        │  [D] Validator              │  Step 12
                        │   yaml → kubeconform → dry-run│
                        └──────────────┬──────────────┘
                                       ▼
                          repo-analysis-output/ (00~11)
```

네 모듈의 결합 규칙:

| 모듈 | 의존 대상 | 의존 금지 |
|---|---|---|
| [A] Analyzer | `models/` 만 | LLM Provider, Renderer, Validator를 import하지 않는다 |
| [B] LLM Provider | `models/`의 입출력 계약 타입만 | Analyzer 내부, 파일시스템 |
| [C] Renderer | `models/`(Intent, Profile)만 | Analyzer 내부, LLM |
| [D] Validator | 렌더링된 파일 경로만 | 위 셋 전부 |
| Orchestrator(CLI) | 위 4개 전부 | — |

이 결합 규칙 덕에: (1) LLM endpoint가 없어도 Analyzer→Renderer→Validator가 완주하고, (2) 각 모듈을 독립적으로 단위 테스트할 수 있으며, (3) Provider 교체가 설정 변경만으로 가능하다(P8).

## 1.2 핵심 데이터 타입: Tracked 필드

P6를 타입 수준에서 강제하는 것이 이 설계의 중심이다. 모든 추출 값은 아래 제네릭을 통과한다.

```python
# src/preanalyzer/models/fields.py
class Confidence(str, Enum):
    HIGH = "high"; MEDIUM = "medium"; LOW = "low"; NONE = "none"

class Conflict(BaseModel):
    value: Any
    source: str

class Tracked(BaseModel, Generic[T]):
    value: T | None = None
    source: str | None = None          # "dockerfile_expose", "pom.xml", "compose_ports", ...
    confidence: Confidence = Confidence.NONE
    unresolved: bool = False
    profile_field: str | None = None   # unresolved일 때 Profile의 대응 필드 경로
    conflicts: list[Conflict] = []
    question_ref: str | None = None    # 질문 생성 시 역참조 (예: "Q-PORT-001")
    resolved_by: str | None = None     # "deployment_profile" 등 (병합 후 기록)
```

불변식(validator로 강제): `unresolved=True`이면 `confidence=NONE`이고 `value`가 확정값이 아니다. `value`가 있으면 `source`와 `confidence`가 반드시 있다. — 이 불변식이 "source/confidence 없는 필드" 자체를 생성 불가능하게 만든다.

## 1.3 중간 모델 체인 (설계 문서 11장 스키마의 pydantic화)

| 모델 | 파일 | 산출물 |
|---|---|---|
| `RepositorySnapshot` | `models/snapshot.py` | `00-repository-snapshot.yaml` |
| `ArtifactInventory` | `models/inventory.py` | `01-artifact-inventory.yaml` |
| `ComponentModel` | `models/component.py` | `02-component-model.yaml` |
| `RuntimeModel` | `models/runtime.py` | `03-runtime-model.yaml` |
| `DependencyModel` (+ `EnvClassification`) | `models/dependency.py` | `04-dependency-model.yaml` |
| `KubernetesIntent` | `models/intent.py` | `05-kubernetes-intent.yaml` |
| `UnresolvedQuestions` | `models/questions.py` | `06-unresolved-questions.yaml` |
| `DeploymentProfile` (+ template 생성기) | `models/profile.py` | `07-deployment-profile.template.yaml` |
| `ValidationReport` | `models/report.py` | `09-validation-report.yaml` |

각 모델은 `model_json_schema()`로 JSON Schema를 내보내며, Profile 입력 검증(Step 10의 "잘못된 Profile은 병합 전 거부")에 그 스키마를 사용한다.

## 1.4 결정론 보장 설계

- **시각 주입**: `analyzed_at`은 orchestrator가 주입하는 `clock: Callable[[], datetime]`에서 얻는다. 테스트는 고정 clock을 주입해 산출물 byte-level 비교를 한다.
- **정렬**: 파일 스캔·컴포넌트 목록·질문 목록은 항상 경로/ID 기준 정렬 후 직렬화한다(파일시스템 순회 순서 비의존).
- **버전 스탬프**: `analyzer_version`(패키지 버전), `rules_version`(탐지 규칙 테이블 + 템플릿 세트의 버전 상수, `src/preanalyzer/rules_version.py`의 단일 문자열)을 snapshot과 manifest annotation에 기록.
- **LLM 비결정성 격리**: LLM 산출 문안은 질문의 `question`(자연어) 필드에만 들어가고, 질문의 `id/field/answer_type/blocking_level/candidates`는 결정론 영역이다. 재현성 회귀 테스트는 LLM 필드를 제외하고 비교하거나 NullProvider로 실행한다.

## 1.5 디렉터리 구조 (전체 파일 맵)

```text
pyproject.toml
src/preanalyzer/
  __init__.py
  rules_version.py            # RULES_VERSION = "2026.07" 단일 상수
  cli.py                      # typer 엔트리포인트: analyze / merge-profile / render / validate
  config.py                   # AnalyzerConfig, LLMProviderConfig 로딩(YAML + env)
  pipeline.py                 # Orchestrator: 단계 연결, 산출물 쓰기, clock 주입
  models/
    fields.py                 # Tracked, Confidence, Conflict
    snapshot.py  inventory.py  component.py  runtime.py
    dependency.py  intent.py  questions.py  profile.py  report.py
  analyzer/                   # ── [A] Deterministic Analyzer ──
    scanner.py                # Step 0~1: snapshot 고정 + artifact inventory
    parsers/
      dockerfile.py           # EXPOSE/CMD/ENTRYPOINT/USER/base image
      compose.py              # services/ports/env/volumes/depends_on (Kompose 매핑)
      maven.py                # pom.xml: packaging, modules, 의존성
      nodejs.py               # package.json: scripts, dependencies
      python_pkg.py           # pyproject.toml / requirements.txt
    detector.py               # Step 4: 규칙 테이블 (파일 지표 → 언어/프레임워크/빌드)
    component_builder.py      # Step 3: 배포 단위 분해 + role 태깅
    runtime_builder.py        # Step 5: 포트/커맨드/헬스 endpoint/런타임 버전
    env_classifier.py         # 7.3절 6분류 + Secret 마스킹
    dependency_builder.py     # Step 6: 의존성 엣지, PVC 후보
    intent_builder.py         # Step 7~8: topology + K8s Intent (LLM 요약은 훅으로만)
    priority.py               # 10장: 소스 우선순위, 충돌 보존, confidence 강등
    question_builder.py       # Step 9: 질문 골격 기계 생성 + 중복 병합
    profile_merge.py          # Step 10: Profile 검증→병합→unresolved 재계산
  llm/                        # ── [B] LLM Provider Interface ──
    provider.py               # LLMProvider Protocol + 입출력 계약 타입
    openai_compatible.py      # httpx 기반 구현 (MVP 유일 구현체)
    null_provider.py          # 항상 None 반환 → 기계 생성 문구 폴백 경로
    contracts/                # 용도별 output contract JSON Schema (버전 관리)
      question_wording.schema.json
      conflict_explanation.schema.json
      summary_text.schema.json
      patch_suggestion.schema.json   # 인터페이스 고정용. MVP에서 구현 안 함
  renderer/                   # ── [C] Template Renderer ──
    engine.py                 # TemplateRenderer: Intent(+Profile) → manifest 파일들
    policy.py                 # 14장 렌더 정책: 보류/placeholder 판단, label 세트
    templates/
      deployment.yaml.j2  service.yaml.j2  ingress.yaml.j2
      configmap.yaml.j2   secret.placeholder.yaml.j2  serviceaccount.yaml.j2
  validator/                  # ── [D] Validator ──
    pipeline.py               # ValidationPipeline: 체인 실행 + report 누적
    yaml_check.py  kubeconform.py  dry_run.py
  output/
    writer.py                 # 중간 모델 → 00~11 파일 트리 직렬화 (정렬·anchor 없는 YAML)
tests/
  unit/                       # 모듈별 단위 테스트 (fixtures 사용, 네트워크 불필요)
  acceptance/                 # 17.4 완료 판정 자동화 (fixture repo 스냅샷 기반)
  integration/                # 실제 GitHub clone (pytest -m integration, 네트워크 필요)
  fixtures/
    repos/jpetstore-like/     # 5.1을 재현한 최소 fixture (pom.xml, webapp 구조)
    repos/fastapi-fullstack-like/  # 5.2 재현 (compose, backend/frontend, .env)
    repos/node-express-like/  # 5.6 baseline (Dockerfile EXPOSE/CMD)
    profiles/dev-profile.yaml
    llm_responses/            # 녹화된 provider 응답 (contract 검증용)
```

fixture repo를 두는 이유: 단위·수용 테스트가 네트워크와 upstream 변경에 의존하면 회귀 테스트가 비결정적이 된다(P10 위반). 실제 repo는 `integration` 마커로 분리해 주기적으로만 돌린다.

## 1.6 모듈별 공개 인터페이스

**[A] Deterministic Analyzer** — orchestrator가 호출하는 단계 함수들. 모두 순수 함수에 가깝게(입력 모델 → 출력 모델), 파일 I/O는 scanner와 writer에만 둔다.

```python
scanner.snapshot(repo: Path, url: str | None, ref: str | None, clock) -> RepositorySnapshot
scanner.build_inventory(repo: Path, snapshot) -> ArtifactInventory
component_builder.build(inventory, parsed_artifacts) -> ComponentModel
detector.detect(component, inventory) -> DetectionResult      # language/framework/build (Tracked)
runtime_builder.build(components, parsed_artifacts) -> RuntimeModel
env_classifier.classify(env_refs: list[EnvRef]) -> EnvClassification
dependency_builder.build(components, parsed_artifacts, env_cls) -> DependencyModel
intent_builder.build(components, runtime, deps, env_cls) -> KubernetesIntent
question_builder.build(intent, env_cls) -> UnresolvedQuestions   # 문안 없는 골격
profile_merge.merge(intent, questions, profile: DeploymentProfile) -> MergeResult
    # MergeResult = 갱신된 intent + 축소된 questions + conflicts: list[MergeConflict] + ready_for_level2: bool
```

**[B] LLM Provider Interface** — 파이프라인이 아는 유일한 LLM 표면.

```python
class LLMProvider(Protocol):
    def generate_question_wording(self, draft: QuestionDraft) -> QuestionWording | None: ...
    def explain_conflict(self, ctx: ConflictContext) -> ConflictExplanation | None: ...
    def summarize(self, topology: TopologySummaryInput) -> SummaryText | None: ...
    def suggest_patch(self, evidence: ErrorEvidence) -> PatchSuggestion | None: ...
    # suggest_patch는 인터페이스만 고정(12.7 벤더 종속 회피). MVP 구현체는 NotImplementedError.
```

계약: 반환값은 contract JSON Schema 검증을 통과한 것만. 검증 실패 → 실패 사유 첨부 1회 재시도 → 재실패 시 `None` 반환(12.6). `None`이면 호출측이 기계 생성 기본 문구를 쓴다. 입력 타입(`QuestionDraft` 등)에는 Secret 값 필드가 아예 존재하지 않는다(P9를 타입으로 강제).

**[C] Template Renderer**

```python
class TemplateRenderer:
    def render(self, intent: KubernetesIntent, profile: DeploymentProfile | None,
               allow_placeholders: bool = False) -> RenderResult
# RenderResult: files: dict[str, str], deferred: list[DeferredResource(reason)], achieved_level_cap: int
```

렌더 정책(14장)은 `policy.py`에 데이터로: 리소스별 "필수 필드 목록 + 미해결 시 행동(defer|placeholder|omit-field)". `allow_placeholders=False`(기본)면 unresolved 잔존 리소스는 렌더 보류 + 사유 기록.

**[D] Validator**

```python
class ValidationPipeline:
    def run(self, manifest_dir: Path, k8s_version: str = "1.29") -> ValidationReport
```

체인: `yaml_check` → `kubeconform`(subprocess, `-kubernetes-version` 지정) → `dry_run`(client). 외부 바이너리 부재 시 해당 단계 `skipped: tool_not_found`로 기록하고 계속 진행 — 단, acceptance 테스트 환경에는 kubeconform을 필수 설치한다. `achieved_level` 판정: placeholder 없이 렌더 + ①~③ 전부 pass → 1, placeholder 렌더 → 0.

## 1.7 CLI (Orchestrator)

```text
preanalyzer analyze <repo-url-or-path> [--ref REF] [--profile profile.yaml]
                    [--out repo-analysis-output/] [--llm-config llm.yaml] [--no-llm]
preanalyzer merge-profile <analysis-dir> --profile profile.yaml   # 재분석 없이 Step 10~12 재실행
preanalyzer validate <manifest-dir> [--k8s-version 1.29]
```

`--no-llm`은 NullProvider를 주입한다. `analyze`는 Step 0→1→(2:compose)→3→4→5→6→8→9→(10 if profile)→11→12를 순서대로 실행하고 16장 산출물 트리를 쓴다.

---

# 2. MVP 범위 확정

설계 문서 17장을 구현 단위로 자른 것. **여기 없는 것은 만들지 않는다(YAGNI).**

## 2.1 포함

| 축 | MVP 범위 |
|---|---|
| 입력 artifact | Dockerfile, docker-compose.yml(+override 1개), 단순 디렉터리 모노레포. 기존 K8s manifest/Helm/Kustomize는 **inventory에 존재만 기록**(파싱은 2단계) |
| 언어/빌드 detector | Java+Maven(`pom.xml`, multi-module 판별 포함), Node.js+npm(`package.json`), Python(pip `requirements.txt` / poetry·uv `pyproject.toml`) |
| 프레임워크 규칙 | spring-boot(medium), nextjs/express(high), fastapi(high) — 4.5절 규칙 테이블의 해당 행만 |
| 생성 리소스 | Deployment, Service, ConfigMap, Secret placeholder, Ingress(후보), ServiceAccount |
| LLM 연동 | OpenAI-compatible provider 1종 + NullProvider. 연산: question_wording, conflict_explanation, summary_text |
| Validation | YAML 파서 + kubeconform + `kubectl apply --dry-run=client`(kubectl 있을 때) |
| 산출물 | `00`~`09` + `10-deployment-readiness-checklist.md` + `11-smoke-test-plan.yaml` |
| Profile | 스키마 정의(8.2절 전체) + JSON Schema 검증 + 병합(8.4절) + 질문 재계산 |

## 2.2 제외 (2단계 로드맵)

- Helm/Kustomize **입력 파싱**, Helm chart **출력**
- Go/.NET detector, Buildpacks 빌드 실행, 소스 코드 내 포트 상수 스캔(env 참조 스캔은 포함)
- HPA/PVC/StatefulSet 자동 생성 — 볼륨·autoscaling 신호는 질문으로만 라우팅
- Step 13(Deployment Check)·Step 14(Smoke Test) **실행** — smoke-test-plan.yaml과 checklist **생성까지만**
- Step 15 Repair Loop 자동화, `suggest_patch` 구현
- 기존 K8s manifest의 역방향 Intent 도출 (5.3 microservices-demo 시나리오)

## 2.3 MVP 목표 수준

- Repository-only 모드: **Level 1** 확정 + 부분적 Level 2(빌드 전략 판정까지)
- Deployment Profile 모드: **Level 2 진입 가능 상태**(required unresolved = 0인 manifest 세트 + checklist)
- `09-validation-report.yaml`에 `target_level` / `achieved_level` 분리 기록

---

# 3. 구현 Task 분해

> 사용자 지시("아직 코드는 작성하지 마")에 따라 본 계획에는 인터페이스 시그니처와 테스트 명세까지만 담고, 함수 본문 구현은 실행 단계로 미룬다. 각 Task는 TDD로 진행한다: 명세된 테스트를 먼저 작성 → 실패 확인 → 최소 구현 → 통과 → 커밋.

### Task 0: 프로젝트 스캐폴드 + Tracked 필드 모델

**Files:**
- Create: `pyproject.toml`, `src/preanalyzer/__init__.py`, `src/preanalyzer/rules_version.py`, `src/preanalyzer/models/fields.py`
- Test: `tests/unit/test_fields.py`

**Interfaces:**
- Produces: `Tracked[T]`, `Confidence`, `Conflict` (1.2절 정의 그대로) — 이후 모든 Task가 사용.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_fields.py`:
  - `test_value_requires_source_and_confidence`: `Tracked(value=8080)` 생성 시 `ValidationError` (source/confidence 누락).
  - `test_unresolved_forces_none_confidence`: `Tracked(unresolved=True, confidence=Confidence.HIGH)` → `ValidationError`.
  - `test_serialization_roundtrip`: `Tracked(value=8080, source="dockerfile_expose", confidence=Confidence.HIGH)` → `model_dump()` → 재생성 → 동일.
- [ ] **Step 2: `pytest tests/unit/test_fields.py -v` 실행, 전부 FAIL 확인** (모듈 없음)
- [ ] **Step 3: `fields.py` 최소 구현** (pydantic `model_validator`로 불변식 강제)
- [ ] **Step 4: 테스트 통과 확인**
- [ ] **Step 5: 커밋** — `feat: project scaffold + Tracked field model enforcing source/confidence invariant`

### Task 1: 중간 모델 스키마 전체 정의

**Files:**
- Create: `src/preanalyzer/models/{snapshot,inventory,component,runtime,dependency,intent,questions,profile,report}.py`
- Test: `tests/unit/test_models_schema.py`

**Interfaces:**
- Consumes: `Tracked[T]`
- Produces: 1.3절 표의 9개 pydantic 모델. 필드 구성은 설계 문서 11.1~11.9의 YAML 예시를 1:1로 타입화한다(예: `KubernetesIntentComponent.workload.container.port: Tracked[int]`). `DeploymentProfile`은 8.2절 스키마 전체(`target_cluster`, `exposure`, `external_dependencies`, `runtime_config`, `resource_policy`, `smoke_test`). `UnresolvedQuestion`은 `id, field, question, reason, answer_type, candidates, blocking_level(application_runnable|feature_partial), profile_field`.

- [ ] **Step 1: 실패하는 테스트 작성** — 설계 문서 11장의 예시 YAML 9개를 fixture 문자열로 넣고, 각 모델이 그것을 파싱·재직렬화(roundtrip)하는지 검증. 추가로 `test_profile_json_schema_rejects_unknown_keys`: `deployment_profile.target_clstr`(오타) 입력 → 검증 실패.
- [ ] **Step 2: FAIL 확인 → Step 3: 모델 구현 → Step 4: PASS 확인**
- [ ] **Step 5: 커밋** — `feat: intermediate model chain (11장 스키마의 pydantic 정의)`

### Task 2: Scanner (Step 0~1) + 테스트 fixture repo 3종

**Files:**
- Create: `src/preanalyzer/analyzer/scanner.py`, `tests/fixtures/repos/{jpetstore-like,fastapi-fullstack-like,node-express-like}/`
- Test: `tests/unit/test_scanner.py`

**Interfaces:**
- Produces: `snapshot(repo, url, ref, clock) -> RepositorySnapshot`, `build_inventory(repo, snapshot) -> ArtifactInventory`

fixture repo 구성 (실제 upstream 구조의 최소 재현):
- `jpetstore-like/`: `pom.xml`(war packaging, 모듈 없음), `src/main/webapp/WEB-INF/web.xml`, `src/main/resources/database/*.sql`, README. **Dockerfile 없음.**
- `fastapi-fullstack-like/`: `docker-compose.yml`(backend/frontend/db 서비스, traefik 라벨, depends_on, `POSTGRES_PASSWORD` env), `backend/Dockerfile`(EXPOSE 8000, uvicorn CMD), `backend/pyproject.toml`(fastapi 의존), `frontend/Dockerfile`, `frontend/package.json`(react/vite), `.env`(개발용 더미 비밀번호 `changethis` 포함 — 마스킹 검증용).
- `node-express-like/`: `Dockerfile`(EXPOSE 3000, `CMD ["node","server.js"]`), `package.json`(express, `scripts.start`).

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_snapshot_is_deterministic`: 고정 clock으로 2회 실행 → `model_dump()` 완전 동일.
  - `test_inventory_detects_artifacts_per_fixture`: fixture별 기대 inventory (jpetstore-like: `build_files=[pom.xml]`, `container_files=[{dockerfile, present: false}]` — **부재의 명시적 기록** 검증).
  - `test_inventory_detects_k8s_manifest_by_content`: `apiVersion`+`kind` 가진 YAML을 `kubernetes_manifests`로 분류.
  - `test_excluded_patterns`: `.git/`, `node_modules/` 하위 파일이 inventory에 없음.
  - `test_inventory_sorted`: 항목이 경로 오름차순.
- [ ] **Step 2: FAIL → Step 3: 구현 → Step 4: PASS → Step 5: 커밋** — `feat: repository scanner (Step 0-1) + fixture repos`

### Task 3: Artifact Parsers (Dockerfile / Compose / package 파일)

**Files:**
- Create: `src/preanalyzer/analyzer/parsers/{dockerfile,compose,maven,nodejs,python_pkg}.py`
- Test: `tests/unit/test_parsers.py`

**Interfaces:**
- Produces: 각 parser는 `parse(path: Path) -> ParsedX` (예: `ParsedDockerfile(expose_ports: list[Tracked[int]], cmd: Tracked[str], entrypoint: Tracked[str], base_image: Tracked[str], user: Tracked[str])`, `ParsedCompose(services: list[ComposeService])` — `ComposeService(name, image, build_context, ports, environment, volumes, depends_on, labels)`). 모든 추출값의 source 문자열 규약: `dockerfile_expose`, `dockerfile_cmd`, `compose_ports`, `compose_environment`, `compose_depends_on`, `pom.xml`, `package.json`, `pyproject.toml`.

- [ ] **Step 1: 실패하는 테스트 작성** (fixture repo의 실제 파일 대상):
  - Dockerfile: EXPOSE 8000 → `Tracked(8000, "dockerfile_expose", HIGH)`; **EXPOSE 없는 Dockerfile → `expose_ports == []`이고 어떤 포트도 만들어내지 않음**(5.6 실패 모드).
  - Compose: fastapi fixture에서 서비스 3개, `depends_on` 보존, traefik 라벨 추출, `POSTGRES_PASSWORD` env **이름은 있고 값은 파서 출력에 원문 그대로 있으되 이후 단계에서 마스킹됨을 주석으로 명시**(마스킹은 Task 5 책임).
  - maven: war packaging 추출, `<modules>` 없으면 `is_multi_module == False`(5.1 검증 항목).
  - nodejs/python_pkg: 의존성 목록과 scripts 추출, fastapi/react 의존 감지 입력 제공.
- [ ] **Step 2~4: FAIL → 구현 → PASS**
- [ ] **Step 5: 커밋** — `feat: deterministic artifact parsers (Dockerfile/Compose/package files)`

### Task 4: Detector (Step 4) + Component Builder (Step 3)

**Files:**
- Create: `src/preanalyzer/analyzer/detector.py`, `src/preanalyzer/analyzer/component_builder.py`
- Test: `tests/unit/test_detector.py`, `tests/unit/test_component_builder.py`

**Interfaces:**
- Consumes: `ArtifactInventory`, parsers 출력
- Produces: `detect(component, inventory) -> DetectionResult(language, framework, build_strategy, build_command: 모두 Tracked)`; `component_builder.build(...) -> ComponentModel`
- detector 규칙 테이블은 4.5절 예시를 데이터(list of rule)로 구현: `pom.xml→java/maven(high)`, `package.json→nodejs(high)`, `dependencies.next→nextjs(high)`, `pyproject.toml[fastapi]→fastapi(high)`, `application.yml→spring-boot(medium)`, `requirements.txt|pyproject.toml→python(high)`. 빌드 커맨드: maven→`mvn -B package`, npm→`npm ci && npm run build`(scripts.build 존재 시). Dockerfile 존재→`build_strategy: dockerfile(high)`, 부재→`dockerfile_needed` 후보 제시(**미제시가 5.1 실패 모드 (a)**).
- component 분해 우선순위(Step 3): ① Compose 서비스 단위 → ② 빌드 파일 경계 → ③ Dockerfile 위치. Compose의 DB/캐시/프록시 이미지(postgres, mysql, redis, traefik, nginx 패턴 테이블)는 `role: dependency|infrastructure`로 태깅.

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_jpetstore_single_java_component`: 컴포넌트 1개, language java(high, source pom.xml), build maven, build_command `mvn -B package`, build_strategy `dockerfile_needed`.
  - `test_fastapi_three_components_with_roles`: backend(application), frontend(application), db(**dependency**), traefik 라벨은 컴포넌트를 만들지 않음(5.2 실패 모드 (a)).
  - `test_detector_rule_priority`: 한 디렉터리에 package.json+Dockerfile → nodejs + dockerfile 전략.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: rule-based detector + component decomposition`

### Task 5: Runtime Builder (Step 5) + Env Classifier + Dependency Builder (Step 6) + 소스 우선순위

**Files:**
- Create: `src/preanalyzer/analyzer/{runtime_builder,env_classifier,dependency_builder,priority}.py`
- Test: `tests/unit/test_runtime_builder.py`, `tests/unit/test_env_classifier.py`, `tests/unit/test_priority.py`

**Interfaces:**
- Produces:
  - `runtime_builder.build(...) -> RuntimeModel` — 포트/시작 커맨드/헬스 endpoint 후보/런타임 버전. 프레임워크 관례값(spring 8080, uvicorn 8000)은 관례 DB(딕셔너리)에서 **항상 `confidence: LOW`** 로만.
  - `env_classifier.classify(env_refs) -> EnvClassification` — 7.3절 6분류. Secret 판정 이름 패턴: `PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|PRIVATE`(대소문자 무시). **secret candidate의 value는 분류 시점에 폐기되고 어떤 출력 모델에도 실리지 않는다** — `SecretCandidate` 타입에 value 필드 자체가 없음.
  - `priority.resolve(candidates: list[Tracked[T]]) -> Tracked[T]` — 10.2 우선순위 적용, 충돌 시 상위 채택 + `conflicts` 보존 + confidence 1단계 강등 + `question_ref` 요청 플래그(10.3).
- Consumes: Task 3 parsers, Task 4 component model.

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_port_conflict_downgrades_and_preserves`: dockerfile 8080(high) vs 앱설정 8081(medium) → value 8080, confidence **medium**, `conflicts=[{8081, application.yml}]`, 질문 플래그 on (10.3 예시 그대로).
  - `test_convention_port_is_low_confidence`: spring-boot 프레임워크 + 포트 근거 없음 → 8080 후보 `LOW` (5.4 실패 모드 (c) 방지). jpetstore(war) → 포트 **unresolved** + 관례 8080은 candidates에만.
  - `test_env_six_way_classification`: 7.3절 예시 입력 → configmap 2 / secret 2(`DB_PASSWORD`, `JWT_SECRET`) / required 1(`DB_HOST`, blocking `application_runnable`) / optional 1(`SMTP_HOST`) 재현.
  - `test_secret_value_never_serialized`: `.env`의 `changethis`가 `EnvClassification.model_dump_json()` 결과에 부재.
  - `test_depends_on_becomes_internal_edge` / `test_database_url_becomes_external_dep`: 11.5 예시 형태 재현.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: runtime/env/dependency analysis with source priority and secret masking`

### Task 6: Intent Builder (Step 7~8)

**Files:**
- Create: `src/preanalyzer/analyzer/intent_builder.py`
- Test: `tests/unit/test_intent_builder.py`

**Interfaces:**
- Consumes: `ComponentModel`, `RuntimeModel`, `DependencyModel`, `EnvClassification`
- Produces: `build(...) -> KubernetesIntent` — 컴포넌트→Deployment 의도, 확인된 포트→Service 의도, 진입점(compose 라벨/frontend/단일 노출 컴포넌트)→Ingress 후보(`host: unresolved, profile_field: exposure.host`), env 분류→ConfigMap/Secret placeholder 의도, `image.registry/tag: unresolved(profile_field: target_cluster.image_registry)`, `replicas: Tracked(1, "default_dev", LOW)`, `resources: unresolved(profile_field: resource_policy)`. `role: dependency` 컴포넌트(예: compose의 postgres)는 워크로드 의도를 만들지 않고 `mode: external|in-cluster` **분기 질문 신호**만 남긴다(5.2 실패 모드 (b) 방지). topology 요약문 필드는 비워두고 LLM 훅 지점만 마련.

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_intent_matches_11_6_shape`: fastapi fixture → 11.6 예시 구조(backend-api: Deployment+Service+Ingress 후보+configmap/secret 키) 재현.
  - `test_db_component_not_rendered_as_workload`: db는 intent에 workload 없음 + 분기 질문 신호 존재.
  - `test_every_leaf_field_is_tracked`: intent 트리를 재귀 순회 — 모든 리프가 `Tracked`이고 불변식 충족(P6의 구조적 검증, 17.4-(b)의 기반).
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: Kubernetes Intent Model builder`

### Task 7: Question Builder (Step 9) + Profile Template 생성

**Files:**
- Create: `src/preanalyzer/analyzer/question_builder.py`
- Test: `tests/unit/test_question_builder.py`

**Interfaces:**
- Consumes: `KubernetesIntent`, `EnvClassification`
- Produces: `build(intent, env_cls) -> tuple[UnresolvedQuestions, DeploymentProfileTemplate]` — unresolved/low-confidence 필드 → 질문(id 규약 `Q-<도메인>-<순번>`: Q-REG/Q-NS/Q-ING/Q-DB/Q-PORT/…), **중복 병합**(여러 컴포넌트의 registry → 단일 Q-REG-001), `question` 문안은 기계 생성 기본 문구(예: `"'{field}' 값을 확인할 수 없습니다. 값을 지정해 주세요."`)로 채움 — LLM은 이후 이 문구를 다듬을 뿐. Profile template은 질문의 `profile_field`들을 빈 값 + `# Q-xxx` 주석으로 배치(11.8 형태).

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_registry_question_merged_across_components`: fastapi fixture(컴포넌트 2개 렌더 대상) → registry 질문 정확히 1개.
  - `test_blocking_levels`: DB host → `application_runnable`, SMTP류 → `feature_partial`.
  - `test_question_ids_deterministic`: 2회 실행 → 동일 id 순서.
  - `test_profile_template_covers_all_questions`: 모든 질문의 `profile_field`가 template에 존재.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: unresolved question generation + profile template`

### Task 8: Profile Merge (Step 10)

**Files:**
- Create: `src/preanalyzer/analyzer/profile_merge.py`, `tests/fixtures/profiles/dev-profile.yaml` (8.2절 예시값)
- Test: `tests/unit/test_profile_merge.py`

**Interfaces:**
- Consumes: `KubernetesIntent`, `UnresolvedQuestions`, `DeploymentProfile`
- Produces: `merge(...) -> MergeResult(intent, questions, conflicts: list[MergeConflict], ready_for_level2: bool)` — `ready_for_level2`는 병합 후 `blocking_level: application_runnable` 질문이 0건일 때 True. Profile 값이 unresolved 필드를 채우며 `resolved_by: deployment_profile` 기록. Profile 값이 repo의 HIGH confidence 값과 모순 → 덮어쓰되 `MergeConflict` 생성(validation_report로 전달). 잘못된 스키마의 Profile은 `ProfileValidationError`로 병합 전 거부. 병합 후 questions 재계산.

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_profile_resolves_registry_and_host`: dev-profile 적용 → Q-REG/Q-ING 질문 소멸, intent의 registry/host가 `resolved_by: deployment_profile`.
  - `test_profile_conflict_with_high_confidence_warns`: profile port 9000 vs dockerfile 8000(high) → 값은 9000, `MergeConflict` 1건.
  - `test_invalid_profile_rejected_before_merge`.
  - `test_blocking_zero_gate`: required 질문 0이 되면 `MergeResult.ready_for_level2 == True`.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: deployment profile validation and merge`

### Task 9: Template Renderer (Step 11)

**Files:**
- Create: `src/preanalyzer/renderer/{engine,policy}.py`, `src/preanalyzer/renderer/templates/*.j2` (deployment/service/ingress/configmap/secret.placeholder/serviceaccount)
- Test: `tests/unit/test_renderer.py`

**Interfaces:**
- Consumes: `KubernetesIntent`, `DeploymentProfile | None`
- Produces: 1.6절 `TemplateRenderer.render(...)` 시그니처. 렌더 정책(14장): resources 미공급 시 **필드 생략**; Ingress는 host 공급 시에만 렌더; Secret placeholder 값은 `__REPLACE_ME__`, Profile `secret_refs` 공급 시 placeholder 파일 대신 `valueFrom.secretKeyRef` 전환; namespace 하드코딩 금지; 공통 label 3종 + 메타데이터 annotation(commit SHA, analyzer/rules 버전, achieved_level) 삽입; unresolved 잔존 리소스는 기본 defer, `allow_placeholders=True`면 `__UNRESOLVED__` + Level 0 캡.

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_render_defers_ingress_without_host` / `test_render_ingress_with_profile_host`.
  - `test_no_resources_block_when_policy_missing`: resources 키 자체가 YAML에 없음(임의 수치 금지).
  - `test_secret_placeholder_values_are_replace_me` / `test_secret_refs_switch_to_secretKeyRef_and_drop_placeholder_file`.
  - `test_labels_and_metadata_annotations_present`.
  - `test_snapshot_stability`: fixture intent → 렌더 결과가 저장된 golden 파일과 byte 동일(템플릿 변경 시 rules_version 올리고 golden 갱신 — 14장 스냅샷 테스트 정책).
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: template renderer with 14장 rendering policy`

### Task 10: Validator (Step 12)

**Files:**
- Create: `src/preanalyzer/validator/{pipeline,yaml_check,kubeconform,dry_run}.py`
- Test: `tests/unit/test_validator.py`

**Interfaces:**
- Produces: `ValidationPipeline.run(manifest_dir, k8s_version) -> ValidationReport` (11.9 형태: 단계별 결과, `dry_run.server: skipped(reason)`, `achieved_level`, `target_level`).

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_valid_manifests_reach_level1`: Task 9 golden 산출물 + kubeconform 설치 환경 → `achieved_level == 1`.
  - `test_broken_yaml_fails_at_syntax_stage`: 고의로 깨진 YAML → `yaml_syntax: fail`, 이후 단계 `skipped`.
  - `test_missing_tool_recorded_as_skipped`: PATH에서 kubeconform 제거(monkeypatch) → `skipped: tool_not_found`, 예외 없음.
  - `test_placeholder_manifests_capped_at_level0`.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: validation pipeline (yaml/kubeconform/dry-run) with level determination`

### Task 11: LLM Provider Interface + OpenAI-compatible 구현 + NullProvider

**Files:**
- Create: `src/preanalyzer/llm/{provider,openai_compatible,null_provider}.py`, `src/preanalyzer/llm/contracts/*.schema.json`, `src/preanalyzer/config.py`
- Test: `tests/unit/test_llm_provider.py` (httpx MockTransport 사용 — 실제 endpoint 불필요)

**Interfaces:**
- Produces: 1.6절 `LLMProvider` Protocol과 입출력 계약 타입(`QuestionDraft`, `QuestionWording`, `ConflictContext`, `ConflictExplanation`, `TopologySummaryInput`, `SummaryText`). `OpenAICompatibleProvider(config: LLMProviderConfig)` — 12.3 설정(`base_url, api_key_env, model, request_defaults{temperature: 0, top_p: 1, max_tokens, timeout_seconds}, output_contract`). `response_format: json_schema` 시도 → 미지원 응답이면 프롬프트 내 schema 강제로 폴백(13.6). system prompt는 `llm/prompts.py`에 버전 상수로 고정(12.4).

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_schema_valid_response_accepted`: mock이 contract 준수 JSON 반환 → `QuestionWording` 객체.
  - `test_invalid_then_valid_retry_once`: 1차 schema 위반 → 실패 사유 포함 재요청 1회 → 2차 성공 수용. 총 호출 2회 검증.
  - `test_double_failure_returns_none`: 2회 모두 위반 → `None` (재시도 추가 금지 — 12.6).
  - `test_temperature_zero_in_request_body`.
  - `test_api_key_from_env_only`: config 파일에 평문 키 넣으면 로딩 거부.
  - `test_input_types_have_no_secret_values`: `QuestionDraft` 등 입력 모델 필드 전수 검사 — secret value 계열 필드 부재(P9).
  - `test_null_provider_returns_none_everywhere`.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: LLM provider interface + OpenAI-compatible provider with schema-constrained output`

### Task 12: Orchestrator + Output Writer + CLI

**Files:**
- Create: `src/preanalyzer/pipeline.py`, `src/preanalyzer/output/writer.py`, `src/preanalyzer/cli.py`
- Test: `tests/unit/test_pipeline.py`

**Interfaces:**
- Consumes: Task 0~11의 전부
- Produces: `run_analysis(repo, ref, profile_path, out_dir, provider: LLMProvider, clock) -> AnalysisResult`; CLI 3개 커맨드(1.7절). writer는 16장 트리(00~09 + 10-checklist.md + 11-smoke-test-plan.yaml)를 쓰고, 질문 문안·checklist 문안·요약에 provider 결과를 반영하되 `None`이면 기계 생성 문구 유지. `10-deployment-readiness-checklist.md`는 11.10 구조(질문 id 역참조 포함), `11-smoke-test-plan.yaml`은 Profile의 `smoke_test` 필드 기반(Profile 없으면 헬스 endpoint 후보 기반 초안).

- [ ] **Step 1: 실패하는 테스트 작성**:
  - `test_full_pipeline_writes_all_outputs`: node-express-like + NullProvider → `00,01,02,03,04,05,06,07,08-generated-manifests/,09,10,11` 전부 존재.
  - `test_pipeline_without_llm_completes`: NullProvider로 예외 없이 완주, 질문 문안이 기계 생성 기본 문구.
  - `test_merge_profile_command_recomputes`: 산출물 디렉터리에 `merge-profile` → 05/06/08/09 갱신, 00~04 불변.
- [ ] **Step 2~4: FAIL → 구현 → PASS → Step 5: 커밋** — `feat: pipeline orchestrator, output writer, CLI`

### Task 13: Acceptance Suite (17.4 완료 판정 자동화)

**Files:**
- Create: `tests/acceptance/test_jpetstore_like.py`, `tests/acceptance/test_fastapi_fullstack_like.py`, `tests/acceptance/test_determinism.py`, `tests/acceptance/forbidden_values.py`
- Create: `tests/integration/test_real_repos.py` (`@pytest.mark.integration`)
- Test: 자체가 테스트

**Interfaces:**
- Consumes: `run_analysis` (Task 12)
- Produces: 4장(아래)의 acceptance criteria를 실행 가능한 회귀 스위트로.

- [ ] **Step 1: 4장의 AC를 테스트 코드로 작성, 실행하여 현재 상태 확인** (Task 0~12 완료 시 전부 PASS해야 함; FAIL 항목은 결함으로 수정)
- [ ] **Step 2: `pytest tests/ -m "not integration" -v` 전체 그린 확인**
- [ ] **Step 3: (네트워크 가능 환경) `pytest -m integration` — 실제 jpetstore-6, full-stack-fastapi-template clone 후 동일 AC 실행, 고정 commit SHA 핀 고정**
- [ ] **Step 4: 커밋** — `test: acceptance suite implementing MVP completion criteria (17.4)`

---

# 4. 테스트 Repository 기반 Acceptance Criteria

MVP 완료 판정(설계 문서 17.4)의 실행 가능한 정의. **AC-0 ~ AC-6이 모두 자동 테스트로 그린이면 MVP 완료다.** fixture repo로 상시 검증하고, 동일 검사를 고정 commit의 실제 repo에 integration 테스트로 재실행한다.

## AC-0. 공통 — 모든 대상 repo에서

| # | 기준 | 검증 방법 |
|---|---|---|
| AC-0.1 | 산출물 12종(00~09, 10-checklist, 11-smoke-plan) 생성 | 파일 존재 + 각 YAML이 대응 pydantic 모델로 파싱됨 |
| AC-0.2 | 모든 추출 필드에 source/confidence 존재 | 00~05 산출물을 재로드 후 `Tracked` 리프 전수 순회 — 불변식 위반 0건 |
| AC-0.3 | **금지 값 부재**: DB host, registry 주소, ingress host, 도메인이 추측으로 등장하지 않음 | `forbidden_values.py`: 산출물 전체를 스캔해 (a) Profile·repo 어디에도 근거 없는 hostname/FQDN/registry 패턴(`\b[\w-]+\.(com|io|local|net)\b` 등) 검출 시 실패, (b) `db.example.com`·`myregistry` 류 상투 값 블랙리스트 검출 시 실패 |
| AC-0.4 | Secret 값 유출 없음 | fixture `.env`의 더미 비밀번호 문자열이 **모든** 산출물 파일에서 grep 0건; secret placeholder의 모든 값 == `__REPLACE_ME__` |
| AC-0.5 | kubeconform 통과 | 렌더된(보류 아닌) manifest 전체 `kubeconform -strict` exit 0, report에 `kubeconform: pass` |
| AC-0.6 | 재현성 | 고정 clock + NullProvider로 2회 실행 → 산출물 트리 byte 동일 (`diff -r` 0건) |
| AC-0.7 | LLM 불요 완주 | `--no-llm`으로 전 단계 완료, 질문 문안은 기계 생성 문구 |

## AC-1. jpetstore-like (단일 Java, 컨테이너 힌트 없음 — 5.1)

- AC-1.1: 컴포넌트 정확히 1개, `language: java(high, pom.xml)`, `build: maven`, `build_command: mvn -B package(high)`, multi-module 아님으로 판정.
- AC-1.2: Dockerfile 부재 → `build_strategy: dockerfile_needed` 후보 제시(빌드 전략 미제시 실패 모드 검증).
- AC-1.3: containerPort **unresolved** — 관례값 8080은 질문의 `candidates`에 `confidence: low`로만 존재, intent의 확정 값으로 등장하지 않음.
- AC-1.4: 질문 세트에 최소 포함: 런타임 포트(Q-PORT), 서블릿 컨테이너 선택, 외부 DB 사용 여부(Q-DB), registry(Q-REG), namespace(Q-NS), Ingress 필요 여부(Q-ING).
- AC-1.5: DB 접속 값이 어느 산출물에도 확정 값으로 없음(내장 HSQLDB 구성 인지, 외부 DB는 분기 질문).

## AC-2. fastapi-fullstack-like (모노레포 + Compose — 5.2)

- AC-2.1: 컴포넌트 3개 — backend(application, fastapi/high), frontend(application, react 계열/high), db(`role: dependency`). **Traefik은 컴포넌트가 아니며** Ingress 의도로만 반영.
- AC-2.2: db는 워크로드 의도 없이 `mode: external|in-cluster` 분기 질문 생성(무조건 StatefulSet 생성 실패 모드 검증 — MVP는 StatefulSet 미생성이므로 질문만).
- AC-2.3: env 분류 — `POSTGRES_PASSWORD`, `SECRET_KEY` → secret candidates(값 미기록), 비밀 아닌 값 → configmap candidates(source 포함).
- AC-2.4: `.env`의 개발용 기본 비밀번호가 확정 값으로 승격되지 않음(AC-0.4로 포섭 + 명시 테스트).
- AC-2.5: `depends_on` → dependency_model internal 엣지 존재(frontend→backend, backend→db).
- AC-2.6: 질문 세트에 최소 포함: Ingress host/TLS, DB 외부화 여부, Secret 공급 방식, frontend의 API base URL 주입 방식.
- AC-2.7: registry 질문은 컴포넌트 수와 무관하게 1개로 병합.

## AC-3. node-express-like (baseline — 5.6)

- AC-3.1: Dockerfile `EXPOSE 3000` → intent port `Tracked(3000, dockerfile_expose, high)`, Service 의도 생성.
- AC-3.2: EXPOSE 제거 변형 fixture → 포트 unresolved + 질문 생성, **어떤 포트도 추측되지 않음**.

## AC-4. Deployment Profile 모드 (dev-profile.yaml 적용)

- AC-4.1: 병합 후 registry/namespace/ingress host 질문이 `resolved_by: deployment_profile`로 해소, unresolved 질문 수가 repo-only 대비 감소.
- AC-4.2: `blocking_level: application_runnable` 질문 0건이면 report에 `target_level: 2` 기록.
- AC-4.3: Profile 값과 HIGH confidence 추론값 충돌 시 validation_report에 경고 존재(조용한 덮어쓰기 금지).
- AC-4.4: Profile의 `secret_refs` 공급 시 secret.placeholder.yaml 미생성 + Deployment가 `secretKeyRef` 참조.
- AC-4.5: Ingress가 host/class 값으로 실제 렌더되고 kubeconform 통과.

## AC-5. Validation Report 정직성

- AC-5.1: repo-only 모드 report — `achieved_level: 1`, `dry_run.server: skipped(reason 명시)`, `deployment_check/smoke_test: not_run`.
- AC-5.2: placeholder 렌더 모드(`allow_placeholders=True`) → `achieved_level: 0`.
- AC-5.3: `target_level`과 `achieved_level`이 항상 분리 기록.

## AC-6. LLM Provider 계약 (mock endpoint)

- AC-6.1: contract 위반 응답 2회 → 해당 문안 폐기 + 기계 생성 문구로 산출물 완성(파이프라인 실패 없음).
- AC-6.2: 모든 요청 body에 `temperature: 0, top_p: 1`.
- AC-6.3: provider로 전송된 요청 payload 전수에서 secret 값·repo 원문 파일 내용 부재(중간 모델 필드만 허용).
- AC-6.4: LLM 문안이 채워진 질문에서도 `id/field/blocking_level/candidates`는 NullProvider 실행 결과와 동일(결정론 필드 불변).

## Integration (실제 repo, 고정 commit, `-m integration`)

- `mybatis/jpetstore-6`과 `fastapi/full-stack-fastapi-template`을 특정 commit SHA로 clone → AC-0, AC-1, AC-2를 동일 실행. fixture와 실제 repo의 판정 차이가 나면 fixture를 실제에 맞게 갱신한다(fixture drift 방지 절차).

---

# 5. 리스크와 선결 판단

| 리스크 | 완화 |
|---|---|
| kubeconform/kubectl 미설치 환경에서 CI 취약 | validator는 skipped 처리로 완주하되, acceptance CI 이미지에 kubeconform 고정 버전 설치. dry-run은 kubectl 없으면 skipped(AC에서 kubeconform만 필수) |
| 실제 repo의 upstream 변경으로 integration 테스트 파손 | commit SHA 핀 고정, integration은 별도 마커로 상시 CI에서 제외 |
| Compose 스키마 변형(v2/v3, extends) 파싱 누락 | MVP는 top-level `services` 필수 키만 지원 선언, 미지원 키는 경고로 기록("조용히 버리지 않는다" — 4.1 Kompose 원칙) |
| LLM guided decoding 미지원 서버 | 13.6 폴백(프롬프트 내 schema + 파서 검증)을 처음부터 구현, 기능 협상은 첫 호출 실패 시 자동 전환 |
| 질문 폭증(question fatigue) | 중복 병합(Task 7) + high confidence는 질문 대신 확인 목록(checklist)으로만 — 4.4 Draft 원칙 |

구현 순서 의존성: Task 0→1은 전체의 전제. Task 2~8(Analyzer)은 3→4→5→6→7→8 순서 필요. Task 9(Renderer)·10(Validator)·11(LLM)은 Task 1 이후 서로 독립 — 병렬 진행 가능. Task 12가 전부를 묶고, Task 13이 완료를 판정한다.
