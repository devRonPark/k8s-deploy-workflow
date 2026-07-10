# 사용자 흐름 — On-Prem LLM K8s Manifest 사전 분석 파이프라인

> 기준 문서: `onprem-llm-k8s-manifest-preanalysis-workflow.md`(이하 "설계 문서"), `docs/implementation-plan.md`(이하 "구현 계획"), `docs/test-strategy.md`.
> 본 문서는 On-Premise LLM 또는 OpenAI-compatible endpoint 기반 Kubernetes Manifest 생성 시스템을 **사용자가 실제로 어떻게 사용하는지**를 설명한다. 시스템 내부 구현은 구현 계획을, 단계별 정의는 설계 문서 9장을 참조한다.

한 문장 요약: **사용자는 Repository URL을 넣고, 시스템이 알 수 없는 값에 대한 "질문 목록"을 받고, Deployment Profile로 답하고, 렌더링·검증·배포 확인을 거쳐 배포 가능성 수준(Level 0~3)을 확정한다.** 시스템은 어떤 단계에서도 사용자를 대신해 DB 접속 정보·registry·도메인·Secret 값을 추측하지 않는다(P5).

---

# 1. 주요 사용자 유형

| 사용자 | 주 관심사 | 주로 사용하는 흐름 | 주로 보는 산출물 |
|---|---|---|---|
| **Platform Engineer** | 클러스터 표준(registry, namespace, ingress class, storage class, 리소스 정책) 준수 | Deployment Profile 작성·배포(3장), Profile을 팀 표준 템플릿으로 관리 | `07-deployment-profile.template.yaml`, `09-validation-report.yaml` |
| **DevOps Engineer** | CI/CD 파이프라인에 분석·렌더·검증을 편입, 배포 후 확인 자동화 | Repository-only 분석(2장) → Profile 병합(3장) → 배포 검증(4장) 전체 | CLI 종료 코드, `09-validation-report.yaml`, `12-repair-suggestions.yaml` |
| **Application Developer** | "내 앱이 K8s에서 뜨려면 뭐가 더 필요한가"를 파악 | Repository-only 분석(2장)으로 질문 목록 확인, 앱 수준 질문(포트, 헬스 endpoint)에 답변 | `06-unresolved-questions.yaml`, `02-component-model.yaml` |
| **Solution Architect** | 전환 대상 시스템의 컴포넌트 구조·의존성·아키텍처 결정 항목 파악 | Repository-only 분석(2장)의 중간 모델 검토, 아키텍처 결정 질문(DB 외부화, discovery 전환 등) 응답 | `04-dependency-model.yaml`, `05-kubernetes-intent.yaml`, topology 요약 |
| **Enterprise Customer Reviewer** | "LLM이 값을 지어내지 않는가, 결과가 재현되는가, Secret이 새지 않는가"의 평가 | 산출물 감사: source/confidence 추적(P6), 재현성(P10), Secret 비유출(P9) 확인 | 산출물 전체(00~12), 특히 `achieved_level`/`target_level` 분리 기록 |

같은 산출물 세트를 서로 다른 사용자가 서로 다른 목적으로 읽는다는 점이 설계의 의도다. 예컨대 Developer가 응답한 포트 질문과 Platform Engineer가 채운 registry 값이 **하나의 Deployment Profile**로 합쳐져 파이프라인에 재공급된다.

---

# 2. Repository-only Mode 사용자 흐름

Deployment Profile 없이 GitHub Repository만으로 분석하는 기본 모드. 도달 가능 수준은 **Level 1(Kubernetes-Valid) + 부분적 Level 2**다(설계 문서 6.1). 이 모드의 정직한 목표는 "완성된 manifest"가 아니라 **"Kubernetes가 이해할 수 있는 manifest + 무엇이 비어 있는지에 대한 완전한 목록"**이다.

## 2.1 흐름 개요

```text
사용자                          시스템 (preanalyzer analyze)
──────────────────────────────  ─────────────────────────────────────────────
① Repository URL 입력            
② branch / commit SHA 선택   →  Step 0  repository snapshot 생성 (commit 고정)
                                Step 1  artifact inventory 생성 (부재도 기록)
                                Step 2~4 component model 생성 (역할 태깅 포함)
                                Step 5~6 runtime/dependency 분석, env 6분류
                                Step 7~8 Kubernetes Intent Model 생성
                                Step 9  runtime gap 탐지
                                        → 06-unresolved-questions.yaml
                                        → 07-deployment-profile.template.yaml
                                Step 11 렌더 가능한 리소스만 템플릿 렌더링
                                Step 12 validation (Level 1 판정)
③ 산출물 검토                ←  repo-analysis-output/ (00~11)
```

