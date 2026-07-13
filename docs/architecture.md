# 시스템 아키텍처 — On-Prem LLM K8s Manifest 사전 분석 파이프라인

> 기준 문서: `onprem-llm-k8s-manifest-preanalysis-workflow.md`(이하 "설계 문서"), `docs/implementation-plan.md`(이하 "구현 계획"), `docs/test-strategy.md`, `docs/user-flow.md`.
> 본 문서는 On-Premise LLM 또는 OpenAI-compatible endpoint 기반 Kubernetes Manifest 생성 시스템의 **내부 아키텍처**를 구현 가능한 수준으로 정의한다. 단계별 워크플로우 정의는 설계 문서 9장을, Task 분해는 구현 계획을, 사용자 관점은 user-flow를 참조한다.

아키텍처를 한 문장으로 요약하면: **Parser는 Repository에서 객관적인 Evidence를 수집하고, Rule-based Analyzer와 LLM Semantic Analyzer가 그 Evidence에 대해 각각 추론·해석을 만든 뒤, Reconciliation Engine이 근거 있는 결과만 Intermediate Model로 승격한다. 최종 YAML은 오직 Template Renderer가 만들고 Validator·Deployment Checker·Smoke Test가 배포 가능성 수준(Level 0~3)을 확정한다.** LLM이 raw repository를 통째로 읽거나 운영환경 값·Kubernetes YAML을 직접 생성하는 경로는 구조적으로 존재하지 않는다(P1~P3, P9).

---

# 1. 전체 시스템 아키텍처

## 1.1 전체 구조 다이어그램

```text
                            ┌─────────────────────────────────────────────────────────────┐
 repo URL/path, ref ──────▶ │ [A] Evidence & Rule Analyzer                  (Step 0~10)   │
 (선택) deployment          │                                                              │
profile.yaml ────────────▶ │  Repository ──▶ Artifact ──▶ Evidence ──▶ Rule Inference     │
                            │  Scanner        Parser       Builder      Engine            │
                            │  (Step 0~1)     (Step 2)     (Step 3)     (Step 4~6)        │
                            └───────────────┬──────────────────────────────┬──────────────┘
                                            │ Evidence Bundle               │ rule_inference
                                            ▼                               │
                            ┌──────────────────────────────────────────────┐ │
                            │ [B] LLM Semantic Analyzer                   │ │
                            │  component boundary / role / runtime        │ │
                            │  dependency semantics / deployment intent   │ │
                            │  · Evidence Bundle만 입력                   │ │
                            │  · 모든 해석은 evidence_ref 필수             │ │
                            │  · 운영환경 값·YAML 생성 금지                │ │
                            └───────────────┬──────────────────────────────┘ │
                                            │ llm_interpretation             │
                                            ▼                               ▼
                            ┌──────────────────────────────────────────────┐
                            │ [C] Rule/LLM Reconciliation Engine          │
                            │  observed_fact + rule_inference +           │
                            │  llm_interpretation + user_decision 교차검증  │
                            │  → Intermediate Model / Questions / Profile │
                            └───────────────┬──────────────────────────────┘
                                            │ reconciled intermediate model
                                            ▼
                            ┌──────────────────────────────┐
                            │ [D] Template Renderer        │  (Step 11)
                            │  버전 관리 템플릿 + 렌더 정책     │
                            └───────┬──────────────────────┘
                                    │ 12-generated-manifests/
                                    ▼
                            ┌──────────────────────────────┐
                            │ [E] Kubernetes Validator     │  (Step 12)  ← Level 1 확정
                            │  yaml → kubeconform →        │
                            │  dry-run → linter → policy   │
                            └───────┬──────────────────────┘
                                    │ 13-validation-report.yaml
                                    ▼
                            ┌──────────────────────────────┐
                            │ [F] Post-deployment Layer    │  (Step 13~15, 클러스터 필요)
                            │  Deployment Checker           │  ← Level 2 확정
                            │  Smoke Test Runner            │  ← Level 3 확정
                            │  Repair Loop ──patch──▶ [A]/[C] 재실행
                            └──────────────────────────────┘
```

## 1.2 레이어 구분과 결합 규칙

시스템은 6개 레이어로 구성되며, 레이어 간 의존은 아래 표로 제한된다(구현 계획 1.1의 결합 규칙을 계승·확장).

| 레이어 | 포함 모듈 | 의존 가능 대상 | 의존 금지 대상 |
|---|---|---|---|
| **[A] Evidence & Rule Analyzer** | Repository Scanner, Artifact Parser, Evidence Builder, Rule Inference Engine, Deployment Profile Merger | 모델 정의(`models/`), evidence schema | LLM Provider, Renderer, Validator |
| **[B] LLM Semantic Analyzer** | Context Selector, Evidence Bundle Builder, Semantic Analyzer provider adapter | Evidence Bundle, semantic output contracts | raw repository 전체, 운영환경 값, Renderer, Validator |
| **[C] Reconciliation Engine** | Rule/LLM 교차검증, conflict resolver, user correction merger, Intermediate Model Generator, Question Builder | observed_fact, rule_inference, llm_interpretation, user_decision | Renderer, Validator, LLM free-form output 직접 채택 |
| **[D] Template Renderer** | 리소스별 템플릿 + 렌더 정책 | reconciled Intent Model, Deployment Profile | Analyzer 내부, LLM |
| **[E] Kubernetes Validator** | YAML/schema/dry-run/linter/policy 체인 | 렌더링된 파일 경로만 | [A]·[B]·[C]·[D] 전부 |
| **[F] Post-deployment** | Deployment Checker, Smoke Test Runner, Repair Loop | 검증 통과 manifest, 클러스터 API, validation report | LLM에 YAML 직접 수정 위임 |
| Orchestrator (CLI) | 전 레이어 연결, clock·provider 주입, 산출물 쓰기 | 위 전부 | — |

이 결합 규칙이 보장하는 성질:

1. **LLM 없이 완주**: [B]가 NullProvider여도 [A]→[C]→[D]→[E]가 완주한다. 이때 semantic interpretation은 비어 있거나 낮은 confidence로 남고, Reconciliation은 rule_inference와 user_decision만으로 진행한다.
2. **독립 테스트 가능성**: 각 레이어는 입력 모델 → 출력 모델의 순수 함수에 가깝게 정의되어 단위 테스트가 mock 없이 가능하다(테스트 전략 1.4).
3. **Provider 교체 자유**: [B] 뒤의 모델 백엔드는 설정 변경만으로 교체된다(P8). 단, provider가 바뀌어도 evidence_ref 없는 LLM 판단은 Reconciliation에서 폐기된다.
4. **근거 기반 의미 해석**: Parser는 사실을 만들고, LLM은 Evidence Bundle의 사실에 근거한 의미를 해석하며, 최종 모델은 Reconciliation을 통과한 항목만 담는다.

---

# 2. 모듈별 책임

각 모듈을 책임 / 입력 / 출력 / 사용하면 안 되는 것 / LLM 사용 가능 여부 / 실패 시 동작으로 정의한다. "실패 시 동작"의 공통 원칙: **실패는 은폐되지 않고 산출물에 기록되며, 파이프라인은 가능한 한 계속 진행한다(fail-visible, not fail-silent).**

