# 테스트 전략 — On-Prem LLM K8s Manifest 사전 분석 파이프라인

> 기준 문서: `onprem-llm-k8s-manifest-preanalysis-workflow.md`(이하 "설계 문서"), `docs/implementation-plan.md`(이하 "구현 계획").
> 구현 계획의 Task별 테스트 명세와 AC-0~AC-6을 상세화·확장한 문서다. 테스트 이름은 구현 계획과 동일한 것을 재사용하며, 여기서 추가된 테스트는 각 절에 명시한다. 본 문서는 기존 Parser/Rule 정확도뿐 아니라 **LLM Semantic Analysis의 정확도와 근거성**을 1급 품질 지표로 평가한다.

---

# 1. TDD 기준 테스트 전략

## 1.1 Iron Law

**실패하는 테스트 없이 production 코드를 작성하지 않는다.** 구현 계획의 모든 Task는 아래 사이클을 강제한다.

```text
RED    : 테스트 1개 작성 (하나의 행동만 검증, 이름이 행동을 서술)
       → 실행하여 "기대한 이유로" 실패하는 것을 눈으로 확인
         (import 에러·오타로 인한 실패는 RED가 아니다 — 수정 후 재확인)
GREEN  : 그 테스트를 통과시키는 최소 코드만 작성 (YAGNI)
       → 해당 테스트 + 기존 전체 테스트 그린 확인
REFACTOR: 그린 유지 상태에서만 중복 제거·이름 개선
       → 다음 RED로
```

테스트가 작성 즉시 통과하면 그 테스트는 아무것도 증명하지 않은 것이다 — 기존 행동을 테스트하고 있거나 잘못된 것을 검증하고 있으므로 테스트를 고친다.

## 1.2 이 프로젝트에서 TDD가 특히 잘 작동하는 이유

파이프라인의 각 단계가 **순수 함수(입력 모델 → 출력 모델)** 로 설계되어 있다(구현 계획 1.6). 따라서:

- 테스트 = "fixture 입력 → 기대 모델" 단언으로 충분하다. 파일시스템 I/O는 scanner/writer에만 있어 mock이 거의 필요 없다.
- 설계 문서가 이미 **기대 출력을 명세**해 놓았다(11장 스키마 예시, 5장의 "기대 evidence/rule/semantic/reconciled model / 기대 unresolved questions"). RED 단계의 테스트는 이 명세를 그대로 옮겨 적는 것에서 시작한다.
- 설계 문서 5장의 "드러내는 실패 모드"는 **회귀 테스트 케이스의 원본 목록**이다. 각 실패 모드는 반드시 그것을 검증하는 이름 있는 테스트를 갖는다(3~4장에 매핑).

## 1.3 테스트 레이어 (3층)

| 레이어 | 위치 | 실행 조건 | 목적 | 속도 목표 |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | 항상, 네트워크·외부 바이너리 불필요 | 모듈 단위 행동 검증. TDD 사이클의 주 무대 | 전체 < 10초 |
| **Acceptance** | `tests/acceptance/` | 항상 (CI 이미지에 kubeconform 고정 버전 필수) | fixture repo에 대한 파이프라인 end-to-end + AC-0~AC-6 판정 | 전체 < 60초 |
| **Integration** | `tests/integration/` | `pytest -m integration` (네트워크 필요, 상시 CI 제외) | 고정 commit SHA의 실제 GitHub repo 5종에 동일 시나리오 재실행 | 제한 없음 |