## 2.2 단계별 사용자 경험

1. **Repository URL 입력** — 사용자는 GitHub Repository URL(또는 로컬 경로)을 입력한다. private repo는 사용자 환경의 git 인증을 그대로 사용한다.

2. **branch 또는 commit SHA 선택** — `--ref`로 branch/tag/commit을 지정한다. 생략하면 기본 브랜치의 HEAD를 사용하되, 분석은 항상 **특정 commit SHA로 고정**되어 snapshot에 기록된다. 같은 SHA에 대한 재분석은 항상 같은 결과를 낸다(P10) — 사용자는 이 SHA를 팀 공유·재현·감사의 기준점으로 쓴다.

3. **repository snapshot 생성** (`00-repository-snapshot.yaml`) — 사용자가 확인할 것: 의도한 commit이 맞는지, `archived: true`가 기록되어 있다면 "참조용 분석"임을 인지.

4. **artifact inventory 생성** (`01-artifact-inventory.yaml`) — 어떤 파일이 분석 근거로 쓰였는지의 전수 목록. **부재도 명시적으로 기록**된다(예: `dockerfile, present: false`). 사용자가 확인할 것: 기대한 artifact(compose 파일, 기존 manifest 등)가 빠짐없이 목록화되었는지. 기존 K8s manifest가 감지되었으나 MVP에서 파싱되지 않는 경우 "detected but not parsed" 경고가 남는다 — 조용히 무시되지 않는다.

5. **component model 생성** (`02-component-model.yaml`) — Repository가 몇 개의 배포 단위로 분해되었는지, 각각의 언어/프레임워크/빌드 전략이 무엇으로 판정되었는지. 모든 판정에는 `source`와 `confidence`가 붙어 있어 "왜 이렇게 판단했는가"를 사용자가 검증할 수 있다. DB·캐시·프록시는 `role: dependency|infrastructure`로 태깅되어 앱 컴포넌트와 구분된다 — 예컨대 Compose의 postgres가 배포 대상으로 둔갑하지 않는다.

6. **runtime gap 탐지** — 포트·환경변수·의존성 분석(`03`, `04`) 결과에서 "Repository가 말해주지 않는 값"이 식별된다. 이 값들은 기본값으로 채워지지 않고 다음 단계의 질문으로 라우팅된다.

7. **unresolved_questions.yaml 생성** (`06`) — 이 모드의 **핵심 산출물**. 각 질문은 `id(Q-DB-001 등) / 대상 필드 / 질문 문안 / 이유 / 답변 형식 / 후보값 / blocking_level`을 갖는다. 함께 생성되는 `07-deployment-profile.template.yaml`에는 각 질문에 대응하는 빈 필드가 `# Q-xxx` 주석과 함께 배치되어 있어, 사용자는 질문을 읽고 템플릿을 채우기만 하면 된다. LLM은 질문의 자연어 문안만 다듬으며, LLM endpoint가 없어도(`--no-llm`) 기계 생성 문구로 동일한 질문 목록이 나온다.

8. **Level 1 확인** (`09-validation-report.yaml`) — 렌더 가능한 리소스(필수 값이 모두 확보된 것)는 렌더링되어 kubeconform·dry-run(client)을 통과하고 `achieved_level: 1`이 기록된다. 필수 값이 unresolved인 리소스(예: host 없는 Ingress)는 **렌더 보류**되고 사유가 기록된다. 사용자가 확인할 것: `achieved_level`과 `target_level`이 분리 기록되어 있고, 실행되지 않은 검증(`dry_run.server`, `deployment_check`, `smoke_test`)이 `skipped`/`not_run`으로 정직하게 표기되어 있는지.

## 2.3 이 모드에서 사용자가 얻는 것 / 얻지 못하는 것

| 얻는 것 | 얻지 못하는 것 |
|---|---|
| Kubernetes-valid manifest (렌더 가능 리소스 한정) | 그대로 배포해서 도는 manifest (Level 3) |
| 무엇이 비어 있는지의 완전한 목록 (질문 + Profile 템플릿) | DB host, registry, ingress host 값 (시스템은 절대 추측하지 않음) |
| 모든 판정의 source/confidence 근거 | Secret 값 (placeholder `__REPLACE_ME__`만) |