> **구현 상태 범례** (2026-07-13, `src/` 기준): ✅ 구현·테스트 완료 · ◐ MVP 구현·파이프라인 배선됨(세부 정책/확장 기능 남음) · 🔌 컴포넌트 구축·제한적 배선 · 📋 계획(코드 없음). 이 절의 설계 서술은 Step 0~15 전체 청사진이므로, 아래 각 모듈 제목의 마커가 코드의 현재 진실이다. 설계와 코드가 갈리면 마커를 따르라.

## 2.1 Repository Scanner (Step 0~1) ✅

| 항목 | 정의 |
|---|---|
| 책임 | 분석 대상을 불변 스냅샷으로 고정(commit SHA, 메타데이터, 제외 규칙)하고, 분석에 의미 있는 파일을 전수 목록화한다. **파일의 부재도 명시적으로 기록**한다(예: `dockerfile, present: false`) |
| 입력 | Repository URL 또는 로컬 경로, ref(branch/tag/commit), clock(주입) |
| 출력 | `repository_snapshot.yaml`, `artifact_inventory.yaml`, 파일 단위 `ArtifactRef` |
| 사용 금지 | 파일 **내용** 해석(파서의 몫), `.env` 등 설정 파일 내용의 inventory 적재, 제외 패턴(`.git/`, `node_modules/` 등) 위반 |
| LLM 사용 | ❌ 불허 |
| 실패 시 | clone/checkout 실패는 파이프라인 중단(분석 대상이 없음). `.git` 없는 디렉터리는 `commit_sha: null` + 경고로 계속. 심볼릭 링크 순환 등은 순회 종료 보장 후 경고 기록 |

## 2.2 Artifact Parser (Step 2) ✅

| 항목 | 정의 |
|---|---|
| 책임 | inventory의 각 artifact(Dockerfile, Compose, package 파일, 기존 K8s manifest/Helm/Kustomize)를 결정론적으로 파싱해 구조화된 추출값을 만든다. 모든 추출값에 `source`와 `evidence_id`를 부여한다 |
| 입력 | artifact inventory + 해당 파일 원문 |
| 출력 | parser별 구조화 결과(ParsedDockerfile, ParsedCompose, ParsedMaven 등) + `observed_fact` 후보 — Evidence Builder의 입력 |
| 사용 금지 | 값 보정·추측(EXPOSE 없는 Dockerfile에서 포트를 만들어내는 것 등), 미지원 필드의 **조용한 폐기**(Kompose 원칙: 경고로 기록), Secret 값 마스킹 판단(env classifier의 몫 — 파서는 원문을 그대로 넘기고 경계를 명시) |
| LLM 사용 | ❌ 불허 |
| 실패 시 | 깨진 파일(pom.xml, JSON 등)은 예외가 아닌 `ParseWarning` 기록 + 해당 artifact skip, 파이프라인 계속 |

## 2.3 Evidence Builder (Step 3) ✅

| 항목 | 정의 |
|---|---|
| 책임 | Scanner/Parser 산출물을 `Evidence Model`로 정규화한다. 파일 존재/부재, parsed field, env 참조, dependency hint, directory relation, 기존 manifest 존재, source snippet hash를 `observed_fact`로 기록한다. LLM 입력용 `Evidence Bundle`은 여기서 만든 evidence 중 필요한 subset만 Context Selector가 고른다 |
| 입력 | artifact inventory + parser 출력 |
| 출력 | `02-evidence-model.yaml` 또는 `evidence_model` 섹션(artifact, fact, relation, signal 목록) |
| 사용 금지 | 의미 확정(예: "이 디렉터리는 backend API다"), 운영환경 값 보정, 파일 원문 전체를 Evidence Bundle에 그대로 포함 |
| LLM 사용 | ❌ 불허 |
| 실패 시 | 깨진 artifact는 ParseWarning을 evidence로 남기고 해당 artifact fact만 제외. evidence가 적어도 빈 Evidence Model을 산출해 이후 단계가 "근거 부족"으로 판단하게 한다 |

## 2.4 Rule Inference Engine (Step 4~6) ✅

| 항목 | 정의 |
|---|---|
| 책임 | Evidence Model에 규칙 테이블을 적용해 `rule_inference`를 만든다. 규칙 기반 component boundary 후보, 언어/프레임워크/빌드 전략, 포트·커맨드·헬스 endpoint 후보, env 6분류, dependency edge 후보, source priority 충돌 정보를 생성한다. **confidence 등급은 규칙 테이블이 부여한다** |
| 입력 | Evidence Model |
| 출력 | `rule_inference` 목록 + rule-only component/runtime/dependency 후보 |
| 사용 금지 | 관례값의 confidence 상향(프레임워크 관례 포트는 항상 low), 충돌 값의 폐기(`conflicts` 필드에 보존), **Secret 값의 직렬화**(SecretCandidate 타입에 value 필드 자체가 없음 — P9의 타입 수준 강제) |
| LLM 사용 | ❌ 불허 |
| 실패 시 | 어떤 규칙에도 걸리지 않는 영역은 unresolved inference로 남긴다. 컴포넌트 0개여도 빈 후보 + 근거 부족 경고로 계속 |

## 2.5 LLM Semantic Analyzer (Step 5~7) 🔌 (bounded agent와 OpenAI-compatible provider 경로 구축·runtime command 중심 배선)

| 항목 | 정의 |
|---|---|
| 책임 | Evidence Bundle을 기반으로 Repository 의미를 해석한다. 주요 출력은 component boundary 분석, component role classification(application/dependency/infrastructure/tooling), runtime behavior, dependency semantic analysis, deployment intent 후보다. 각 판단은 `evidence_refs[]`, reasoning summary, confidence, uncertainty를 포함한다 |
| 입력 | Context Selector가 만든 Evidence Bundle. Repository 전체 원문이 아니라 relevant artifact metadata, parsed facts, 짧은 source excerpts/hash, rule_inference summary만 포함 |
| 출력 | `04-semantic-analysis.yaml` audit와 검증된 runtime command 후보. 전체 설계의 `llm_interpretation` 목록은 아직 확장 대상 |
| 사용 금지 | Secret 생성·수신·기록, registry/namespace/DB host/Ingress host/resource 수치 생성, Kubernetes YAML 자유 생성, evidence_ref 없는 판단 반환, raw repository 전체 읽기 |
| LLM 사용 | ⭕ 핵심 기능 — 단 Evidence Bundle 기반 semantic interpretation으로 제한 |
| 실패 시 | verifier rejected/ambiguous, provider 설정 실패, LLM 장애는 audit에 기록하고 빈 semantic 후보로 Reconciliation 진행 |

## 2.6 Rule/LLM Reconciliation Engine (Step 8~9) ◐