pytest 설정:

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
  "integration: real GitHub repos, network required",
  "needs_kubeconform: skipped when kubeconform binary is absent",
  "needs_kubectl: skipped when kubectl binary is absent",
]
addopts = "-m 'not integration'"    # 기본 실행에서 integration 제외
```

## 1.4 Mock 정책 (anti-pattern 방지)

**원칙: 실제 코드를 테스트한다. mock은 경계 밖의 것에만 쓴다.**

| 대상 | 정책 |
|---|---|
| 파서·빌더·병합·렌더러 | mock 금지. fixture 파일과 실제 모델 객체로 테스트 |
| LLM endpoint | `httpx.MockTransport` + `tests/fixtures/llm_responses/`의 녹화 응답. Provider 테스트는 schema 검증·재시도·None 폴백을 검증하고, semantic regression 테스트는 녹화 응답이 Reconciliation 후 기대 component/dependency 결과를 만드는지 검증 |
| kubeconform / kubectl | acceptance에서는 **실제 바이너리** 실행(판정 로직을 mock하면 Level 1 확정이 무의미). unit에서 도구 부재 시나리오만 `monkeypatch.setenv("PATH", ...)` |
| 시각 | mock이 아니라 **주입**: `clock=lambda: datetime(2026, 7, 10, 9, 0, 0, tzinfo=UTC)` |
| git clone | unit/acceptance는 로컬 fixture 디렉터리를 직접 입력(clone 경로 우회). integration만 실제 clone |

금지 사항: production 클래스에 테스트 전용 메서드 추가, mock의 호출 횟수만 검증하고 결과 모델을 검증하지 않는 테스트, 하나의 테스트에서 여러 행동 검증(이름에 "and"가 들어가면 분리).

## 1.5 결정론이 테스트 전략에 주는 제약 (P10)

- 모든 unit/acceptance 테스트는 **고정 clock + NullProvider**가 기본. Semantic Analysis 품질 테스트만 MockTransport provider를 명시적으로 주입해 Rule-only와 Hybrid 결과를 비교한다.
- 순서 의존 검증: 목록 산출물(inventory 항목, 컴포넌트, 질문)은 정렬 상태 자체를 단언한다(`test_inventory_sorted`, `test_question_ids_deterministic`).
- 재현성은 별도 테스트로 상시 검증: `test_determinism.py`가 파이프라인을 2회 실행해 산출물 트리 byte 비교(AC-0.6).

## 1.6 전 산출물 공통 불변식 테스트 (모든 레이어에서 재사용하는 헬퍼)

`tests/helpers/invariants.py`에 아래 4개 검사기를 두고, acceptance의 모든 시나리오가 마지막에 호출한다. (구현 계획 Task 13의 `tests/acceptance/forbidden_values.py`는 이 헬퍼 모듈로 일반화·흡수한다 — 금지 값 검사는 4개 불변식 중 하나가 된다.)

| 헬퍼 | 검사 내용 | 근거 |
|---|---|---|
| `assert_all_leaves_tracked(model)` | 모델 트리 재귀 순회 — 모든 추출·해석 리프가 `Tracked`이고 불변식(value↔source/confidence/classification/evidence_refs, unresolved↔NONE) 충족 | P6, AC-0.2 |
| `assert_no_forbidden_values(out_dir, allowed)` | 산출물 전체 스캔 — repo/Profile에 근거 없는 hostname·FQDN·registry 패턴, 상투 값(`db.example.com`, `myregistry` 등) 검출 시 실패 | P5, AC-0.3 |
| `assert_no_secret_leak(out_dir, secrets)` | fixture의 더미 비밀 문자열이 산출물·LLM 요청 payload 어디에도 없음, placeholder 값 == `__REPLACE_ME__` | P9, AC-0.4 |
| `assert_levels_honest(report)` | `target_level`/`achieved_level` 분리 기록, 실행 안 된 단계는 `not_run`/`skipped(reason)` | 6장, AC-5 |
| `assert_semantic_grounded(semantic, evidence)` | 모든 `llm_interpretation.evidence_refs[]`가 Evidence Model의 evidence_id에 존재하고 빈 ref가 없음 | Evidence grounding, AC-0.8 |
| `assert_no_hallucinated_intermediate(report, models)` | Reconciliation에서 rejected된 LLM 값이 component/runtime/dependency/intent에 저장되지 않았음 | Hallucination rate, AC-0.9 |

## 1.7 Semantic Analysis 품질 지표

Semantic Analysis는 "LLM이 그럴듯한 설명을 했는가"가 아니라 "Evidence에 근거해 최종 Intermediate Model 정확도를 높였는가"로 평가한다.

| 지표 | 정의 | MVP 기준 |
|---|---|---|
| Component Boundary Accuracy | fixture의 기대 컴포넌트 경계와 reconciled component boundary의 precision/recall | 핵심 fixture(jpetstore, fastapi, node-express)에서 100%, 확장 fixture는 회귀 추적 |
| Component Role Accuracy | application/dependency/infrastructure/tooling role classification 정확도 | fastapi fixture에서 backend/frontend/db/traefik 기대 role 100% |
| Dependency Accuracy | internal edge/external dependency 분류의 precision/recall | fastapi fixture internal edge와 DB dependency 100% |
| Evidence Grounding | `llm_interpretation` 중 유효 evidence_refs를 가진 비율 | 100%. 근거 없는 interpretation은 즉시 rejected |
| Hallucination Rate | LLM이 만든 값 중 Evidence/Profile에 없는 component/value가 Intermediate Model에 저장된 비율 | 0% |
| Rule-only vs Hybrid Delta | NullProvider 결과와 Hybrid 결과의 boundary/role/dependency 차이 | 차이는 `05-reconciliation-report.yaml`에 기록. Hybrid가 금지 값/Secret/validation 불변식을 깨면 실패 |
| LLM Regression Stability | 녹화된 LLM 응답 + 고정 context policy로 같은 semantic/reconciliation 결과가 나오는지 | byte-level 또는 structured diff 동일 |

---

# 2. 모듈별 테스트 정의

각 표의 "구현 계획 정의" 열이 ✓인 테스트는 구현 계획 Task에 이미 명세된 것이고, 나머지는 본 문서가 추가하는 테스트다.

## 2.1 Repository Scanner (Step 0~1 — 구현 계획 Task 2)

**책임**: snapshot 고정(재현성의 기반) + artifact inventory(파일 존재/부재의 명시적 기록).

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_snapshot_is_deterministic` | 고정 clock 2회 실행 → `model_dump()` 완전 동일 | ✓ |
| `test_inventory_detects_artifacts_per_fixture` | fixture 3종 → 기대 inventory. jpetstore-like는 `container_files=[{dockerfile, present: false}]`로 **부재를 기록** | ✓ |
| `test_inventory_detects_k8s_manifest_by_content` | `apiVersion`+`kind` 가진 YAML → `kubernetes_manifests` 분류 (파일명 아닌 내용 기준) | ✓ |
| `test_excluded_patterns` | `.git/`, `node_modules/` 하위 파일 → inventory 부재 + `excluded_patterns` 필드에 기록 | ✓ |
| `test_inventory_sorted` | 항목 경로 오름차순 | ✓ |
| `test_snapshot_records_versions` | snapshot에 `analyzer_version`, `rules_version`, `commit_sha` 존재 (11.1 스키마) | 추가 |
| `test_compose_variants_detected` | `docker-compose.yml`, `docker-compose.override.yml`, `compose.yaml` 모두 `compose_files`로 | 추가 |
| `test_env_template_detected_but_env_value_not_inventoried` | `.env` 파일은 `app_configs`로 목록화되되 파일 **내용**은 inventory에 실리지 않음 | 추가 |
| `test_yaml_without_apiversion_not_k8s_manifest` | `apiVersion` 없는 일반 YAML(예: CI 설정) → `kubernetes_manifests` 미분류 (오탐 방지) | 추가 |
| `test_non_git_directory_snapshot` | `.git` 없는 로컬 디렉터리 → `commit_sha: null` + 경고 기록, 예외 없음 | 추가 |