---

# 3. Deployment Profile Mode 사용자 흐름

Repository-only 분석 결과에 **환경별 입력 파일**(Deployment Profile)을 공급하여 Level 2(Pod-Runnable) 이상을 목표로 하는 모드. 하나의 분석 결과에 dev/stage/prod Profile을 각각 적용해 환경별 manifest 세트를 파생시킬 수 있다.

## 3.1 흐름 개요

```text
사용자                              시스템
──────────────────────────────────  ────────────────────────────────────────
① 07-deployment-profile.template.yaml 을 복사해 작성 시작
② registry / namespace / ingress host / DB 접속 /
   Secret ref / storage class 입력
③ merge-profile 실행            →  Profile JSON Schema 검증 (위반 시 병합 전 거부)
                                    Step 10 병합: unresolved 필드 ← Profile 값
                                            resolved_by: deployment_profile 기록
                                            질문 재계산 (해소된 질문 소멸)
                                    Step 8  Kubernetes Intent Model 재생성
                                    Step 11 manifest rendering (Ingress 등 보류분 포함)
                                    Step 12 validation
④ 갱신된 산출물 검토           ←  05/06/08/09 갱신 (00~04 불변)
⑤ Pod-runnable / Application-runnable 여부 확인 (4장으로 연결)
```

## 3.2 단계별 사용자 경험

1. **Profile 작성 시작** — 사용자는 빈 파일에서 시작하지 않는다. Step 9가 생성한 `07-deployment-profile.template.yaml`에는 이 Repository에 필요한 필드만, 대응 질문 ID 주석과 함께 배치되어 있다. Platform Engineer가 클러스터 표준 값(registry, ingress class, storage class, resource_policy)을, Developer가 앱 수준 값을 나눠 채우는 협업이 일반적이다.

2. **값 입력** — 사용자가 채우는 대표 필드(설계 문서 8.2):
   - `target_cluster`: namespace, image_registry, ingress_class, storage_class
   - `exposure`: type, host, TLS 여부와 secret_name
   - `external_dependencies`: DB/cache의 mode(external|in-cluster), host, port, **secret_ref**
   - `runtime_config`: configmap_values, secret_refs
   - `resource_policy`: 기본 requests/limits
   - `smoke_test`: 검증 경로와 기대 status

   **Secret은 값이 아니라 참조로 공급한다.** Profile에는 비밀번호 평문 대신 기존 Secret 리소스에 대한 참조(`name`/`key`)를 넣는다. Profile 파일이 유출되어도 credential이 노출되지 않으며, 시스템 역시 Secret 값을 어디에도 기록하지 않는다(P9).

3. **Deployment Profile merge** — 잘못된 스키마(오타 필드 포함)의 Profile은 **병합 전에 거부**되므로, 오타가 조용히 무시된 채 unresolved가 남는 사고가 없다. 병합 시 Profile 값이 Repository 추론값보다 우선하되, Repository의 high confidence 값과 모순되면(예: Dockerfile EXPOSE 8000 vs Profile port 9000) 조용히 덮지 않고 validation report에 **충돌 경고**를 남긴다 — 사용자는 이 경고를 보고 Profile 오기인지 의도적 재정의인지 판단한다.

4. **Kubernetes Intent Model 재생성** — 채워진 필드는 `resolved_by: deployment_profile`로 기록되고, 해소된 질문은 목록에서 사라진다. 사용자가 확인할 것: 남은 질문 중 `blocking_level: application_runnable`이 0건인지 — 0건이어야 Level 2~3 검증 단계로 진입할 수 있다.

5. **manifest rendering** — repo-only에서 보류되었던 리소스가 이제 렌더된다: host가 공급된 Ingress, `secretKeyRef` 참조로 전환된 env(placeholder 파일은 제거됨), resource_policy가 반영된 Deployment.

6. **validation** — 렌더 결과 전체가 다시 검증 체인을 통과하고 report가 갱신된다.

7. **Pod-runnable / Application-runnable 여부 확인** — 이 시점의 report는 `target_level: 2`(또는 3)를 기록하지만, `achieved_level`은 아직 1이다. **Level 2~3은 생성 시점의 약속이 아니라 배포 후 검증의 결과**이므로(설계 문서 8.5), 확정은 4장의 흐름에서 이루어진다. MVP에서는 이 배포 후 검증을 `10-deployment-readiness-checklist.md`의 절차에 따라 사용자가 수동 실행한다.