| 항목 | 정의 |
|---|---|
| 책임 | `observed_fact`, `rule_inference`, 검증 통과 semantic command를 바탕으로 Intermediate Model과 질문을 만든다. 현재 구현은 component/runtime/dependency/intent 생성과 port conflict 질문 라우팅까지 포함하며, 전체 설계의 source priority·evidence quality 기반 conflict report는 확장 대상 |
| 입력 | Evidence Model, rule_inference, llm_interpretation, Deployment Profile 또는 사용자 수정 |
| 출력 | `06-component-model.yaml`, `07-runtime-model.yaml`, `08-dependency-model.yaml`, `09-kubernetes-intent.yaml`, `10-unresolved-questions.yaml` |
| 사용 금지 | LLM 결과의 직접 채택, evidence_ref 없는 판단 저장, 운영환경 값 생성, `role: dependency` 컴포넌트의 무조건 워크로드 의도 생성 |
| LLM 사용 | ❌ 불허(이미 생성된 `llm_interpretation`을 입력으로만 사용) |
| 실패 시 | conflicting port처럼 결정 불가한 값은 질문으로 남긴다. 모든 리프 필드는 Tracked 불변식(value↔source/confidence)을 통과해야 하며 위반은 버그(테스트로 강제) |

## 2.7 Deployment Profile Merger (Step 10) ◐

| 항목 | 정의 |
|---|---|
| 책임 | 사용자가 채운 Profile을 모델로 검증한 뒤 registry, namespace, image tag, ingress host를 Intent에 병합한다. 질문 재계산과 `ready_for_level2` 판정은 구현되어 있으며, `user_decision` classification과 충돌 리포트는 확장 대상 |
| 입력 | Reconciled Intermediate Model + questions + deployment_profile.yaml |
| 출력 | 갱신된 Intent + 축소된 questions + `ready_for_level2` |
| 사용 금지 | 스키마 위반 Profile의 병합(병합 **전** 거부 — 오타 필드가 조용히 무시되는 사고 방지), high confidence 추론값과 모순되는 Profile 값의 **조용한** 덮어쓰기(덮어쓰되 충돌 경고를 report에 기록) |
| LLM 사용 | ⭕ 제한적 — 충돌 **설명문** 생성만. 어느 값을 채택할지는 규칙(Profile 우선)과 사용자 결정이 정한다 |
| 실패 시 | Profile 검증 실패는 명시적 오류로 반환(사용자가 수정 후 재실행). 병합 자체는 결정론이므로 실패 모드가 검증 실패뿐 |

## 2.8 LLM Provider Interface 🔌

| 항목 | 정의 |
|---|---|
| 책임 | bounded semantic agent의 decision provider 경계와 OpenAI-compatible chat provider를 제공한다. 전체 설계의 `analyze_semantics`, `generate_question_wording`, `explain_conflict`, `suggest_patch`, `summarize` 5개 연산 인터페이스는 아직 통합 확장 대상 |
| 입력 | **Evidence Bundle 또는 정규화된 중간 모델 조각만**. 입력 계약 타입에 Secret 값 필드와 운영환경 값을 생성할 수 있는 필드가 존재하지 않는다 |
| 출력 | semantic agent action/resolution 모델 또는 provider unavailable 상태. 질문 문안·충돌 설명·repair 계약은 아직 MVP 범위 밖 |
| 사용 금지 | raw repository 전체·Secret 값의 전송(P9), evidence_ref 없는 semantic 판단, 충돌 값 채택 결정, YAML 텍스트 반환(patch_suggestion도 Intent/Profile 필드 경로 patch로 제한) |
| LLM 사용 | — (이 모듈이 LLM 경계 그 자체) |
| 실패 시 | 설정 실패·endpoint 불달·invalid action은 audit에 기록되고 파이프라인은 deterministic 결과로 계속 진행한다. **LLM 장애가 파이프라인을 중단시키는 경로는 없다** |

## 2.9 Template Renderer (Step 11) ✅

| 항목 | 정의 |
|---|---|
| 책임 | Intent Model(+Profile)을 버전 관리되는 리소스별 템플릿에 주입해 최종 YAML을 생성한다. 렌더 정책(6장)을 기계적으로 적용하고, 렌더 결과에 메타데이터 annotation(commit SHA, analyzer/rules 버전, achieved_level)을 삽입한다. **이 모듈이 만든 YAML만 산출물이 될 수 있다(P3)** |
| 입력 | 병합된 Intent Model, Deployment Profile(선택), `allow_placeholders` 플래그 |
| 출력 | `generated-manifests/` 파일 트리 + deferred 목록(보류 리소스와 사유) + achieved_level 상한 |
| 사용 금지 | Intent/Profile/템플릿 상수에 없는 값의 발명, namespace 하드코딩, resources 임의 수치, LLM 호출 |
| LLM 사용 | ❌ 불허 |
| 실패 시 | 필수 값이 unresolved인 리소스는 기본 **렌더 보류(defer) + 사유 기록**. 사용자가 `allow_placeholders`를 요청한 경우에만 `__UNRESOLVED__` placeholder로 렌더하고 Level 0으로 캡 |

## 2.10 Kubernetes Validator (Step 12) ◐

| 항목 | 정의 |
|---|---|
| 책임 | 렌더 결과에 검증 체인(YAML 문법 → kubeconform → kubectl dry-run)을 실행하고 결과를 하나의 report에 누적 기록, `achieved_level`/`target_level`을 분리 판정한다. linter와 정책 엔진은 아직 미구현이다. **판정은 도구가 한다** |
| 입력 | 렌더링된 manifest 디렉터리 + 대상 K8s 버전 |
| 출력 | `validation_report.yaml` |
| 사용 금지 | 실행하지 않은 단계의 pass 기록(반드시 `skipped(reason)`/`not_run`), placeholder manifest의 Level 1 이상 판정, 판정의 LLM 위임 |
| LLM 사용 | ⭕ 제한적 — validator **오류 메시지의 해석·수리 제안**만(Repair Loop 경유). pass/fail 판정은 항상 도구 |
| 실패 시 | 단계 실패는 fail 기록 + 후속 단계 skipped(fail-fast 체인). 외부 바이너리 부재는 `skipped: tool_not_found`로 기록하고 계속 — 예외를 던지지 않는다. `kubeconform: skipped` 상태는 Kubernetes schema 검증 완료로 간주하지 않는다 |

## 2.11 Deployment Checker (Step 13) 📋

| 항목 | 정의 |
|---|---|
| 책임 | 검증 통과 manifest를 대상 클러스터에 적용한 뒤 Pod 기동을 확인: rollout status 대기 → Pod phase(Running) → 컨테이너 상태(ImagePullBackOff/CrashLoopBackOff/OOMKilled 감지) → Ready 조건. **Level 2 확정 지점** |
| 입력 | 검증 통과 manifest + 대상 클러스터 컨텍스트(Profile) |
| 출력 | deployment check 결과(validation report에 병합), 실패 시 이벤트·로그 증거 수집 |
| 사용 금지 | 값을 바꿔서 조용히 재시도, Secret 값이 포함된 로그의 무마스킹 전달 |
| LLM 사용 | ⭕ 제한적 — 수집된 이벤트/로그 기반 **원인 설명**만(Repair Loop 경유) |
| 실패 시 | 실패 증거(이벤트, 로그, exit code)를 수집해 Repair Loop에 전달. `achieved_level`은 2 미만으로 유지 |
| MVP 상태 | 실행 자동화는 미구현. 현재 파이프라인은 `14-deployment-readiness-checklist.md`를 생성해 사용자가 수동 수행 |