**Edge cases**: 빈 repo(파일 0개) → 빈 inventory + 컴포넌트 0개 경고 경로의 시작점. 심볼릭 링크 순환 → 순회 종료 보장.

## 2.2 Artifact Parser (구현 계획 Task 3)

**책임**: Dockerfile/Compose/package 파일의 결정론적 파싱. **파싱 불가능·미지원 필드는 조용히 버리지 않고 경고 기록**(Kompose 원칙, 설계 문서 4.1).

### Dockerfile parser

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_expose_extracted_high_confidence` | `EXPOSE 8000` → `Tracked(8000, "dockerfile_expose", HIGH)` | ✓ |
| `test_no_expose_yields_empty_ports` | EXPOSE 없는 Dockerfile → `expose_ports == []`, **어떤 포트도 생성 안 함** (5.6 실패 모드) | ✓ |
| `test_cmd_exec_form_and_shell_form` | `CMD ["node","server.js"]` / `CMD node server.js` 둘 다 → `Tracked(str, "dockerfile_cmd", HIGH)` | 추가 |
| `test_multistage_last_stage_wins` | multi-stage Dockerfile → 최종 stage의 EXPOSE/CMD/base image 채택, 이전 stage는 무시 | 추가 |
| `test_base_image_and_user_extracted` | `FROM python:3.11-slim` → runtime_version 입력; `USER app` → 기록 | 추가 |
| `test_expose_multiple_ports` | `EXPOSE 8080 9090` → 2개 포트 모두, 순서 보존 | 추가 |

### Compose parser

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_three_services_parsed` | fastapi fixture → 서비스 3개, `depends_on`·traefik 라벨 보존 | ✓ |
| `test_env_values_pass_through_raw` | `POSTGRES_PASSWORD` 이름+값 파서 출력에 존재 (마스킹은 env_classifier 책임 — 경계 명시) | ✓ |
| `test_override_file_merged` | base + override 1개 → override 값 우선 병합 (MVP 범위: override 1개) | 추가 |
| `test_unsupported_keys_warned_not_dropped` | `network_mode: host` 등 미지원 키 → `warnings` 목록에 기록, 예외 없음 | 추가 |
| `test_ports_short_and_long_syntax` | `"8080:80"` 문자열형과 long syntax 모두 → host/container 포트 분리 추출 | 추가 |
| `test_named_volume_recorded_as_pvc_signal` | named volume → PVC 후보 신호 (MVP는 질문 라우팅만이므로 신호 필드까지) | 추가 |

### Package 파일 parsers (maven / nodejs / python_pkg)

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_maven_war_packaging_no_modules` | jpetstore-like pom.xml → packaging war, `is_multi_module == False` (5.1 검증 항목) | ✓ |
| `test_maven_multi_module_detected` | `<modules>` 있는 pom 변형 fixture → `is_multi_module == True` + 모듈 목록 (5.4 실패 모드 (a)의 입력) | 추가 |
| `test_nodejs_scripts_and_deps` | package.json → scripts.start, dependencies 추출; react/vite 의존 감지 입력 제공 | ✓ |
| `test_python_poetry_and_requirements` | pyproject.toml(fastapi 의존)과 requirements.txt 각각 → 의존 목록 | ✓ |
| `test_malformed_file_raises_parse_warning` | 깨진 pom.xml/JSON → 파서 예외가 아닌 `ParseWarning` 기록 + 해당 artifact skip (파이프라인 계속) | 추가 |

## 2.3 Evidence Builder (Step 3 — 구현 계획 Task 4)

**책임**: Parser 출력을 의미 해석 전 `observed_fact` 원장으로 정규화한다.

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_evidence_records_file_presence_and_absence` | Dockerfile 존재/부재, package 파일 존재 → 각각 evidence_id를 가진 observed_fact | 추가 |
| `test_parsed_fields_become_observed_facts` | Dockerfile EXPOSE, Compose depends_on, package dependency → source/evidence_id/artifact_ref 포함 | 추가 |
| `test_evidence_does_not_classify_roles` | postgres image fact는 남지만 `role: dependency`는 아직 생성되지 않음 | 추가 |
| `test_evidence_sorted_and_deterministic` | 같은 repo 2회 → evidence_id와 정렬 순서 동일 | 추가 |
| `test_evidence_excludes_secret_values` | `.env` 값은 fact value로 저장되지 않고 key/source만 기록 | 추가 |

## 2.4 Rule Inference Engine (Step 4~6 — 구현 계획 Task 5)