---

# 4. Post-deployment Validation 흐름

Profile 병합·렌더링·Level 1 검증을 통과한 manifest를 실제 클러스터에 적용해 Level 2~3을 확정하는 흐름이다(설계 문서 Step 13~15, 검증 체인 ⑥~⑧). MVP 범위에서는 시스템이 `10-deployment-readiness-checklist.md`와 `11-smoke-test-plan.yaml`을 **생성까지만** 하고, 실행은 사용자가 checklist를 따라 수동으로 수행한다. 2단계 로드맵에서 이 흐름 자체가 자동화된다(deploy-check / smoke-test 커맨드).

## 4.1 흐름

```text
① kubectl dry-run (server-side)   클러스터 접근 가능해진 시점에 server-side 재검증
        │ pass
② apply                           namespace는 Profile 값 (하드코딩 없음)
        │
③ Pod Running 확인                rollout status 대기, phase 확인
        │                         실패 신호: ImagePullBackOff, CrashLoopBackOff, OOMKilled
④ Pod Ready 확인                  readinessProbe 통과       ← Level 2 확정
        │
⑤ Service / Ingress 확인          endpoint 연결, 라우팅 도달성
        │
⑥ smoke test 실행                 11-smoke-test-plan.yaml의 검사
        │                         (예: GET /health via ingress → 200)
        ▼ pass                                              ← Level 3 확정
validation_report.yaml 갱신 (achieved_level: 2 또는 3)
실패 시 → repair_suggestions.yaml 생성 (5장 예외 흐름으로)
```

## 4.2 사용자가 각 단계에서 하는 일

| 단계 | 사용자 행동 | 판정 기준 |
|---|---|---|
| ① dry-run | 대상 클러스터 컨텍스트에서 server-side dry-run 실행 | admission/권한 수준 오류가 없는가 |
| ② apply | checklist의 사전 조건(namespace 존재, Secret 리소스 사전 생성, registry push 완료) 확인 후 apply | — |
| ③ Pod Running | rollout 상태 관찰 | Pod phase == Running, 컨테이너 재시작 없음 |
| ④ Pod Ready | Ready 조건 확인 | readinessProbe 통과 — **Level 2 확정 지점** |
| ⑤ Service/Ingress | Service endpoint와 Ingress 라우팅 확인 | 트래픽이 올바른 Pod에 도달 |
| ⑥ smoke test | smoke-test-plan의 검사 실행 | 기대 status 일치 — **Level 3 확정 지점** |

## 4.3 결과 기록

- **validation_report.yaml**: 단계 ①~⑥의 결과가 누적 기록되고 `achieved_level`이 갱신된다. 실행하지 않은 단계는 `not_run`으로 남는다 — 실행 안 한 것을 pass로 기록하는 경로는 없다.
- **repair_suggestions.yaml** (`12-repair-suggestions.yaml`): 실패 시 생성. 알려진 오류 패턴은 규칙 기반 수리 항목으로(예: ImagePullBackOff → registry/credential/태그 점검), 규칙으로 못 잡는 오류만 LLM의 schema-constrained patch 제안으로 기록된다. patch는 항상 **Intent Model 또는 Profile에 대한 수정 제안**이며 YAML을 직접 고치지 않는다 — 사용자가 제안을 검토·채택하면 렌더링부터 재실행된다.

---

# 5. 실패 / 예외 흐름

각 실패 상황에서 시스템이 무엇을 하고, 사용자가 무엇을 보게 되며, 어떻게 복구하는지. 공통 원칙: **실패는 은폐되지 않고 산출물에 기록되며, 복구 경로는 항상 "질문에 답하기(Profile 갱신)" 또는 "제안 검토 후 재실행"이다.**

## 5.1 분석 단계의 예외