## 2.12 Smoke Test Runner (Step 14) 📋

| 항목 | 정의 |
|---|---|
| 책임 | `smoke-test-plan.yaml`(Profile의 smoke_test 필드 기반)의 검사를 실행: Service/Ingress 경유 HTTP 요청 → 기대 status 대조, pod_ready 게이트 확인. **Level 3 확정 지점** |
| 입력 | smoke-test-plan + 배포된 서비스 |
| 출력 | smoke test 결과(pass/fail, validation report에 병합) |
| 사용 금지 | 판정의 LLM 위임(판정은 결정론), 실패의 pass 위장 |
| LLM 사용 | ❌ 불허 (실패 리포트 요약만 Repair Loop에서 허용) |
| 실패 시 | Level 3 미달성으로 기록(Level 2에 머묾), 실패한 검사·응답 코드를 report에 남기고 Repair Loop로 |
| MVP 상태 | 실행 자동화는 미구현. 현재 파이프라인은 `15-smoke-test-plan.yaml` 초안 생성까지 |

## 2.13 Repair Loop (Step 15) 📋

| 항목 | 정의 |
|---|---|
| 책임 | validation/deployment/smoke 실패를 수정 제안으로 환류. 1차는 **규칙 기반** 매핑 테이블(ImagePullBackOff→registry/credential/태그 점검, CrashLoopBackOff+exit code→command/env 점검, schema 오류→필드 경로). 규칙으로 못 잡는 오류만 LLM `suggest_patch`로 전달 |
| 입력 | validation report, 클러스터 이벤트/로그(Secret 값 제외), 관련 Intent Model 조각 |
| 출력 | `repair_suggestions.yaml` — **Intent Model 또는 Profile에 대한 patch 제안**(schema 강제) |
| 사용 금지 | LLM의 YAML 직접 수정(경로 자체가 없음), 오류 증거 없는 개입("더 좋게 고쳐줘" 금지), 사용자 승인 없는 patch 자동 적용, 무한 반복(최대 3회 후 escalate) |
| LLM 사용 | ⭕ 허용 — 단 오류 증거가 있을 때만, schema-constrained patch 제안으로만 |
| 실패 시 | patch 채택 → Step 11(재렌더)부터 재실행. 반복 상한 초과 시 사람에게 escalate하고 시도 내역을 파일로 보존 |
| MVP 상태 | 자동화는 2단계. MVP는 규칙 기반 항목 + 오류 설명 생성까지(`suggest_patch`는 인터페이스만 고정) |

---

# 3. 데이터 흐름

## 3.1 데이터 흐름 다이어그램

```text
 repository input (URL/path + ref)          deployment-profile.yaml (사용자 작성)
        │                                            │
        ▼ Scanner                                    │
 repository_snapshot.yaml ──── 00 ──┐                │
        │                           │ 재현성의 기준점   │
        ▼ Scanner                   │ (commit SHA 고정)│
 artifact_inventory.yaml ────── 01  │                │
        │                                            │
        ▼ Parser + Evidence Builder                     │
 evidence_model.yaml ─────────── 02                      │ observed_fact
        │                                                │
        ├──▶ Rule Inference Engine                       │
        │    rule_inference.yaml ───── 03                 │ rule_inference
        │                                                │
        └──▶ Context Selector → Evidence Bundle ──▶ LLM Semantic Analyzer
             semantic_analysis.yaml ── 04                │ llm_interpretation
        │                                                │
        ▼ Reconciliation Engine                          ▼ Profile Merger
 reconciliation-report.yaml ── 05 ◀──────────── user_decision(Profile/수정)
        │                                      (resolved_by 기록, 질문 재계산)
        ├──▶ component_model.yaml ─────── 06              │
        ├──▶ runtime_model.yaml ───────── 07              │
        ├──▶ dependency_model.yaml ────── 08 (+ env 6분류)│
        ├──▶ kubernetes_intent.yaml ───── 09              │
        ├──▶ unresolved_questions.yaml ── 10 ─┐
        └──▶ deployment-profile               │ 사용자가 10을 읽고
             .template.yaml ────────────── 11 ┘ 11을 복사·기입 → 위의 Profile 입력으로 환류
        │
        ▼ Renderer (렌더 정책 적용, 보류分 사유 기록)
 generated-manifests/ ───────── 12
        │
        ▼ Validator (체인 실행, 누적 기록)
 validation_report.yaml ─────── 13  ← achieved_level / target_level 분리 기록
        │
        ▼ (배포 후: Deployment Checker / Smoke Test Runner 결과 병합)
 repair_suggestions.yaml ────── 16  ← 실패 시. patch는 09(Intent) 또는 Profile로 환류
                                       → Step 11부터 재실행
```

번호는 산출물 디렉터리 `repo-analysis-output/`의 파일 접두어다(설계 문서 16장). 이 밖에 `14-deployment-readiness-checklist.md`, `15-smoke-test-plan.yaml`이 13과 함께 생성된다.

## 3.2 산출물별 생산자/소비자