**책임**: Evidence Model에 규칙 테이블을 적용해 component/runtime/dependency/env 후보를 만든다. **confidence는 규칙 테이블이 부여하며 하드코딩 검증한다.**

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_jpetstore_single_java_boundary_candidate` | Java boundary 후보 1개, java(high, pom.xml), maven, `mvn -B package`, `build_strategy: dockerfile_needed` | ✓ |
| `test_fastapi_rule_candidates_with_roles` | backend/frontend(application 후보), db(dependency 후보), traefik(infrastructure 후보) | ✓ |
| `test_rule_inference_priority` | package.json+Dockerfile 공존 → nodejs + dockerfile 전략 후보 | ✓ |
| `test_rule_table_confidences` | 규칙 테이블 파라미터화 테스트: `pom.xml→java(HIGH)`, `application.yml→spring-boot(MEDIUM)`, `pyproject[fastapi]→fastapi(HIGH)` — 4.5절 표의 각 행이 정확한 confidence로 | 추가 |
| `test_component_boundary_priority` | Compose 서비스 단위 > 빌드 파일 경계 > Dockerfile 위치 순서 검증: compose가 있으면 서비스 단위가 이긴다 | 추가 |
| `test_infra_image_pattern_table` | postgres/mysql/redis → `role: dependency`; traefik/nginx(프록시 문맥) → `role: infrastructure` | 추가 |
| `test_monorepo_directory_boundaries` | backend/ frontend/ 각각 package 파일 → 컴포넌트 2개, root_path 정확 | 추가 |
| `test_no_indicator_yields_unknown_not_guess` | 지표 파일이 전혀 없는 디렉터리 → `language: unresolved(NONE)` + reconciliation 질문 신호. **임의 언어 부여 금지** | 추가 |
| `test_detection_is_pure` | 동일 입력 2회 → 동일 DetectionResult (규칙 평가에 상태 없음) | 추가 |

## 2.5 LLM Semantic Analyzer (Step 5~7 — 구현 계획 Task 6~7)

**책임**: Evidence Bundle 기반 semantic interpretation 생성. Repository 전체가 아니라 Context Selector가 선택한 evidence만 입력한다.

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_context_bundle_contains_relevant_evidence_only` | backend 분석 context → 관련 evidence만 포함, 무관 파일 원문 제외 | 추가 |
| `test_context_bundle_excludes_secret_values` | `.env` 더미 비밀번호와 Secret 값 후보 → LLM payload에 부재 | 추가 |
| `test_semantic_result_requires_evidence_refs` | evidence_ref 없는 component role 응답 → 폐기 + warning | 추가 |
| `test_component_boundary_accuracy_hybrid` | fastapi fixture + 녹화 LLM 응답 → backend/frontend/db boundary가 기대값과 일치 | 추가 |
| `test_component_role_accuracy_hybrid` | fastapi fixture → backend/frontend application, db dependency, traefik infrastructure | 추가 |
| `test_dependency_semantic_accuracy_hybrid` | depends_on + DATABASE_URL evidence → internal/external dependency 분류 기대값 | 추가 |
| `test_forbidden_operational_values_rejected_from_llm` | LLM이 registry/namespace/DB host 생성 → semantic result rejected | 추가 |
| `test_llm_regression_recorded_response_stable` | 같은 Evidence Bundle + 녹화 응답 → semantic_analysis structured diff 동일 | 추가 |

## 2.6 Rule/LLM Reconciliation Engine (Step 8~9 — 구현 계획 Task 8)

**책임**: observed_fact, rule_inference, llm_interpretation, user_decision을 교차 검증해 Intermediate Model을 만든다.

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_rule_llm_agreement_promotes_boundary` | rule과 LLM이 같은 boundary를 제시 → component_model 채택 + evidence_refs 보존 | 추가 |
| `test_rule_llm_conflict_routes_user_question` | db role에 rule/LLM 불일치 → component 저장 보류 + 질문 생성 | 추가 |
| `test_llm_only_without_evidence_rejected` | LLM이 evidence 없는 worker component 주장 → reconciliation report rejected | 추가 |
| `test_user_decision_overrides_with_resolved_by` | Profile/user correction → classification=user_decision, resolved_by 기록 | 추가 |
| `test_hallucinated_values_not_in_intermediate_model` | LLM이 만든 registry/DB host → 06~09 산출물에 부재 | 추가 |
| `test_rule_only_vs_hybrid_report` | NullProvider와 Hybrid 결과 비교 → boundary/role/dependency delta가 report에 기록 | 추가 |

## 2.7 Kubernetes Intent Model (Reconciliation 이후 — 구현 계획 Task 8)

**책임**: 토폴로지 → K8s 리소스 의도. 모든 필드가 Tracked, 누락은 unresolved + profile_field 라우팅.

### Reconciled Runtime/Env/Dependency (Task 8)

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_port_conflict_downgrades_and_preserves` | dockerfile 8080(HIGH) vs application.yml 8081(MEDIUM) → value 8080, confidence MEDIUM(강등), conflicts 보존, question_ref 발생 (10.3 예시 그대로) | ✓ |
| `test_convention_port_is_low_confidence` | 근거 없는 spring-boot → 8080은 후보(LOW)로만, jpetstore(war) → 포트 unresolved (5.1/5.4 실패 모드) | ✓ |
| `test_env_six_way_classification` | 7.3절 예시 입력 → 6분류 정확 재현 (configmap 2 / secret 2 / required 1 / optional 1) | ✓ |
| `test_secret_value_never_serialized` | `.env`의 `changethis` → `EnvClassification` 직렬화 결과에 부재 (`SecretCandidate`에 value 필드 자체가 없음) | ✓ |
| `test_depends_on_becomes_internal_edge` / `test_database_url_becomes_external_dep` | 11.5 예시 형태 재현 | ✓ |
| `test_secret_name_patterns_case_insensitive` | `db_password`, `ApiKey`, `PRIVATE_KEY_PATH` → 전부 secret candidate (패턴 `PASSWORD\|SECRET\|TOKEN\|KEY\|CREDENTIAL\|PRIVATE`, 대소문자 무시) | 추가 |
| `test_grpc_addr_env_is_internal_dependency` | `*_SERVICE_ADDR` 패턴 env가 repo 내 다른 컴포넌트를 가리키면 internal 엣지 (5.3 실패 모드 (b) — 외부 의존 오분류 방지) | 추가 |
| `test_health_endpoint_signal_confidence` | actuator 의존/`/health` 라우트 지표 → probe 후보 MEDIUM, 지표 없으면 probe 후보 없음 | 추가 |