| 상황 | 시스템 동작 | 사용자가 보는 것 | 복구 경로 |
|---|---|---|---|
| **Dockerfile 없음** | 빌드 전략을 `dockerfile_needed`(또는 buildpacks) 후보로 제시. 임의로 Dockerfile을 생성하지 않음 | component model의 `build_strategy` 후보 + 빌드 전략 질문 | 질문에 답하거나 repo에 Dockerfile 추가 후 재분석 |
| **port 불명확** (EXPOSE 없음, 설정에도 없음) | 포트를 **unresolved** 처리. 프레임워크 관례값(예: Spring 8080)은 질문의 후보에 `confidence: low`로만 제시. Service 의도 미생성 | Q-PORT 질문 + Service/Ingress 렌더 보류 사유 | Profile 또는 질문 답변으로 포트 공급 |
| **DB 접속 정보 없음** | `blocking_level: application_runnable` 질문 생성(Q-DB). external / in-cluster 분기 질문 포함. 연결 값은 어디에도 채워지지 않음 | 질문 + Profile 템플릿의 `external_dependencies.database` 빈 필드 | Profile에 DB mode/host/secret_ref 기입 |
| **Secret 값 없음** | placeholder manifest 생성(값 `__REPLACE_ME__`). 값 생성·제안 금지 | `secret.placeholder.yaml` + Secret 공급 방식 질문 | Profile `secret_refs`로 기존 Secret 참조 공급 → placeholder 파일 제거되고 `secretKeyRef` 전환 |
| **image registry 없음** | `image.registry: unresolved` 기록. 컴포넌트가 여럿이어도 registry 질문은 1개로 병합 | Q-REG 질문 | Profile `target_cluster.image_registry` 기입 |
| **Ingress host 없음** | Ingress를 후보로만 생성, **렌더 보류** + 사유 기록 | `deferred` 목록의 ingress 항목 + Q-ING 질문 | Profile `exposure.host` 기입 → 재렌더 시 Ingress 생성 |

## 5.2 빌드·배포 단계의 예외

| 상황 | 시스템/사용자 동작 | 복구 경로 |
|---|---|---|
| **build 실패** | 이미지 빌드는 사용자(또는 CI) 책임 영역. checklist의 빌드 항목(`build_command`, 예: `mvn -B package`)이 출발점 | 빌드 로그 확인 → repo 수정 후 재분석, 또는 빌드 전략 질문 재답변 |
| **Pod CrashLoopBackOff** | 이벤트·로그·exit code 수집 → 규칙 기반 매핑(command/env 점검) 우선, 미해결 시 LLM patch 제안 | `12-repair-suggestions.yaml` 검토 → Intent/Profile patch 채택 → 재렌더·재배포 |
| **ImagePullBackOff** | 규칙 기반 매핑: registry 주소 / pull credential / 이미지 태그 점검 항목 제시 | registry 값·credential 확인 후 재시도 |
| **readinessProbe 실패** | Level 2에서 정지, `achieved_level`은 2 미만으로 유지. probe 경로/포트와 앱의 실제 헬스 endpoint 불일치 여부를 수리 제안으로 | probe 후보의 근거(source) 확인 → Intent/Profile 수정 → 재렌더 |
| **smoke test 실패** | Level 3 미달성으로 기록(⑥까지 통과했어도 Level 2에 머묾). 실패한 검사·응답 코드가 report에 남음 | 외부 의존성 도달성(DB 등)·env 공급 상태를 checklist로 역추적 |

어떤 실패에서도 시스템이 "값을 바꿔서 조용히 재시도"하는 일은 없다. 반복(재렌더→재검증)은 사용자가 patch를 채택했을 때만 일어나며, 최대 반복 횟수(권장 3회) 초과 시 사람에게 escalate된다.

---

# 6. 사용자 입력이 필요한 시점

## 6.1 반드시 질문해야 하는 항목 (시스템이 답을 만들 수 없음)

Repository와 Deployment Profile 어디서도 확인되지 않으면 `blocking_level`과 함께 질문이 생성된다(설계 문서 13.4).

- DB 등 외부 의존성 접속 정보와 external/in-cluster 분기 — `application_runnable`
- Secret 공급 방식 (기존 Secret 리소스 참조) — `application_runnable`
- image registry, namespace — `application_runnable`
- Ingress host / class / TLS — 노출이 필요한 경우 `application_runnable`
- 확인 불가한 컨테이너 포트 — `application_runnable`
- storage class (영속 볼륨이 필요한 경우)
- 아키텍처 결정: DB 외부화 여부, Eureka 유지 vs K8s Service discovery 전환 등 — 분석기가 임의 결정하지 않음
- SMTP 등 선택적 외부 서비스 — `feature_partial` (없어도 기동은 가능)

## 6.2 기본값을 제안할 수 있는 항목 (제안하되 확인 목록에 표기)