| 산출물 | 생산 모듈 | 소비자 | 성격 |
|---|---|---|---|
| repository input | (사용자 입력) | Repository Scanner | URL/경로 + ref |
| `00-repository-snapshot.yaml` | Scanner | 전 모듈(버전·SHA 스탬프), 감사자 | 재현성 기준점. 불변 |
| `01-artifact-inventory.yaml` | Scanner | Parser, Evidence Builder | 파일 존재/**부재**의 전수 기록 |
| `02-evidence-model.yaml` | Evidence Builder | Rule Inference, Context Selector, 감사자 | `observed_fact`의 원장. 의미 해석 전 사실 |
| `03-rule-inference.yaml` | Rule Inference Engine | Reconciliation, Semantic Analyzer context | 규칙 기반 후보와 confidence |
| `04-semantic-analysis.yaml` | LLM Semantic Analyzer | Reconciliation, 감사자 | evidence_ref를 가진 `llm_interpretation` |
| `05-reconciliation-report.yaml` | Reconciliation Engine / Merger | 사용자, 감사자 | Rule/LLM/User 교차검증 결과와 conflict |
| `06-component-model.yaml` | Reconciliation Engine | Intent Builder, 사용자 검토 | 배포 단위 분해 + classification |
| `07-runtime-model.yaml` | Reconciliation Engine | Intent Builder | 포트/커맨드/probe 후보 |
| `08-dependency-model.yaml` | Reconciliation Engine | Intent Builder, Solution Architect | 내부 엣지/외부 시스템 + env 분류 |
| `09-kubernetes-intent.yaml` | Reconciliation Engine / Merger(갱신) | Renderer, Repair Loop(patch 대상) | 리소스 의도. **YAML 아님** |
| `10-unresolved-questions.yaml` | Reconciliation Engine / Merger(재계산) | 사용자, Profile 템플릿 | runtime gap과 semantic conflict의 명시적 표현 |
| `11-deployment-profile.template.yaml` | Reconciliation Engine | 사용자(복사해 Profile 작성) | 질문 id 주석이 달린 입력 템플릿 |
| deployment-profile.yaml | (사용자 작성) | Merger | 환경별 값. Secret은 **참조**로만 |
| `12-generated-manifests/` | Renderer | Validator, 클러스터 적용 | 유일한 최종 YAML 경로 |
| `13-validation-report.yaml` | Validator(+Checker/Smoke 병합) | 사용자, CI 게이트, Repair Loop | 공식 배포 가능성 수준 |
| `16-repair-suggestions.yaml` | Repair Loop | 사용자(검토·채택) | Intent/Profile patch 제안 |

## 3.3 데이터 흐름의 불변식

- **단방향 체인 강제(P2)**: 00→01→02→(03,04)→05→06~09 순서를 건너뛸 수 없다. Repository → YAML 직행 경로는 없다.
- **모든 추출·해석 필드는 Tracked(P6)**: `value / source / confidence(high|medium|low|none)` + `classification(observed_fact|rule_inference|llm_interpretation|user_decision)` + `evidence_refs / unresolved / conflicts / resolved_by`. 이 불변식은 타입 수준에서 강제된다(구현 계획 1.2).
- **Profile 병합은 00~04를 불변으로 둔다**: merge는 `user_decision`을 추가해 05~13만 갱신한다. 분석과 환경 주입이 분리되어 하나의 분석 결과에서 dev/stage/prod manifest가 파생된다.
- **LLM 판단은 evidence-bound**: `llm_interpretation`은 최소 1개 이상의 `evidence_ref`를 가져야 하며, Reconciliation이 검증하기 전에는 Intermediate Model에 저장되지 않는다.
- **Secret 값은 이 흐름 어디에도 실리지 않는다(P9)**: env 분류 시점에 값이 폐기되고 이름·출처·분류 근거만 흐른다. placeholder 값은 `__REPLACE_ME__` 고정.
- **재현성(P10)**: 동일 commit + 동일 Profile + 동일 rules_version + 동일 LLM semantic analyzer 버전 → 00~13 byte 동일(LLM 문안 필드 제외 — 그마저 temperature 0으로 최소화). `--no-llm` 모드는 04가 빈 결과로 고정된다.

---

## 3.4 Evidence Model과 Intermediate Model 분류

Evidence Model은 "Repository에서 관찰된 사실"만 담는다. Intermediate Model은 Reconciliation을 통과한 의미 있는 모델이며, 각 필드는 아래 classification 중 하나를 반드시 가진다.

| classification | 의미 | 생성 주체 | Intermediate Model 저장 조건 |
|---|---|---|---|
| `observed_fact` | 파일 존재/부재, parsed field, env 참조, dependency hint처럼 Repository에서 직접 관찰된 사실 | Scanner, Parser, Evidence Builder | source와 evidence_id 필수 |
| `rule_inference` | 규칙 테이블이 observed_fact를 근거로 만든 후보 판단 | Rule Inference Engine | rule_id, evidence_refs, confidence 필수 |
| `llm_interpretation` | LLM Semantic Analyzer가 Evidence Bundle을 근거로 해석한 의미 | LLM Semantic Analyzer | evidence_refs 필수, Reconciliation 승인 전 저장 금지 |
| `user_decision` | 사용자가 분석 결과를 수정하거나 Deployment Profile로 제공한 값 | 사용자, Profile Merger | schema 검증 통과, resolved_by 기록 필수 |

중요한 불변식:

- `observed_fact`는 의미를 주장하지 않는다. 예: `backend/package.json` 존재는 fact이고, "backend는 frontend가 아니다"는 interpretation이다.
- `rule_inference`와 `llm_interpretation`이 같은 결론을 내리면 confidence를 높일 수 있지만, 둘 중 하나라도 evidence가 없으면 채택하지 않는다.
- `llm_interpretation`이 운영환경 값을 포함하면 값은 폐기하고 `needs_user_decision` 질문으로 변환한다.
- Reconciliation conflict는 Intermediate Model에서 숨기지 않고 `05-reconciliation-report.yaml`과 `10-unresolved-questions.yaml`에 남긴다.

---

# 4. LLM 연동 아키텍처

## 4.1 구조

```text
 [A] Evidence Model ──▶ Context Selector ──▶ Evidence Bundle
        │                                            │
        │ RuleInferenceSummary / QuestionDraft       ▼
        │ ConflictContext / ErrorEvidence     ┌──────────────────────────┐
        └────────────────────────────────────▶│ LLM Provider Interface   │
                                             │  · analyze_semantics      │
                                             │  · question wording       │
                                             │  · conflict explanation   │
                                             │  · patch suggestion       │
                                             │  · schema 검증 / audit log │
                                             └───────┬───────────┬──────┘
                                                     │           │
                                      ┌──────────────▼──┐   ┌────▼─────────────────┐
                                      │ Local On-Premise │   │ OpenAI-compatible    │
                                      │ Runtime          │   │ endpoint             │
                                      │ (vLLM, TGI 등)   │   │ (vLLM/TGI/gateway)   │
                                      └──────────┬───────┘   └────┬─────────────────┘
                                                 │ schema-constrained
                                                 ▼
                                      ┌──────────────────────────┐
                                      │ Reconciliation Engine    │
                                      │ evidence_ref 검증 후      │
                                      │ Intermediate 반영         │
                                      └──────────────────────────┘
```

두 옵션의 차이는 "어디서 실행되는가"(배치)와 "무엇으로 호출하는가"(API 계약)의 관심사 차이다(설계 문서 12.3). On-Premise 서버가 OpenAI-compatible API를 노출하는 구성이 1차 대상이며, 이 경우 두 옵션은 동시에 성립한다. 어떤 배치에서도 LLM 입력은 Repository 전체가 아니라 Evidence Bundle이다.

## 4.2 Local On-Premise Runtime

- 모델은 분석기와 같은 클러스터의 전용 namespace 또는 별도 GPU 노드풀에 배치하고 내부 Service로 노출한다.
- NetworkPolicy로 분석기→모델 단방향만 허용하고 모델의 외부 egress를 차단한다(`network_policy: internal_only`).
- LLM 호출 지점(Semantic Analysis, 질문 문안, 충돌 설명, 오류 해석)은 전부 비차단 경로 — LLM 지연·장애가 evidence 수집, rule inference, reconciliation, rendering, validation을 막지 않는다.

## 4.3 OpenAI-compatible Endpoint

Chat Completions API 호환을 연동 계약으로 채택한다. **OpenAI 호스팅 모델을 의미하지 않는다** — 호환 API를 노출하는 모든 서버(vLLM, TGI, llama.cpp server, Ollama-compatible gateway, LiteLLM proxy, 사내 LLM gateway)가 대상이다.

설정 계약(설계 문서 12.3):

```yaml
llm_provider:
  mode: openai_compatible
  base_url: "https://<사내 endpoint>/v1"
  api_key_env: "LLM_API_KEY"        # 환경변수 참조만 — 설정 파일에 평문 키 금지
  model: "<모델 이름>"
  request_defaults:
    temperature: 0                   # 재현성(P10)
    top_p: 1
    max_tokens: 4096
    timeout_seconds: 60
  output_contract:
    format: json_schema
```

## 4.4 Provider Abstraction

- 파이프라인은 Provider Interface의 **5개 연산만** 안다: `analyze_semantics`, `generate_question_wording`, `explain_conflict`, `suggest_patch`, `summarize`(P8).
- 구현체는 플러그인: MVP는 OpenAI-compatible 1종 + NullProvider(항상 None → 기계 생성 문구 폴백 경로이자 `--no-llm` 모드). 비호환 사내 API는 어댑터로 수용(2단계).
- 모델 이름·system prompt 버전·schema 버전·context selection policy 버전을 산출물 메타데이터에 기록해, 모델 교체 시 회귀 세트로 동등성을 검증한다(벤더 종속 회피 — 설계 문서 12.7).

## 4.5 JSON Schema Constrained Output

- 용도별 output contract 5종: `semantic_analysis`, `question_wording`, `conflict_explanation`, `summary_text`, `patch_suggestion` — 모두 버전 관리되는 JSON Schema.
- 지원 서버는 `response_format: json_schema`(guided decoding) 사용, 미지원 서버는 프롬프트 내 schema 강제 + 파서 검증으로 폴백(첫 호출 실패 시 자동 전환).
- 검증 실패 → 실패 사유 첨부 1회 재시도 → 재실패 시 결과 폐기(None). 그 외의 "다시 생성" 반복은 금지.
- `patch_suggestion`은 Intent/Profile의 **unresolved 필드 경로 화이트리스트** 안에서만 유효하며 YAML 텍스트를 담을 수 없다.
- `semantic_analysis`는 `component_boundary`, `component_role`, `runtime_behavior`, `dependency_semantics`, `deployment_intent` 항목으로 제한되며 각 항목은 `evidence_refs[]`를 가져야 한다.
- 추가 방어선(값 필터): LLM 출력에 등장한 hostname/registry/도메인 형태 문자열은 Profile·Repository에 근거가 없으면 자동 거부한다(설계 문서 13.5).

## 4.6 Audit Logging과 Secret Redaction

- **Audit logging**: 모든 LLM 요청/응답을 감사 로그로 기록한다 — 어떤 중간 모델 조각이 전달되었고 어떤 제안이 반환되었는지, 어떤 응답이 schema 검증에 실패해 폐기되었는지를 추적 가능하게 한다. 로그에는 요청 payload의 중간 모델 필드가 그대로 남으므로, payload 자체가 이미 secret-free여야 한다(아래).
- **Secret redaction의 층위**:
  1. **타입 수준**: Provider 입력 계약 타입에 Secret 값 필드가 존재하지 않는다 — 유출이 컴파일/검증 단계에서 불가능.
  2. **분류 수준**: env classifier가 Secret 후보 판정 시점에 값을 폐기한다. 이름·출처·분류 근거만 남는다.
  3. **자격증명 수준**: `api_key`는 설정 파일이 아닌 환경변수 참조(`api_key_env`)로만 공급된다. 평문 키가 든 설정 파일은 로딩이 거부된다.
  4. **검증 수준**: 회귀 테스트가 LLM 요청 payload 전수에서 fixture의 더미 비밀 문자열 부재를 단언한다(AC-6.3).

---

# 5. Facts / Semantics / Reconciliation Boundary

## 5.1 Parser와 Rule 코드가 반드시 처리하는 영역

파일 스캔과 artifact 탐지, 모든 artifact 파싱(Dockerfile/Compose/Helm/Kustomize/기존 manifest/package 파일), Evidence Model 생성, source/evidence_id 부여, 규칙 테이블 기반 후보 생성, env 6분류, Secret 값 폐기, source priority 충돌 보존, Profile 스키마 검증과 병합, 템플릿 렌더링, 모든 validation 판정, Pod Running/Ready 판정, smoke test 실행과 pass/fail 판정.

Parser와 Rule 코드는 사실과 규칙 추론을 만든다. Monorepo, multi-module, custom layout처럼 규칙만으로 의미가 불명확한 경우에도 임의로 결론을 만들지 않고 `rule_inference`의 uncertainty와 conflict로 남긴다.

## 5.2 LLM이 수행할 수 있는 semantic 영역 (항상 Evidence Bundle 기반)

| 작업 | 단계 | 출력 계약 | 폴백 |
|---|---|---|---|
| Component Boundary 분석 | Step 5~7 | semantic_analysis | rule_inference만으로 reconciliation |
| Component Role Classification | Step 5~7 | semantic_analysis | rule_inference만으로 classification 또는 질문 |
| Runtime Behavior 분석 | Step 5~7 | semantic_analysis | 확인 가능한 observed_fact만 채택 |
| Dependency Semantic Analysis | Step 5~7 | semantic_analysis | dependency 후보를 unresolved/question으로 유지 |
| Deployment Intent 분석 | Step 5~7 | semantic_analysis | Kubernetes Intent 후보 미생성 또는 질문 |
| unresolved question의 자연어 문안 | Step 9 | question_wording | 기계 생성 기본 문구 |
| Profile↔추론값 충돌 설명문 | Step 10 | conflict_explanation | 기계 생성 문구 |
| validator/runtime 오류의 해석·수리 제안 | Step 12/13/15 | patch_suggestion | 규칙 기반 매핑 항목만 |
| 사용자向 문서(checklist 등) 문안 | 산출물 단계 | summary_text | 기계 생성 문구 |

공통 조건: LLM은 **Evidence Bundle만** 입력받고, 출력은 언제나 `llm_interpretation` 또는 "제안"이며 채택은 Reconciliation Engine 또는 사용자가 한다.

## 5.3 Reconciliation이 반드시 처리하는 영역

- Rule과 LLM이 같은 결론을 냈는지 확인한다.
- 결론이 다르면 source priority, confidence, evidence quality, 사용자 결정 여부로 conflict를 분류한다.
- evidence_ref가 없는 LLM 판단, Repository 근거와 맞지 않는 판단, 운영환경 값을 생성한 판단은 폐기한다.
- 사용자에게 먼저 보여줘야 하는 분석 결과(`06-component-model.yaml`, `08-dependency-model.yaml`, `05-reconciliation-report.yaml`)와 수정 가능한 질문(`10-unresolved-questions.yaml`)을 만든다.
- 최종 Intermediate Model에는 Reconciliation을 통과한 `observed_fact`, `rule_inference`, `llm_interpretation`, `user_decision`만 저장한다.

## 5.4 LLM이 절대 해서는 안 되는 영역 (경로 자체가 없음)

- raw repository 전체 읽기 — Provider 입력 타입이 Evidence Bundle이므로 전달 경로가 없다
- 파일 존재 탐지, Dockerfile/Compose/package 파일 파싱
- Kubernetes YAML 직접 생성 — 산출물은 Renderer 출력만 허용(P3), patch_suggestion도 YAML 텍스트 반환 불가
- Secret 값 생성·수신·기록(P9)
- registry / 도메인 / namespace / DB host의 임의 생성 — 값 필터가 근거 없는 hostname을 자동 거부
- 충돌 값 중 어느 것을 채택할지 **최종 결정** — Reconciliation과 user_decision의 몫
- 운영환경 리소스 이름 생성(namespace, registry, Secret name, DB host 등)
- evidence_ref 없이 component role, boundary, dependency를 주장하는 것

이 경계의 요지는 "LLM을 배제한다"가 아니라 **"LLM은 의미 해석에 참여하되, 사실 수집과 최종 채택 권한은 갖지 않는 구조"**다(설계 문서 19장). 경계는 규범이 아니라 타입·schema·Reconciliation·회귀 테스트(근거 없는 판단 스캔, 금지 값 스캔, Secret 유출 grep)로 강제된다.

---

# 6. Template Rendering Architecture

## 6.1 구조

Renderer는 (a) 버전 관리되는 리소스별 템플릿 세트와 (b) 렌더 정책 데이터(리소스별 "필수 필드 + 미해결 시 행동(defer|placeholder|omit-field)")로 구성된다. 정책이 데이터로 분리되어 있어 템플릿 추가·변경이 렌더 엔진 변경 없이 가능하며, 템플릿 변경은 `rules_version`을 올리고 golden 스냅샷 테스트로 회귀를 감시한다(테스트 전략 3장).

## 6.2 템플릿별 렌더 규칙

| 템플릿 | 생성 규칙 | 미해결 시 행동 | MVP |
|---|---|---|---|
| **Deployment** | 컴포넌트당 1개(stateless 기본). image = Profile registry + Intent name/tag. port/env는 Intent에서, replicas/resources는 Profile `resource_policy`에서. readinessProbe는 헬스 endpoint confidence가 **medium 이상**일 때만 생성 | resources 미공급 → 필드 생략(임의 수치 금지). image registry 미공급 → 렌더 보류 | ✅ |
| **Service** | 포트가 **확인된** 컴포넌트당 ClusterIP 기본. 노출 유형 변경은 Profile `exposure.type`으로만 | 포트 unresolved → Service 의도 자체가 미생성 | ✅ |
| **Ingress** | 진입점 컴포넌트에 한해 후보 생성. host·ingressClassName은 Profile 값이 있을 때만 렌더. TLS는 `tls.enabled`+`secret_name` 공급 시에만 블록 생성 | host 미공급 → 렌더 보류 + deferred 사유 기록 | ✅ |
| **ConfigMap** | env 분류의 configmap_candidates로 구성. 값의 source/confidence를 annotation으로 기록 | 값 미확인 항목은 키 제외 + 질문 | ✅ |
| **Secret placeholder** | secret_candidates의 **키 구조만** 생성, 값은 `__REPLACE_ME__` 고정. Profile이 `secret_refs`를 주면 placeholder 파일을 만들지 않고 기존 Secret 참조(`valueFrom.secretKeyRef`/`envFrom`)로 전환 | — (placeholder가 곧 미해결의 표현) | ✅ |
| **PVC** | 볼륨 후보당 1개. storageClassName·용량은 Profile에서 | 미공급 → 렌더 보류(Level 0 표기) | 2단계(MVP는 질문 라우팅만) |
| **HPA** | 기본 생성하지 않음. Profile에 autoscaling 정책이 명시된 경우에만(metrics/min/max는 Profile 값) | 정책 부재 → 미생성(질문·checklist로만) | 2단계 |
| **ServiceAccount** | 컴포넌트당 전용 SA + Deployment `serviceAccountName` 연결(default SA 회피). 추가 RBAC은 범위 밖, 필요 시 질문 | — | ✅ |

## 6.3 공통 렌더 정책

- 모든 리소스에 label 3종(`app.kubernetes.io/name`, `app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by`)과 메타데이터 annotation(commit SHA, analyzer/rules 버전, achieved_level)을 삽입한다.
- `namespace`는 하드코딩하지 않는다. Profile 값이 있으면 그 값만, 없으면 필드 생략 + `kubectl -n` 안내.
- unresolved 잔존 리소스는 **렌더 보류가 기본**. `allow_placeholders` 요청 시에만 `__UNRESOLVED__`로 렌더하되 achieved_level을 0으로 캡한다.
- 멀티 컴포넌트는 `12-generated-manifests/<component>/` 하위 디렉터리로 분리한다.
- 렌더 결과에 등장하는 모든 값의 출처는 Intent / Profile / 템플릿 상수 셋 중 하나여야 한다 — Renderer는 값을 발명하지 않는다(테스트로 강제).

---

# 7. Validation Architecture

## 7.1 검증 체인

```text
        ┌── 클러스터 불필요 (Level 1 확정 구간) ────────────────────────┐
        │ ① YAML 문법 검증        파서                                  │
        │ ② K8s schema 검증      kubeconform(권장) / kubeval           │
        │                        — 대상 K8s 버전 명시(-kubernetes-version)│
        │ ③ kubectl dry-run      client-side (클러스터 가능 시 server)   │
        │ ④ Linter               kube-linter / kube-score              │
        │                        (probe 누락, latest 태그, root 실행 등) │
        │ ⑤ 정책 검증             조직 정책 엔진(OPA/Gatekeeper·Kyverno)  │
        └───────────────────────────────────────────────────────────────┘
        ┌── 클러스터 필요 ───────────────────────────────────────────────┐
        │ ⑥ Pod Running 확인      apply → rollout/phase 감시   ┐        │
        │ ⑦ Pod Ready 확인        readiness 조건               ┴ Level 2 │
        │ ⑧ Smoke test           smoke-test-plan 실행          — Level 3 │
        └───────────────────────────────────────────────────────────────┘
```

## 7.2 아키텍처 규칙

- **fail-fast 누적 기록**: 단계 실패 시 후속 단계는 skipped로 기록하되, 모든 단계 결과가 하나의 `validation_report.yaml`에 누적된다(교체가 아니라 병합).
- **도구 부재의 정직한 처리**: kubeconform/kubectl이 없으면 해당 단계를 `skipped: tool_not_found`로 기록하고 계속한다. 실행 안 된 단계가 pass로 기록되는 경로는 없다.
- **Level 판정 규칙**: placeholder 없이 렌더 + ①~③ 전부 pass → Level 1. placeholder 렌더 → Level 0 캡(②를 통과해도). ⑥~⑦ 통과 → Level 2, ⑧ 통과 → Level 3. `target_level`(목표)과 `achieved_level`(실제)은 항상 분리 기록.
- **판정과 해석의 분리**: pass/fail 판정은 항상 도구가 내린다. LLM은 실패의 해석·수리 제안(Repair Loop)만 담당한다.
- **MVP 범위**: ①+②+③(client). ④⑤는 2단계, ⑥~⑧은 MVP에서 checklist/plan 파일 기반 수동 절차.

---

# 8. 확장 포인트

아키텍처의 결합 규칙(1.2)이 만들어 두는 확장 지점. 공통 원리: **중간 모델(Intent)이 안정된 계약이므로, 그 앞(입력·탐지)과 뒤(출력·검증)를 독립적으로 확장할 수 있다.**

| 확장 | 접합 지점 | 방식 |
|---|---|---|
| **Helm output** | Renderer 뒤 | Intent Model은 출력 형식 중립적이다. Helm chart 렌더러를 Template Renderer의 두 번째 구현체로 추가(values.yaml = Profile 필드의 재배치). Analyzer·Validator 무변경 |
| **Kustomize overlay** | Renderer 뒤 | base(Intent의 환경 중립 값) + overlay(Profile별 값)로 분해하는 렌더러 추가. 환경별 Profile → 환경별 overlay의 자연 대응 |
| **CI/CD integration** | Orchestrator/CLI | `analyze`/`merge-profile`/`validate`가 파일 산출물과 종료 코드로 동작하므로 파이프라인 게이트로 직결. validation report를 아티팩트로 보존, `achieved_level`을 배포 승인 조건으로 사용 |
| **Policy engine** | Validator 체인 ⑤ | OPA/Gatekeeper·Kyverno 규칙 평가를 검증 체인의 플러그인 단계로 추가. 결과는 동일 report에 누적 |
| **추가 언어 지원** | Rule Inference Engine | 탐지 규칙 테이블에 행 추가(Go: `go.mod`, .NET: `.sln`/`.csproj` 등) + 대응 parser 추가. Buildpacks detect 스타일이므로 기존 규칙과 독립 |
| **추가 LLM provider** | Provider Interface 뒤 | 5개 연산 계약을 구현하는 어댑터 추가(비호환 사내 API 포함). 파이프라인 코드 무변경, 설정으로 선택. 모델 교체 시 5장 회귀 세트로 동등성 검증 |

이 밖에 입력 측 확장(Helm/Kustomize **입력** 파싱)은 Artifact Parser에 parser를 추가하고 소스 우선순위 표(설계 문서 10.2)의 이미 정의된 슬롯(3순위)에 연결하는 것으로 완결된다.

---

# 9. MVP 아키텍처와 향후 확장 아키텍처

## 9.1 경계 원칙

MVP와 2단계의 경계는 "모듈의 유무"가 아니라 **"실행의 자동화 여부"**다. 인터페이스와 산출물 스키마는 MVP에서 전부 고정하고(Deployment Checker의 checklist, Smoke Test의 plan, Repair의 suggestions 파일), 실행 자동화만 2단계로 미룬다. 따라서 2단계 확장은 기존 산출물 계약을 깨지 않는다.

## 9.2 대비표

| 축 | MVP | 향후 확장 (2단계~) |
|---|---|---|
| 입력 파싱 | Dockerfile, docker-compose(+override 1개), 단순 모노레포. 기존 K8s manifest/Helm/Kustomize는 **존재 기록 + "detected but not parsed" 경고까지** | Helm/Kustomize 입력 파싱, 기존 manifest의 역방향 Intent 도출(소스 우선순위 2~3순위 활성화) |
| Rule/Semantic 분석 | Java+Maven, Node.js+npm, Python(pip/poetry) 규칙 + Evidence Bundle 기반 semantic analysis | Go(go.mod), .NET(.sln/.csproj), 소스 내 포트 상수 스캔, Buildpacks 빌드 실행, 기존 manifest semantic reuse |
| 생성 리소스 | Deployment, Service, ConfigMap, Secret placeholder, Ingress(후보), ServiceAccount | PVC, HPA, StatefulSet(질문 라우팅 → 자동 생성), Helm chart·Kustomize overlay 출력 |
| Validation | ①YAML + ②kubeconform + ③dry-run(client) | ④kube-linter/kube-score, ⑤정책 엔진, server-side dry-run |
| Level 2~3 확정 | checklist·smoke-test-plan **생성까지** — 사용자가 수동 수행 | `deploy-check`/`smoke-test` 커맨드로 Deployment Checker·Smoke Test Runner 실행 자동화 |
| Repair Loop | 규칙 기반 매핑 항목 + 오류 설명 생성. `suggest_patch`는 인터페이스만 고정 | LLM patch 제안 → 채택 → 재렌더 → 재검증 루프 자동화(반복 상한 + escalate) |
| LLM Provider | OpenAI-compatible 1종 + NullProvider | 비호환 사내 API 어댑터, provider별 기능 협상(guided decoding 유무 자동 감지 고도화) |
| 도달 수준 | repo-only: Level 1 + 부분적 Level 2 / Profile 모드: Level 2 진입 가능 상태 | Profile 모드: Level 2~3 자동 확정 |

## 9.3 MVP 아키텍처 (실행 관점)

```text
 MVP 실행 경로 (자동)                          MVP에서 수동 (2단계에 자동화)
 ────────────────────────────────────         ──────────────────────────────
 [A] Analyzer (Scanner→Parser→Evidence        [E] Deployment Checker
     →Rule Inference)                              → 14-checklist.md 를 사람이 이행
        │                                      [E] Smoke Test Runner
 [B] LLM Provider (semantic_analysis,            → 15-smoke-test-plan.yaml 을 사람이 실행
     question_wording, conflict_explanation,  [E] Repair Loop
     summary — NullProvider 가능)                  → 16-repair-suggestions.yaml 의
        │                                           규칙 기반 항목까지 생성
 [C] Reconciliation Engine → Renderer (6종 템플릿)
        │
 [D] Validator (①②③)  → achieved_level 판정
```

---

# 10. 금지 구조 (아키텍처 수준의 부정 명세)

본 아키텍처에 **존재하지 않아야 하는** 경로를 명시한다. 이는 문서상 규범이 아니라 회귀 테스트(테스트 전략 1.6의 불변식 4종)로 상시 검증되는 구조적 제약이다.

| 금지 경로 | 차단 메커니즘 |
|---|---|
| LLM이 raw repository 전체를 읽는 경로 | Provider 입력 계약 타입이 Evidence Bundle뿐 — context selection을 통과하지 않은 파일 내용을 담을 필드가 없다 |
| LLM 판단이 곧바로 Intermediate Model에 들어가는 경로 | Reconciliation Engine이 `evidence_refs`, confidence, 금지 값, conflict를 검증하지 않으면 저장 불가 |
| LLM이 최종 YAML을 생성·수정하는 경로 | 산출물은 Renderer 출력만 허용(P3). patch_suggestion은 Intent/Profile 필드 경로로 제한 |
| Repository → YAML 직행 | Renderer의 입력 타입이 reconciled KubernetesIntent뿐(P2) |
| Secret 값이 산출물·LLM·로그로 흐르는 경로 | SecretCandidate에 value 필드 부재 + placeholder `__REPLACE_ME__` 고정 + payload 회귀 검사(P9) |
| 누락 값이 기본값으로 조용히 채워지는 경로 | Tracked 불변식(근거 없는 value 생성 불가) + 금지 값 스캔 테스트(P5, P6) |
| 실행 안 된 검증이 pass로 기록되는 경로 | report의 단계별 `skipped(reason)`/`not_run` 강제 + Level 판정 규칙(7.2) |