### Intent Builder (Task 8)

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_intent_matches_11_6_shape` | fastapi fixture → 11.6 예시 구조 재현 (Deployment+Service+Ingress 후보+configmap/secret 키) | ✓ |
| `test_db_component_not_rendered_as_workload` | db → workload 의도 없음 + `mode: external\|in-cluster` 분기 질문 신호 (5.2 실패 모드 (b)) | ✓ |
| `test_every_leaf_field_is_tracked` | intent 트리 재귀 순회 → 전 리프 Tracked + 불변식 충족 | ✓ |
| `test_registry_and_tag_unresolved_with_profile_field` | `image.registry.unresolved == True`, `profile_field == "target_cluster.image_registry"` | 추가 |
| `test_replicas_default_dev_low` | `replicas: Tracked(1, "default_dev", LOW)` — 임의 운영값 부여 금지 (7.4 표) | 추가 |
| `test_resources_unresolved_never_numeric` | resources에 수치 없음, `profile_field: resource_policy` (분석기의 임의 수치 부여 금지) | 추가 |
| `test_entrypoint_only_gets_ingress_candidate` | 진입점 컴포넌트만 `ingress.candidate: true`; 내부 전용 컴포넌트는 Service까지만 | 추가 |
| `test_port_unresolved_means_no_service_intent` | 포트 unresolved 컴포넌트 → Service 의도 미생성 + 질문 (14장 "포트가 확인된 컴포넌트당") | 추가 |
| `test_existing_manifest_priority_over_source` *(2단계 예약)* | 기존 manifest의 port와 소스 추론 충돌 → manifest 값 우선 (10.2). MVP에서는 `@pytest.mark.skip(reason="phase-2")`로 자리만 | 추가 |

## 2.8 Template Renderer (Step 11 — 구현 계획 Task 10)

**책임**: Intent(+Profile) → YAML. 14장 렌더 정책의 기계적 적용. **여기서 나온 YAML만이 산출물이 될 수 있다(P3).**

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_render_defers_ingress_without_host` | host unresolved → ingress.yaml 미생성 + `deferred[{ingress, reason}]` | ✓ |
| `test_render_ingress_with_profile_host` | Profile host/class 공급 → ingress.yaml 생성 | ✓ |
| `test_no_resources_block_when_policy_missing` | resources 미공급 → YAML에 `resources:` 키 자체가 없음 | ✓ |
| `test_secret_placeholder_values_are_replace_me` | 모든 secret 값 == `__REPLACE_ME__` | ✓ |
| `test_secret_refs_switch_to_secretKeyRef_and_drop_placeholder_file` | Profile `secret_refs` → placeholder 파일 없음 + `valueFrom.secretKeyRef` | ✓ |
| `test_labels_and_metadata_annotations_present` | label 3종(`app.kubernetes.io/name|part-of|managed-by`) + annotation(commit SHA, analyzer/rules 버전, achieved_level) | ✓ |
| `test_snapshot_stability` | golden 파일과 byte 동일 (3장 golden 방식) | ✓ |
| `test_namespace_never_hardcoded` | Profile 없으면 manifest에 `namespace:` 키 부재; Profile 있으면 그 값만 | 추가 |
| `test_allow_placeholders_caps_level0` | `allow_placeholders=True` → `__UNRESOLVED__` 문자열 존재 + `achieved_level_cap == 0` | 추가 |
| `test_readiness_probe_only_when_medium_or_higher` | probe 후보 confidence LOW → readinessProbe 블록 없음 + 질문; MEDIUM 이상 → 생성 (14장 Deployment 규칙) | 추가 |
| `test_serviceaccount_per_component_and_linked` | 컴포넌트당 SA 1개 + Deployment `serviceAccountName` 연결 | 추가 |
| `test_renderer_never_invents_values` | intent에 없는 키가 렌더 결과에 등장하지 않음: 렌더 결과 파싱 → 모든 값의 출처가 intent/Profile/템플릿 상수 중 하나 | 추가 |
| `test_multi_component_renders_subdirectories` | 컴포넌트 2개 이상 → `12-generated-manifests/<component>/` 하위 분리 (16장) | 추가 |

## 2.9 Validator (Step 12 — 구현 계획 Task 11)

**책임**: 검증 체인 실행과 **정직한 수준 판정**. 판정은 도구가, 해석만 LLM이(MVP는 해석도 제외).

| 테스트 | Given → Expect | 계획 정의 |
|---|---|---|
| `test_valid_manifests_reach_level1` | golden manifest + kubeconform → `achieved_level == 1` `@needs_kubeconform` | ✓ |
| `test_broken_yaml_fails_at_syntax_stage` | 깨진 YAML → `yaml_syntax: fail`, 후속 단계 `skipped` (fail-fast 체인) | ✓ |
| `test_missing_tool_recorded_as_skipped` | PATH에서 kubeconform 제거 → `skipped: tool_not_found`, 예외 없음 | ✓ |
| `test_placeholder_manifests_capped_at_level0` | `__UNRESOLVED__` 포함 manifest → `achieved_level == 0` (kubeconform 통과 여부와 무관) | ✓ |
| `test_kubeconform_schema_error_reported_with_path` | 잘못된 필드(`spec.replicas: "two"`) → `kubeconform: fail` + 리소스/필드 경로가 report에 | 추가 |
| `test_kubernetes_version_passed_through` | `k8s_version="1.29"` → kubeconform 인자에 반영, report에 기록 (11.9 형태) | 추가 |
| `test_dry_run_client_when_kubectl_present` | kubectl 존재 → client dry-run 실행; `dry_run.server == skipped(reason: "no cluster in repo-only mode")` | 추가 `@needs_kubectl` |
| `test_report_accumulates_not_replaces` | 체인 각 단계 결과가 하나의 report에 누적 (①~⑤ 전부 기록) | 추가 |
| `test_deployment_check_and_smoke_not_run_in_mvp` | report의 `deployment_check/smoke_test == not_run` (거짓 성공 방지 — 실행 안 한 것을 pass로 기록하지 않음) | 추가 |

---

# 3. Golden File 테스트 방식

## 3.1 무엇을 golden으로 잡는가