confidence 정책(설계 문서 10.1)에 따른다: high는 채택, medium은 채택 + 확인 표기, low는 **후보로만** 제시 + 확인 질문.

- 프레임워크 관례 포트(Spring 8080, uvicorn 8000) — 항상 `low`, 질문의 candidates에만 등장
- `replicas: 1` — `source: default_dev, confidence: low`로 명시된 개발 편의 기본값. 운영값은 Profile로
- 헬스 endpoint 후보(actuator, `/health` 지표) — medium 이상일 때만 readinessProbe 생성, 아니면 질문
- 빌드 커맨드(`mvn -B package` 등) — 빌드 파일에서 추론, high confidence로 채택되나 checklist에 표기
- Service type `ClusterIP` — 템플릿 기본, 변경은 Profile `exposure.type`으로만

## 6.3 절대 추측하면 안 되는 항목 (추측이 곧 결함)

이 값들이 산출물에 근거 없이 등장하면 회귀 테스트(`assert_no_forbidden_values`)가 실패한다 — 즉 "추측 금지"는 규범이 아니라 테스트로 강제되는 불변식이다.

- **Secret 값 전부** — placeholder `__REPLACE_ME__` 외의 값 생성 금지. repo의 개발용 기본 비밀번호(`.env`의 더미 값)를 확정 값으로 승격하는 것도 금지
- **DB host 등 접속 좌표** — `db.example.com` 류의 그럴듯한 값 금지
- **image registry 주소, Ingress host / 도메인, namespace** — 임의 생성 금지
- **resource requests/limits 수치** — 미공급 시 필드 자체를 생략, 임의 수치 부여 금지
- **충돌 값의 채택 결정** — 소스 우선순위 규칙이 결정하고, LLM은 설명문만 생성

---

# 7. Level 0~3 배포 가능성 기준과 사용자 경험

모든 산출물 세트의 공식 수준은 `09-validation-report.yaml`의 `achieved_level`이다. `target_level`(목표)과 분리 기록되므로, 사용자는 "지금 어디까지 왔고 무엇이 남았는가"를 한 필드로 확인한다.

| Level | 이름 | 답하는 질문 | 확정 근거 | 사용자 경험 |
|---|---|---|---|---|
| **0** | Manifest Generated | 파일이 존재하는가? | 템플릿 렌더 완료 (placeholder 허용 시) | `__UNRESOLVED__`가 남은 참고용 YAML. 배포 시도 대상이 아님을 report가 명시 |
| **1** | Kubernetes-Valid | Kubernetes가 이해하는가? | YAML 문법 + kubeconform + dry-run(client) 통과 | Repository-only 모드의 정상 도달점. "문법적으로 유효하나 아직 돌지 않는다" + 질문 목록 |
| **2** | Pod-Runnable | 컨테이너가 시작되는가? | 이미지 빌드/push 가능 + apply 후 Pod Running·Ready | Profile 공급 + 실제 배포 후에만 확정. checklist의 사전 조건 이행이 전제 |
| **3** | Application-Runnable | 애플리케이션이 동작하는가? | Pod Ready + Service/Ingress 라우팅 + 외부 의존성 도달 + smoke test 통과 | required 질문 0건 + 배포 후 검증 통과의 **결과**로만 선언됨 |

사용자 관점의 핵심 규칙:

- **Repository-only 모드에서 Level 3을 약속받는 일은 없다**(P7). 시스템이 Level 3을 표기했다면 그것은 항상 실제 배포 검증의 결과다.
- 수준이 오르지 않을 때 무엇이 막고 있는지는 항상 산출물에 있다: Level 1→2는 남은 `application_runnable` 질문이, Level 2→3은 deployment check/smoke test 결과가 말해준다.
- placeholder 렌더를 요청하면 kubeconform을 통과하더라도 Level 0으로 캡된다 — "검증 통과"가 "값이 채워짐"을 위장할 수 없다.

---

# 8. CLI 기준 예시 플로우

개념적 커맨드 단위의 전체 여정. MVP CLI는 이 중 `analyze`(generate-profile·render·validate 포함), `merge-profile`, `validate`를 제공하며(구현 계획 1.7), `deploy-check`/`smoke-test`/`repair`는 MVP에서 checklist·plan 파일 기반 수동 절차로 대응하고 2단계에서 커맨드로 자동화된다.

```text
─── 1일차: Application Developer ───────────────────────────────────

$ preanalyzer analyze https://github.com/acme/shop-backend --ref v2.3.1
  # Step 0~9, 11~12 실행. LLM endpoint가 없으면 --no-llm으로 동일하게 완주
  → repo-analysis-output/ 생성
  → "컴포넌트 2개 감지 (backend-api, frontend). 질문 7건 (required 5, optional 2).
     achieved_level: 1 — Ingress/Deployment 일부는 렌더 보류 (사유: registry, host 미공급)"

  사용자: 06-unresolved-questions.yaml 검토
          — Q-PORT-001의 후보(8080, low)가 맞는지 앱 코드로 확인해 답변 준비

─── 2일차: Platform Engineer ───────────────────────────────────────

  (generate-profile에 해당 — analyze가 이미 생성한 템플릿 사용)
  사용자: 07-deployment-profile.template.yaml 을 dev-profile.yaml로 복사,
          registry / namespace / ingress host / DB secret_ref / storage class 기입

$ preanalyzer merge-profile repo-analysis-output/ --profile dev-profile.yaml
  # Step 10 병합 + Step 8 재생성 + render + validate 재실행 (재분석 없음)
  → "질문 7건 → 1건 (optional만 잔존). required 0건 → target_level: 2.
     Ingress 렌더됨. secret placeholder 제거, secretKeyRef 전환.
     ⚠ 충돌 경고 1건: Profile port 9000 vs Dockerfile EXPOSE 8000(high) — report 참조"

$ preanalyzer validate repo-analysis-output/08-generated-manifests --k8s-version 1.29
  # 렌더 산출물만 독립 재검증 (CI 게이트 용도)
  → "yaml: pass / kubeconform: pass / dry-run(client): pass — achieved_level: 1"

─── 3일차: DevOps Engineer (배포) ──────────────────────────────────

  (deploy-check에 해당 — MVP: 10-deployment-readiness-checklist.md 수동 이행)
  사용자: checklist 이행 — Secret 리소스 사전 생성, 이미지 build/push,
          server-side dry-run → apply → Pod Running/Ready 확인
  → Pod Ready 도달                                    [Level 2 확정]

  (smoke-test에 해당 — MVP: 11-smoke-test-plan.yaml 수동 실행)
  사용자: GET /health via ingress → 200 확인
  → validation_report에 기록                          [Level 3 확정]

─── 실패가 났다면 ──────────────────────────────────────────────────

  (repair에 해당)
  Pod CrashLoopBackOff → 이벤트/로그 수집 → 12-repair-suggestions.yaml
  → 규칙 기반 항목(env 누락 점검) 또는 LLM patch 제안(Intent/Profile 대상) 검토
  → 사용자가 채택 → merge-profile(갱신된 Profile)부터 재실행 → 재배포
  → 3회 반복 초과 시 escalate (시도 내역은 파일로 보존)
```

커맨드와 단계·산출물의 대응:

| 커맨드 (개념) | 대응 Step | 주 산출물 | MVP 상태 |
|---|---|---|---|
| `analyze` | 0~9, 11~12 | `00`~`09`, `10`, `11` | 제공 (`--ref`, `--profile`, `--no-llm`) |
| `generate-profile` | 9의 일부 | `07-deployment-profile.template.yaml` | analyze에 포함 |
| `render` | 11 | `08-generated-manifests/` | analyze / merge-profile에 포함 |
| `validate` | 12 | `09-validation-report.yaml` | 독립 커맨드 제공 |
| `merge-profile` | 10 → 8 → 11 → 12 | 갱신된 `05/06/08/09` | 제공 |
| `deploy-check` | 13 | report 갱신 (Level 2) | checklist 기반 수동 → 2단계 자동화 |
| `smoke-test` | 14 | report 갱신 (Level 3) | plan 파일 기반 수동 → 2단계 자동화 |
| `repair` | 15 | `12-repair-suggestions.yaml` | 규칙 기반 + 오류 설명까지 → 2단계 확장 |

UI를 얹는 경우에도 이 흐름은 동일하다: 화면은 (a) 질문 목록에 답하는 폼(= Profile 작성), (b) 중간 모델·근거(source/confidence) 열람, (c) Level 진행 상태 표시의 세 가지를 제공하는 얇은 계층이며, 판정과 산출물은 전부 파일 기반 파이프라인이 만든다 — 비대화형 CI에서도 같은 결과가 나오는 이유다.