| Golden 세트 | 위치 | 비교 대상 | 갱신 트리거 |
|---|---|---|---|
| **렌더 golden** | `tests/golden/render/<fixture>/<scenario>/` | `12-generated-manifests/` 트리 (renderer 단위) | 템플릿 변경 (rules_version bump 필수) |
| **파이프라인 golden** | `tests/golden/pipeline/<fixture>/<mode>/` | 산출물 트리 전체 `00~15` (repo-only / with-profile 두 mode) | 규칙·모델·템플릿 어떤 변경이든 |

파이프라인 golden이 핵심이다: **Evidence/Rule/Semantic/Reconciliation/Intermediate(00~09)까지 golden에 포함**시켜 "어느 단계에서 출력이 달라졌는지"를 diff 위치로 즉시 알 수 있다. 예: 탐지 규칙 변경 → `03-rule-inference.yaml` diff부터 나타나고, 템플릿 변경 → `12-*`만 diff.

## 3.2 비교 규칙

- **byte-level 비교** (`filecmp` + 실패 시 unified diff 출력). 정규화 후 비교가 아니라, 생성 자체를 결정론화한다:
  - `analyzed_at` → 고정 clock 주입으로 상수화 (필드 제외·마스킹 방식 금지 — 마스킹 로직 자체가 버그 은폐 지점이 됨)
  - `commit_sha` → fixture는 git repo가 아니므로 `null` 고정
  - YAML 직렬화는 writer 단일 경로: key 순서 고정(모델 필드 순서), anchor/alias 금지, 개행 규칙 고정
- 파일 **목록**도 비교한다(새 파일 생성/누락도 회귀): 디렉터리 상대 경로 집합 동일성 → 각 파일 내용 동일성 순서로 검사.

## 3.3 갱신 절차 (의도적 변경 vs 회귀의 구분)

```bash
pytest tests/ --update-golden        # conftest.py의 custom flag
```

규율:

1. golden 갱신은 **전용 커밋**으로 분리한다 — 코드 변경과 golden 갱신이 한 커밋에 섞이면 리뷰에서 의도적 변경과 회귀를 구분할 수 없다.
2. 갱신 커밋 메시지에 변경 사유와 diff 요약을 기록한다 (예: `test: update golden — readinessProbe 생성 조건 medium 이상으로 변경`).
3. 템플릿/규칙 변경으로 인한 갱신은 `rules_version` bump가 같은 PR에 없으면 CI가 실패하도록 검사 테스트를 둔다: `test_golden_change_requires_rules_version_bump` (git diff에 templates/ 또는 rule inference 규칙 변경이 있는데 rules_version 동일하면 실패).
4. **golden diff를 읽지 않고 `--update-golden`을 실행하는 것은 금지** — 갱신 전 실패한 테스트의 diff 출력을 확인하고, 기대한 변경만 있는지 검토한다.

## 3.4 golden과 TDD의 관계

golden 테스트는 **회귀 방지망**이지 TDD의 RED를 대체하지 않는다. 새 행동은 반드시 명시적 단언 테스트(2장)로 먼저 RED→GREEN을 거치고, golden은 그 결과를 스냅샷으로 고정하는 마지막 단계다. "golden만 갱신하면 통과"하는 변경은 행동 테스트가 없다는 신호로 취급한다.

---

# 4. Mock Repository Fixture 구조

## 4.1 설계 원칙

1. **최소 재현**: 실패 모드를 드러내는 데 필요한 파일만 넣는다. 실제 repo의 전체 복사 금지(유지보수 불가 + 어떤 파일이 어떤 판정을 유도하는지 불명).
2. **1 fixture = 1 실패 모드 집합**: 각 fixture는 설계 문서 5장의 특정 repo 유형과 그 실패 모드에 대응한다.
3. **변형(variant)은 파일 단위 오버레이**: 별도 전체 fixture 복사 대신, 테스트가 `tmp_path`에 base fixture를 복사한 뒤 특정 파일만 추가/제거/치환한다 (`fixture_variant(base, remove=[...], overwrite={...})` 헬퍼).
4. **fixture drift 방지**: integration 테스트가 실제 repo(고정 SHA)에서 동일 단언을 실행한다. fixture와 실제의 판정이 다르면 fixture를 실제에 맞게 갱신하는 절차를 CI 주기 잡에 포함.

## 4.2 fixture 트리

```text
tests/fixtures/
  repos/
    jpetstore-like/                  # 5.1: 단일 Java, 컨테이너 힌트 없음
      pom.xml                        #   war packaging, <modules> 없음
      src/main/webapp/WEB-INF/web.xml
      src/main/resources/database/schema.sql
      src/main/resources/application.properties   # DB env 참조 (${DB_HOST} 형태)
      README.md
      # Dockerfile 의도적 부재 — "부재의 명시적 기록" 검증
    fastapi-fullstack-like/          # 5.2: 모노레포 + Compose
      docker-compose.yml             #   backend/frontend/db, traefik 라벨, depends_on
      docker-compose.override.yml    #   override 병합 검증용 (포트 1개 재정의)
      .env                           #   POSTGRES_PASSWORD=changethis (마스킹 검증용 더미)
      backend/
        Dockerfile                   #   EXPOSE 8000, CMD uvicorn
        pyproject.toml               #   fastapi 의존
        app/main.py                  #   os.getenv("DATABASE_URL") 참조 1줄 (env 스캔용)
      frontend/
        Dockerfile
        package.json                 #   react + vite
    node-express-like/               # 5.6 baseline: 최단 경로
      Dockerfile                     #   EXPOSE 3000, CMD ["node","server.js"]
      package.json                   #   express, scripts.start
      server.js                      #   process.env.PORT 참조 1줄
    spring-multimodule-like/         # 5.4 축소판 (2단계 대비, MVP에선 multi-module 판정만 사용)
      pom.xml                        #   <modules>api-gateway, vets-service</modules>
      api-gateway/pom.xml
      api-gateway/src/main/resources/application.yml   # server.port: 8081
      vets-service/pom.xml
      vets-service/src/main/resources/application.yml  # server.port: 8082
      docker-compose.yml             #   포트 교차 검증(소스 우선순위)용
    k8s-manifest-present-like/       # 5.3 축소판 (MVP: inventory 기록만 검증)
      kubernetes-manifests/frontend.yaml   # 완전한 Deployment+Service 1쌍
      src/frontend/Dockerfile
      src/frontend/package.json
  profiles/
    dev-profile.yaml                 # 8.2절 예시값 전체
    conflicting-profile.yaml         # HIGH confidence 추론과 모순되는 포트 (충돌 경고 검증)
    invalid-profile.yaml             # 스키마 위반 (병합 전 거부 검증)
  llm_responses/
    question_wording_valid.json
    question_wording_schema_violation.json
    conflict_explanation_valid.json
  golden/                            # 3장 구조
    render/...   pipeline/...
```

## 4.3 변형 fixture 사용 예 (테스트 내 오버레이)

| 변형 | 방법 | 검증 대상 |
|---|---|---|
| EXPOSE 없는 node-express | `fixture_variant(node-express-like, overwrite={"Dockerfile": no_expose_content})` | AC-3.2: 포트 추측 금지 |
| Dockerfile 추가된 jpetstore | `overwrite={"Dockerfile": tomcat_dockerfile}` | 빌드 전략이 dockerfile_needed → dockerfile로 전환 |
| 포트 충돌 spring 모듈 | application.yml 8081 + Dockerfile EXPOSE 8080 오버레이 | 10.3 충돌 강등·보존 |
| 빈 repo | `tmp_path` 빈 디렉터리 | 컴포넌트 0개 경고, 예외 없음 |

---

# 5. 테스트 대상 Repository 5개 기준 Validation Scenario

설계 문서 5.1~5.5의 repo 5개 각각에 대한 시나리오. **실행 형태 표기**: `[F]` = fixture로 상시 실행(acceptance), `[I]` = 실제 repo 고정 SHA로 integration 실행, `[P2]` = MVP 범위 밖 — 시나리오는 지금 정의하되 `@pytest.mark.skip(reason="phase-2")`로 자리를 만들어 두고 2단계에서 활성화.

모든 시나리오는 공통으로 1.6절의 불변식 4종(`Tracked 전수 / 금지 값 / Secret 유출 / Level 정직성`)을 마지막에 실행한다.

## 5.1 mybatis/jpetstore-6 — 단일 Java 웹앱 `[F][I]`

**시나리오**: `analyze <repo> --no-llm` (repo-only 모드)

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S1-1 | 컴포넌트 정확히 1개, java(HIGH, pom.xml), maven, `mvn -B package`, multi-module 아님 | 루트만 보고 오판 |
| S1-2 | `build_strategy: dockerfile_needed` 후보 제시됨 | (a) Dockerfile 부재 시 빌드 전략 미제시 |
| S1-3 | containerPort **unresolved**, 관례 8080은 질문 candidates에 LOW로만 | (b) 관례 포트를 high로 오표기 |
| S1-4 | 내장 HSQLDB가 외부 의존성으로 등장하지 않음; 외부 DB는 분기 질문(Q-DB)으로만 | (c) 내장 DB를 외부 의존성으로 오탐 |
| S1-5 | 질문 세트 ⊇ {Q-PORT, 서블릿 컨테이너, Q-DB 분기, Q-REG, Q-NS, Q-ING} | 질문 누락 |
| S1-6 | `13-validation-report.yaml`: achieved_level 1 (렌더 가능 리소스 한정), 포트 unresolved로 Deployment는 deferred 또는 Level 0 표기 | 거짓 성공 |

## 5.2 fastapi/full-stack-fastapi-template — 모노레포 + Compose `[F][I]`

**시나리오 A**: repo-only / **시나리오 B**: `--profile dev-profile.yaml`

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S2-1 | 컴포넌트: backend(application, fastapi HIGH), frontend(application), db(role: dependency). Traefik 컴포넌트 부재, Ingress 의도로만 반영 | (a) Traefik을 배포 대상으로 오탐 |
| S2-2 | db → workload 의도 없음 + `mode: external\|in-cluster` 분기 질문 | (b) DB를 질문 없이 StatefulSet 생성 |
| S2-3 | `POSTGRES_PASSWORD`/`SECRET_KEY` → secret candidates, `.env`의 `changethis`가 전 산출물에서 grep 0건 | (c) 개발용 기본 비밀번호를 확정 값으로 승격 |
| S2-4 | depends_on → internal 엣지 (frontend→backend, backend→db) | 의존 그래프 누락 |
| S2-5 | backend 포트 8000(HIGH, dockerfile_expose) → Service 의도; Ingress host unresolved | — |
| S2-6 | (B) 병합 후: Q-REG/Q-NS/Q-ING `resolved_by: deployment_profile`, required 질문 0 → `ready_for_level2`, Ingress 실제 렌더 + kubeconform 통과 | Profile 병합 미작동 |
| S2-7 | (B) `secret_refs` 공급 → placeholder 파일 미생성, `secretKeyRef` 참조 | Secret 값 평문화 |
| S2-8 | registry 질문 1개로 병합(컴포넌트 2개임에도) | 질문 폭증 |

## 5.3 GoogleCloudPlatform/microservices-demo — 기존 manifest 완비 `[F 축소][I는 P2]`

**MVP에서 실행하는 부분** (`k8s-manifest-present-like` fixture):

| # | 단언 |
|---|---|
| S3-1 | 기존 K8s manifest가 inventory `kubernetes_manifests`에 내용 기준으로 목록화됨 |
| S3-2 | manifest 파싱 미지원임이 **명시적으로 기록됨**: 산출물에 "existing manifests detected but not parsed (phase-2)" 경고 + 관련 질문(기존 manifest 재사용 여부) 생성 — 조용한 무시 금지 |
| S3-3 | 소스(Dockerfile/package.json) 기반 분석은 정상 수행 |

**P2에서 활성화하는 시나리오** (`@skip(phase-2)`로 정의만):

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S3-4 | 기존 manifest에서 image/port/env HIGH로 추출, 소스 우선순위 최상 적용 | (a) 기존 manifest 무시하고 재추론 |
| S3-5 | `*_SERVICE_ADDR` env → internal 엣지 (외부 의존 아님) | (b) gRPC 의존 오분류 |
| S3-6 | 10+ 컴포넌트에서 unresolved 질문이 소스-only 대비 현저히 적음 (namespace/registry 수준) + 분석 시간 상한 | (c) 컴포넌트 폭증 시 성능 |

## 5.4 spring-petclinic/spring-petclinic-microservices — Maven multi-module `[F 축소][I는 P2]`

**MVP에서 실행하는 부분** (`spring-multimodule-like` fixture — MVP rule inference가 Java+Maven을 지원하므로 multi-module 분해까지는 MVP 검증 대상):

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S4-1 | 모듈별 컴포넌트 2개(api-gateway, vets-service) — 루트 pom 1개로 오판하지 않음 | (a) 단일 컴포넌트 오판 |
| S4-2 | 각 모듈 `server.port`(8081/8082) → MEDIUM(application.yml), **8080을 모든 모듈에 부여하지 않음** | (c) 관례 포트 일괄 부여 |
| S4-3 | Compose 포트와 application.yml 포트 충돌 시 우선순위 적용(Compose 우선) + conflicts 보존 + 확인 질문 | 교차 검증 미작동 |

**P2 시나리오** (정의만):

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S4-4 | eureka/config-server 의존 감지 → `role: infrastructure` 태깅 | (b) 인프라 패턴을 일반 웹앱으로 오분류 |
| S4-5 | "Eureka 유지 vs K8s Service discovery 전환" **아키텍처 결정 질문** 생성 — 분석기가 임의 결정하지 않음 | 임의 아키텍처 결정 |

## 5.5 dotnet/eShop — .NET + archived 참조 repo `[P2, snapshot 메타만 MVP]`

**MVP에서 실행하는 부분** (fixture 불필요 — snapshot 메타데이터 단위 테스트):

| # | 단언 |
|---|---|
| S5-1 | `archived: true` 메타데이터가 주어지면 snapshot에 기록되고, 산출물 checklist에 "참조용 분석" 경고 문구 포함 (integration에서 eShopOnContainers로 검증) |

**P2 시나리오** (정의만 — .NET rule inference 부재):

| # | 단언 | 드러내는 실패 모드 |
|---|---|---|
| S5-2 | .sln 기준 컴포넌트 열거 (.csproj 단독 순회로 누락 없음) | (a) 컴포넌트 누락 |
| S5-3 | archived repo의 오래된 Helm/manifest → confidence 강등 + 확인 질문 | (b) 오래된 manifest를 최신 관행으로 오인 |
| S5-4 | Aspire 전용 구성 → 직역하지 않고 질문 라우팅 | (c) Aspire 무리한 직역 |

## 5.6 시나리오 ↔ 테스트 파일 매핑

```text
tests/acceptance/test_jpetstore_like.py          # S1-*  (AC-1)
tests/acceptance/test_fastapi_fullstack_like.py  # S2-*  (AC-2, AC-4)
tests/acceptance/test_node_express_like.py       # AC-3 (baseline)
tests/acceptance/test_manifest_present_like.py   # S3-1~3
tests/acceptance/test_spring_multimodule_like.py # S4-1~3
tests/acceptance/test_determinism.py             # AC-0.6
tests/integration/test_real_repos.py             # 5개 repo 고정 SHA — S1/S2 전체, S3-1~3, S5-1
```

---

# 6. 실행 및 완료 기준

## 6.1 로컬/CI 실행 매트릭스

| 명령 | 언제 | 요구 도구 |
|---|---|---|
| `pytest tests/unit -x` | TDD 사이클 내 상시 (초 단위) | 없음 |
| `pytest` (기본 = not integration) | 커밋 전, CI 모든 PR | kubeconform (acceptance) |
| `pytest -m integration` | 주간 CI 잡 / 릴리스 전 | 네트워크, git, kubeconform, kubectl |

## 6.2 완료 판정 (구현 계획 AC와의 관계)

- **모듈 완료** = 해당 절(2장)의 테스트 전부 그린 + golden 갱신 커밋 분리 규율 준수.
- **MVP 완료** = `pytest`(unit+acceptance) 전체 그린 + 1.7절 Semantic Analysis 품질 지표 기준 충족 — 이것이 구현 계획 4장 AC-0~AC-6의 실행형이며, 설계 문서 17.4의 자동 검증이다.
- **회귀 게이트** = rules_version/템플릿 변경 PR은 golden diff 리뷰 + `test_golden_change_requires_rules_version_bump` 통과 필수.

## 6.3 커버리지 정책

라인 커버리지 수치 목표는 두지 않는다(수치는 게임 가능). 대신 **행동 커버리지**를 강제한다: 설계 문서 5장의 실패 모드 15개(5.1~5.5 각 3개), Semantic Analysis 품질 지표 7개(1.7), 그리고 LLM hallucination 방어 경로 각각에 대응하는 이름 있는 테스트가 존재해야 한다. 본 문서 5장의 매핑 표가 그 대장(ledger)이다. 새 실패 모드 발견 시(버그 리포트 포함) — 수정 전에 그것을 재현하는 실패 테스트부터 추가한다(TDD 버그 수정 규칙).
