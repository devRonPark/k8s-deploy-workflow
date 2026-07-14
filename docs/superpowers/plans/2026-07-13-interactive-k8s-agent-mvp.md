# Interactive Kubernetes Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 결정론 preanalyzer 위에, 저장소 분석 → 컴포넌트 선택 → Kubernetes Intent 구축 → 질문/답변 → 매니페스트 생성 → 로컬 검증 → 수정 제안까지 사용자를 안내하는 Python CLI 인터랙티브 에이전트(`k8sagent`)를 만든다.

**Architecture:** 새 최상위 패키지 `src/k8sagent/`가 오케스트레이션 계층(세션, Git 획득, 위저드, ChangeSet, Python 렌더러, 검증 집계)을 담당하고, 기존 `src/preanalyzer/`는 라이브러리로만 소비한다(import 방향: `k8sagent → preanalyzer` 단방향). 결정론 분석·렌더링·검증 판정에 LLM이 개입하는 경로는 없으며, LLM은 설명·질문 문안·NL→ChangeSet 변환·오류 설명·수정 제안에만 쓰이고 모든 출력은 pydantic 스키마 검증을 통과해야 한다.

**Tech Stack:** Python 3.11+, stdlib `argparse`(신규 CLI 프레임워크 없음), Pydantic v2, PyYAML, `openai`(기존 의존성), `unittest`(pytest 금지 — tests/CLAUDE.md), subprocess 기반 git/kubeconform/kubectl. **신규 의존성 추가 없음.**

## Global Constraints

- 신규 pip 의존성 금지 — 기존 `jinja2`, `openai`, `PyYAML`, `pydantic`만 사용 (pyproject.toml:6-11).
- 테스트는 `unittest`만. pytest로 마이그레이션 금지 (tests/CLAUDE.md).
- 실행/검증 명령 형식: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v` (AGENTS.md Completion).
- 결정론 우선: 동일 입력 → 동일 출력. clock·id·subprocess runner는 전부 주입 가능해야 한다 (AGENTS.md Architecture Invariants).
- Secret 값·Git 토큰은 LLM payload, 로그, 세션 파일, 산출물, 예외 메시지 어디에도 실리지 않는다. 토큰은 환경변수 이름으로만 참조한다.
- LLM은 Kubernetes YAML을 생성·수정하지 않는다. 최종 YAML은 오직 `k8sagent/render/`의 Python 렌더러가 만든다.
- 모든 상태 변경성 자연어 요청은 `자연어 → ChangeSet → 스키마+허용경로 검증 → diff → 승인 → Intent 갱신 → 재생성 → 재검증` 순서를 따른다. 미승인 변경 적용 금지.
- 에이전트 상태는 `~/.k8s-agent/`(환경변수 `K8S_AGENT_HOME`으로 재지정 가능) 아래, 생성 산출물은 분석 대상 저장소의 `k8s-agent-output/` 아래에만 쓴다. 애플리케이션 소스 파일은 수정하지 않는다.
- 생성 리소스는 Namespace, Deployment, Service, ConfigMap, 기존 Secret **참조**, Ingress, PVC로 한정. Secret 값 생성 금지. Helm/Kustomize/StatefulSet/Job/CronJob 미지원.
- 검증 체인: YAML 파싱 → 내부 불변식 검증 → kubeconform → `kubectl apply --dry-run=client`. 집계 상태는 `PASS`/`FAIL`/`PARTIAL` 하나. 누락 도구 자동 설치 금지.
- 클러스터 배포, `kubectl apply`, server-side dry-run, 자율 수리 루프는 범위 밖. 검증 실패 → 수정 ChangeSet 제안 → 승인 → 재생성+재검증은 **승인 1회당 1사이클**.
- MVP의 preanalyzer semantic agent 모드는 `disabled` 고정 (아래 Architecture Decision D6 참조).

---

## Part 1 — Current-State Assessment (2026-07-13, main @ 5106c86)

이 절의 모든 항목은 이번 세션에서 직접 열람한 파일·명령 결과에 근거한다.

### 1.1 실제로 존재하고 동작하는 것 (재사용 대상)

| 기능 | 위치 | 상태 · 근거 |
|---|---|---|
| 결정론 Phase-1 파이프라인 (snapshot→inventory→parse→evidence→rule inference) | `src/preanalyzer/pipeline.py` `run_phase1_analysis()` (52-112행) | ✅ 00~04 YAML 산출. clock 주입, `workspace`/`commit` 모드 |
| Git 메타데이터 스냅샷 (commit SHA, dirty 여부, workspace hash) | `src/preanalyzer/analyzer/scanner.py` `snapshot()` (52-106행), `models/snapshot.py` | ✅ 단, **로컬 경로 전용** — clone/fetch 코드는 저장소 전체에 없음 |
| Reconciliation (rules+evidence → ComponentModel/RuntimeModel/DependencyModel/KubernetesIntent/UnresolvedQuestions) | `src/preanalyzer/reconciliation/engine.py` `reconcile()` | ✅ port conflict → 질문 라우팅, 결정론 우선 command 채택 포함 |
| `Tracked[T]` 출처 추적 필드 (value/source/confidence/evidence_refs 불변식) | `src/preanalyzer/models/fields.py` | ✅ `__post_init__`이 value↔source/confidence 불변식 강제 |
| OpenAI-compatible LLM 설정/클라이언트 (env: `SEMANTIC_LLM_BASE_URL/MODEL/API_KEY/TIMEOUT_SECONDS`) | `src/preanalyzer/semantic/llm_config.py`, `semantic/openai_provider.py` | ✅ 스키마 preflight, 오류 코드 분류, code-fence strip 패턴 |
| bounded semantic agent (runtime command 한정) + FakeDecisionProvider | `src/preanalyzer/semantic/agent.py`, `semantic/fake_provider.py` | 🔌 verifier 수락 시에만 반영. MVP 에이전트에서는 사용하지 않음(D6) |
| kubeconform 관리형 바이너리 해석 (`.tools/kubeconform/v0.8.0/...`) | `src/preanalyzer/validator/kubeconform_tool.py` `resolve_kubeconform()`, `scripts/ensure_kubeconform.py` | ✅ 자동 설치 없음, preflight 스크립트 별도 |
| 검증 체인 (yaml→kubeconform→kubectl dry-run client, fail-fast, skipped(tool_not_found)) | `src/preanalyzer/validator/pipeline.py` `ValidationPipeline` | ✅ 단, 결과가 Level 0/1 판정 — PASS/FAIL/PARTIAL 집계는 없음 |
| Jinja2 템플릿 렌더러 (Deployment/Service/ConfigMap/Ingress/SA/Secret placeholder) | `src/preanalyzer/renderer/engine.py`, `renderer/templates/*.j2` | ✅ 단, 신규 제품 결정과 충돌(§2.1) — 에이전트 경로에서는 미사용 |
| Secret 값 비유출 장치 (env 값 폐기, SecretCandidate에 value 필드 없음) | `src/preanalyzer/analyzer/env_safety.py`, `models/rule_inference.py` SecretCandidate | ✅ 회귀 테스트 `tests/unit/test_env_secret_redaction.py` 존재 |
| 경로 안전 장치 (저장소 경계, 제외 디렉터리, 민감 파일 패턴) | `src/preanalyzer/path_safety.py` | ✅ `EXCLUDED_DIR_NAMES`, `SENSITIVE_FILE_PATTERNS` |
| 테스트 기반 (368개 테스트, 픽스처 저장소 5종) | `tests/`, `tests/fixtures/repos/{node-express-like, jpetstore-like, fastapi-fullstack-like, fastapi-shell-entrypoint, port-conflict-node}` | ✅ 이번 세션 전체 실행 결과 `OK (skipped=1)` |
| 기존 CLI | `src/preanalyzer/cli.py` — argparse, `analyze` 단일 커맨드 | ✅ `python -m` 실행 관례 (console script 없음, build-system 미구성) |

### 1.2 없는 것 (이번 MVP가 만드는 것)

- Git URL clone/fetch/checkout, 토큰 인증, 저장소 캐시 — **코드 전무**. `snapshot(url=...)`은 메타데이터 기록용 문자열일 뿐.
- 세션 개념, 상태 저장/재개, `~/.k8s-agent/` — 없음.
- 인터랙티브 위저드/REPL — 없음.
- 컴포넌트 선택 — `reconcile()`은 모든 component candidate를 무조건 포함.
- ChangeSet/승인 모델, NL→구조화 변경 — 없음.
- Namespace/PVC 렌더링, 기존 Secret 참조(`secretKeyRef`) 렌더링 — 기존 렌더러에 없음 (Secret은 placeholder 파일 생성 방식 — 신규 결정과 충돌).
- PASS/FAIL/PARTIAL 집계, K8s 버전 CLI override — 없음 (`ValidationPipeline(k8s_version="1.29")` 하드코딩 기본값만).
- LLM의 설명/질문 문안/오류 해석 연산 — architecture.md 4.4가 기술한 5연산 인터페이스는 **문서상 계획일 뿐 미구현** (bounded agent decision provider만 존재).

### 1.3 Documentation-versus-code discrepancies (중요한 것만)

| # | 문서 주장 | 코드 현실 | 이 플랜의 처리 |
|---|---|---|---|
| D-1 | `docs/user-flow.md` 2.2: "사용자는 Repository URL을 입력한다", "private repo는 git 인증을 그대로 사용" | clone 코드 없음. `preanalyzer analyze`는 로컬 경로만 받음 | Task 4가 Git 획득을 신규 구현 |
| D-2 | `docs/architecture.md` 4.4: Provider Interface 5연산(`analyze_semantics`, `generate_question_wording`, `explain_conflict`, `suggest_patch`, `summarize`) | 해당 인터페이스 없음. `OpenAIChatDecisionProvider.decide()`(bounded agent 전용)만 존재 | Task 11이 에이전트용 typed 연산을 신규 구현 (기존 설정 로더 재사용) |
| D-3 | `pyproject.toml` 13-21행에 pytest 설정/마커 존재 | `tests/CLAUDE.md`: "unittest only — do not migrate to pytest". 전 테스트가 unittest | unittest 유지. pytest 설정은 건드리지 않음 |
| D-4 | `docs/architecture.md` 3.2: `11-deployment-profile.template.yaml`(질문 주석 달린 템플릿) 생성 | `pipeline.py` 247행은 `11-deployment-profile.yaml`에 **사용된** 프로필을 기록. 템플릿 생성 없음 | 에이전트는 질문/답변 모델로 대체하므로 수정하지 않음 |
| D-5 | 기존 렌더러가 Secret placeholder **파일**을 생성 (`renderer/engine.py` 97-100행) | 신규 제품 결정: "Do not generate Secret values", 기존 Secret **참조**만 | 에이전트 렌더러(Task 12)는 `valueFrom.secretKeyRef`만 생성. 기존 Jinja 렌더러는 preanalyzer 경로용으로 그대로 둔다 |
| D-6 | 신규 제품 결정: "Do not use … Jinja templates" | 기존 렌더러는 Jinja2 (`renderer/engine.py` 6행) | 에이전트 경로는 Python dict 렌더러(Task 12) 신규 작성. 기존 코드 리팩터링 금지 원칙에 따라 Jinja 렌더러는 미변경 |
| D-7 | `pipeline.py` 211행이 `15-smoke-test-plan.yaml`을 빈 stub으로 기록 | architecture.md는 Step 14 산출물로 기술 | MVP 범위 밖. 미변경 |

### 1.4 이 플랜이 기존 코드에 가하는 유일한 수정

`src/preanalyzer/path_safety.py`의 `REPO_EXCLUDED_GLOBS` / `EXCLUDED_DIR_NAMES`에 `k8s-agent-output` 추가 + 그에 따른 `src/preanalyzer/rules_version.py` 범프 `"2026.07"` → `"2026.07.1"` (Task 5). 이유: 산출물을 분석 대상 저장소 안에 쓰라는 제품 결정 때문에, 재분석 시 생성된 매니페스트가 `kubernetes_manifests` inventory로 역유입되어 evidence를 오염시키는 경로를 차단해야 한다. 스캔 규칙 변경은 inventory 산출에 영향을 주므로 재현성 계약(P10: 같은 commit + 같은 rules_version = 같은 산출물)상 버전 범프가 필수다(테스트는 `RULES_VERSION`을 심볼로만 참조 — 값 고정 단언 없음을 grep으로 확인). `tests/unit/test_scanner.py`는 `assertIn` 방식이므로(91행) 패턴 추가는 기존 단언을 깨지 않는다 — Task 5에서 전체 스위트로 확인한다. 그 외 preanalyzer 프로덕션 코드는 일절 수정하지 않는다.

---

## Part 2 — Architecture Decision

### 2.1 선택: 별도 오케스트레이션 패키지 `src/k8sagent/`

**채택 이유:**
- `docs/architecture.md` 1.2의 레이어 표가 "Orchestrator (CLI)"를 별도 관심사로 이미 예약해 두었다.
- preanalyzer의 불변식("Deterministic First", "no LLM in the loop" — src/CLAUDE.md)을 건드리지 않고 위에 쌓을 수 있다. import 방향이 `k8sagent → preanalyzer` 단방향이면 결정론 분석기의 LLM 독립성이 구조적으로 유지된다.
- 기존 368개 테스트와 산출물 계약(00~15 파일)이 그대로 보존된다.

**기각한 대안:**
1. **`preanalyzer` 패키지 내부 확장** (`preanalyzer/agent/` 서브패키지) — 기각. src/CLAUDE.md가 "no LLM in the loop"를 패키지 정체성으로 선언하고 있고, 세션/REPL/Git 획득은 분석기 책임이 아니다. 레이어 결합 규칙 위반.
2. **기존 `run_analysis()` 확장 + CLI 플래그 증설** — 기각. `run_analysis`는 Jinja 렌더러+프로필 병합에 강결합돼 있어(187-212행) 신규 제품 결정(Jinja 금지, ChangeSet 흐름)과 정면 충돌. 분기 플래그 지옥이 된다.
3. **별도 저장소/배포 패키지** — 기각. 픽스처·모델·검증 코드를 공유해야 하고, 저장소는 이미 `src/` 다중 패키지 배치(PYTHONPATH=src)를 지원한다.

### 2.2 세부 설계 결정 (D1~D10)

| # | 결정 | 근거 |
|---|---|---|
| D1 | CLI 프레임워크 = stdlib **argparse**, REPL = `input()` 기반 라인 루프 + 주입 가능한 `Console` 추상화 | 기존 `preanalyzer/cli.py`와 동일 관례. 신규 의존성 0. 테스트는 scripted IO로 결정론적 |
| D2 | 실행 방식 = `PYTHONPATH=src python3 -m k8sagent` | pyproject에 build-system이 없어 console script가 설치되지 않음(검증: pyproject.toml 전체 21행). 기존 관례 유지 |
| D3 | 설정 우선순위 = CLI 플래그 > 환경변수(`K8S_AGENT_*`) > `~/.k8s-agent/config.yaml` > 내장 기본값 | 표준 12-factor 순서. 테스트는 `K8S_AGENT_HOME`으로 격리 |
| D4 | LLM 설정 = 기존 `load_semantic_llm_settings()` 재사용 (같은 `SEMANTIC_LLM_*` 환경변수) | "one OpenAI-compatible API configuration" 요구를 기존 검증된 로더로 충족. 설정 이원화 방지 |
| D5 | Git 토큰 = `K8S_AGENT_GIT_TOKEN` 환경변수, **GIT_ASKPASS 헬퍼** 경유 주입 | URL 삽입 방식은 `.git/config`에 토큰이 영속되므로 기각. askpass는 argv·디스크·git config 어디에도 토큰을 남기지 않음 |
| D6 | 에이전트의 preanalyzer 호출은 `semantic_mode="disabled"` 고정 | `run_phase1_analysis()`는 verifier 수락 command를 반환하지 않고 버린다(pipeline.py 92행 `_accepted_commands` 미반환). 시그니처 변경 없이는 semantic 결과를 reconcile에 전달할 수 없고, MVP 필수 범위도 아니다. 결정론 폴백이 항상 존재하므로 기능 손실 없음. **사용자 확인(2026-07-13): MVP는 disabled 유지, 연결(non-breaking 래퍼)은 2단계 백로그** |
| D7 | 에이전트 Intent = 신규 `k8sagent/models/intent.py` (기존 `preanalyzer.models.intent`를 초기값 소스로 소비) | 기존 Intent는 replicas/PVC/secret ref/ingress path가 없는 최소 모델(intent.py 전체 39행)이고 Jinja 렌더러와 계약이 묶여 있다. 기존 모델 확장은 "unrelated refactoring 금지"에 저촉 |
| D8 | `Tracked[T]` 재사용 (`preanalyzer.models.fields`) | 출처 추적 불변식을 공짜로 얻음. 사용자 답변은 `source="user_decision", confidence=HIGH` |
| D9 | 산출물 디렉터리 = `<repo>/k8s-agent-output/{analysis,intent,manifests,validation}` | 제품 결정("generated-output directory under the analyzed repository") 준수 + Task 5의 스캔 제외로 역유입 차단 |
| D10 | 렌더러 = 리소스별 순수 함수 `(spec 모델) -> dict`, 직렬화는 단일 `to_yaml()` | dict 구성 순서가 곧 출력 순서(`sort_keys=False`) → 동일 Intent = byte 동일 YAML. 저장소 접근·LLM 호출 경로가 시그니처상 없음 |
| D11 | 로컬 경로 + `--ref` = 해당 로컬 저장소를 `file://` URL로 **캐시에 clone 후 checkout** (ref 미지정 시엔 기존대로 작업 트리 직접 분석) | 사용자 결정(2026-07-13). "branch/tag/commit 선택" 요구를 로컬에도 충족하면서 사용자 작업 트리를 절대 건드리지 않는다 |
| D12 | SSH URL(`git@…`, `ssh://…`)은 **명시적 거부** — `RepoAcquisitionError("SSH URLs are not supported; use an HTTPS URL or a local path")` | 사용자 결정(2026-07-13). 요구 범위는 로컬/공개 URL/HTTPS+토큰뿐. ssh-agent 의존 경로는 테스트 불가·예측 불가 |

### 2.3 Data Flow

```text
사용자 입력 (local path | git URL, --ref)
   │  [Task 4] repo.py: clone/fetch→checkout→rev-parse (캐시 ~/.k8s-agent/cache/<url-hash>)
   ▼
AcquiredRepo(repo_path, RepoSource{kind,location,ref,commit_sha})
   │  [Task 5] analysis.py: preanalyzer.run_phase1_analysis(semantic=disabled)
   │           + reconcile() → <repo>/k8s-agent-output/analysis/00~10-*.yaml
   ▼
AnalysisBundle(snapshot, inventory, evidence, rules, reconciliation)
   │  [Task 6] components.py: 후보 추출 → 사용자 선택 → 제외 의존성 경고
   ▼
SelectionResult ──[Task 7]──▶ ApplicationTopology (topology.yaml)
   │  [Task 8] intent_builder.py: topology + baseline intent → AgentKubernetesIntent
   ▼
AgentKubernetesIntent (intent/intent.yaml)
   │  [Task 9] gaps.py: find_unresolved() → questions.py: 결정론 질문
   │           (LLM phrase_question은 문안만 교체 가능 — 후보/타입 불변)
   │  답변 → set_intent_path(source="user_decision")
   │  [Task 10] NL 요청 → ChangeSet → 검증 → diff → 승인 → 적용 (매 변경 공통 경로)
   ▼
resolved Intent ──[Task 12]──▶ render_all() → manifests/*.yaml (Python 렌더러, LLM·repo 접근 불가)
   │  [Task 13] validate.py: yaml→invariants→kubeconform→kubectl dry-run(client)
   ▼
AgentValidationReport{aggregate: PASS|FAIL|PARTIAL} (validation/report.yaml)
   │  FAIL 시 [Task 14]: 결정론 매핑 테이블 → (없으면 LLM propose_correction)
   │  → ChangeSet → diff → 승인 → 재생성+재검증 (승인 1회당 1사이클)
   ▼
세션 종료 (~/.k8s-agent/sessions/<id>/session.json 에 전 과정 기록, 토큰 제외)
```

세션 상태 기계 (Task 3): `created → repo_ready → analyzed → components_selected → intent_drafted → intent_resolved → plan_approved → generated → validated → completed` (+ 어느 상태에서든 `failed`). 역방향 전이는 두 개만 허용: `plan_approved → intent_resolved`(승인된 ChangeSet 적용 시)와 `validated → generated`(승인된 수정 재생성 시).

---

## Part 3 — File Structure

```text
src/k8sagent/                      # 전부 신규
├── __init__.py                    # __version__
├── __main__.py                    # python -m k8sagent
├── cli.py                         # argparse 트리, exit code 매핑        [Task 15]
├── config.py                      # AgentConfig, load_config             [Task 1]
├── errors.py                      # AgentError 계열                      [Task 1]
├── procutil.py                    # run_command + 토큰 redaction         [Task 2]
├── session.py                     # SessionState/AgentSession/SessionStore [Task 3]
├── repo.py                        # acquire_local/acquire_git/캐시       [Task 4]
├── analysis.py                    # preanalyzer 어댑터, AnalysisBundle   [Task 5]
├── components.py                  # 후보 추출/선택/의존성 경고           [Task 6]
├── gaps.py                        # find_unresolved                      [Task 9]
├── questions.py                   # Question/답변 파싱/적용              [Task 9]
├── changeset.py                   # ChangeSet/허용경로/diff/apply        [Task 10]
├── llm.py                         # AgentLLMClient + Fake용 프로토콜     [Task 11]
├── corrections.py                 # 결정론 수정 테이블 + 수정 사이클     [Task 14]
├── interactive.py                 # Console/Wizard REPL                  [Task 16]
├── models/
│   ├── __init__.py
│   ├── topology.py                # ApplicationTopology                  [Task 7]
│   ├── intent.py                  # AgentKubernetesIntent + set_intent_path [Task 8]
│   └── report.py                  # CheckResult/AgentValidationReport    [Task 13]
├── render/
│   ├── __init__.py                # render_all                           [Task 12]
│   ├── resources.py               # 리소스별 순수 함수                   [Task 12]
│   ├── policy.py                  # labels/annotations (managed-by=k8s-agent) [Task 12]
│   └── serialize.py               # to_yaml                              [Task 12]
└── validate.py                    # 체크 어댑터 + PASS/FAIL/PARTIAL 집계 [Task 13]

src/preanalyzer/path_safety.py     # 수정: k8s-agent-output 제외 패턴 추가 [Task 5]

tests/unit/agent/                  # 신규 (unittest)
├── __init__.py
├── helpers.py                     # FakeLLM, ScriptedConsole, FakeRunner, make_git_repo
├── test_config.py                 # [Task 1]
├── test_procutil.py               # [Task 2]
├── test_session.py                # [Task 3]
├── test_repo.py                   # [Task 4]
├── test_analysis.py               # [Task 5]
├── test_components.py             # [Task 6]
├── test_topology.py               # [Task 7]
├── test_intent.py                 # [Task 8]
├── test_gaps_questions.py         # [Task 9]
├── test_changeset.py              # [Task 10]
├── test_llm.py                    # [Task 11]
├── test_render.py                 # [Task 12]
├── test_validate.py               # [Task 13]
├── test_corrections.py            # [Task 14]
├── test_cli_agent.py              # [Task 15]
└── test_interactive.py            # [Task 16]

tests/acceptance/test_agent_workflow.py   # E2E                           [Task 17]
tests/fixtures/agent/answers-node.yaml    # 비대화형 답변 파일 픽스처      [Task 15]
```

명명 규칙: 모든 신규 YAML 산출물은 snake-case 키, `yaml.safe_dump(sort_keys=False)` — 기존 `pipeline._write_yaml()`(608-612행)과 동일한 방식.

<!-- PLAN-TASKS-BEGIN -->

---

## Part 4 — Tasks

공통 규칙 (모든 태스크에 적용, 반복 서술 생략):

- 테스트 실행 명령 축약형 `RUN_UNIT="PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest"` 를 문서 내 표기로 쓴다. 실제 실행 시 풀어서 입력한다.
- 커밋 메시지는 기존 이력 관례(`feat:`/`test:`/`fix:`/`docs:`, git log 확인 결과) 를 따른다.
- 각 태스크 완료 시점에 해당 테스트 모듈이 통과해야 하고, Task 5·17은 전체 스위트를 돌린다(다른 태스크는 신규 모듈 테스트만으로 충분 — preanalyzer를 수정하지 않기 때문).

### Task 1: Package Skeleton, Error Taxonomy, Config Loading

**목표:** `k8sagent` 패키지 골격과 오류 분류, `CLI > env > file > default` 우선순위의 설정 로딩을 만든다.

**이유:** 모든 후속 태스크가 `AgentConfig`(홈 디렉터리, K8s 버전, LLM on/off, 토큰 env 이름)와 오류 계층에 의존한다.

**Files:**
- Create: `src/k8sagent/__init__.py`, `src/k8sagent/errors.py`, `src/k8sagent/config.py`
- Test: `tests/unit/agent/__init__.py`, `tests/unit/agent/test_config.py`

**Interfaces:**
- Produces:
  - `errors.AgentError(Exception)` — `code: str` 속성. 하위: `ConfigError("config_error")`, `RepoAcquisitionError("repo_acquisition_error")`, `SessionError("session_error")`, `AnalysisError("analysis_error")`, `ChangeSetError("changeset_error")`, `RenderError("render_error")`, `ValidationRunError("validation_run_error")`, `LLMUnavailableError("llm_unavailable")`
  - `config.AgentConfig(BaseModel, frozen)`: `home: Path`, `k8s_version: str = "1.29"`, `git_token_env: str = "K8S_AGENT_GIT_TOKEN"`, `llm_enabled: bool = True`, `kubeconform_path: Path | None = None`
  - `config.load_config(cli_overrides: dict[str, object] | None = None, env: Mapping[str, str] | None = None, home_override: Path | None = None) -> AgentConfig`
- Consumes: 없음 (stdlib + pydantic만)

**데이터/제어 흐름:** `load_config`는 (1) `home` 결정: `home_override` > `env["K8S_AGENT_HOME"]` > `~/.k8s-agent` → (2) `home/config.yaml`이 있으면 `yaml.safe_load`로 file 계층 로드(모르는 키는 `ConfigError`) → (3) env 계층: `K8S_AGENT_K8S_VERSION`, `K8S_AGENT_NO_LLM`(값 "1"/"true"→`llm_enabled=False`), `K8S_AGENT_KUBECONFORM_PATH` → (4) `cli_overrides` 계층(None 값은 무시) → 병합해 `AgentConfig` 생성.

**에러·보안:** 토큰 **값**은 AgentConfig에 절대 저장하지 않는다 — 환경변수 **이름**(`git_token_env`)만 보관하고 값은 git 호출 시점(Task 4)에 읽는다. config.yaml 파싱 실패·미지의 키는 `ConfigError`(메시지에 파일 경로만, 값 미포함).

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/agent/test_config.py`

```python
import tempfile
import unittest
from pathlib import Path

from k8sagent.config import AgentConfig, load_config
from k8sagent.errors import AgentError, ConfigError


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config(env={}, home_override=Path("/tmp/x"))
        self.assertEqual(cfg.k8s_version, "1.29")
        self.assertTrue(cfg.llm_enabled)
        self.assertEqual(cfg.git_token_env, "K8S_AGENT_GIT_TOKEN")
        self.assertEqual(cfg.home, Path("/tmp/x"))

    def test_precedence_cli_over_env_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("k8s_version: '1.27'\n", encoding="utf-8")
            env = {"K8S_AGENT_K8S_VERSION": "1.28"}
            self.assertEqual(load_config(env=env, home_override=home).k8s_version, "1.28")
            cfg = load_config(cli_overrides={"k8s_version": "1.30"}, env=env, home_override=home)
            self.assertEqual(cfg.k8s_version, "1.30")

    def test_file_only_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("k8s_version: '1.27'\n", encoding="utf-8")
            self.assertEqual(load_config(env={}, home_override=home).k8s_version, "1.27")

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("registry: oops\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(env={}, home_override=home)

    def test_no_llm_env(self):
        cfg = load_config(env={"K8S_AGENT_NO_LLM": "1"}, home_override=Path("/tmp/x"))
        self.assertFalse(cfg.llm_enabled)

    def test_home_from_env(self):
        cfg = load_config(env={"K8S_AGENT_HOME": "/tmp/agent-home"})
        self.assertEqual(cfg.home, Path("/tmp/agent-home"))

    def test_error_taxonomy_codes(self):
        self.assertEqual(ConfigError("x").code, "config_error")
        self.assertIsInstance(ConfigError("x"), AgentError)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_config.py" -v` / Expected: `ModuleNotFoundError: No module named 'k8sagent'`
- [ ] **Step 3: 구현** — `errors.py`:

```python
from __future__ import annotations


class AgentError(Exception):
    code: str = "agent_error"


class ConfigError(AgentError):
    code = "config_error"


class RepoAcquisitionError(AgentError):
    code = "repo_acquisition_error"


class SessionError(AgentError):
    code = "session_error"


class AnalysisError(AgentError):
    code = "analysis_error"


class ChangeSetError(AgentError):
    code = "changeset_error"


class RenderError(AgentError):
    code = "render_error"


class ValidationRunError(AgentError):
    code = "validation_run_error"


class LLMUnavailableError(AgentError):
    code = "llm_unavailable"
```

`config.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from k8sagent.errors import ConfigError

_FILE_KEYS = {"k8s_version", "llm_enabled", "git_token_env", "kubeconform_path"}
_TRUTHY = {"1", "true", "yes"}


class AgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    home: Path
    k8s_version: str = "1.29"
    git_token_env: str = "K8S_AGENT_GIT_TOKEN"
    llm_enabled: bool = True
    kubeconform_path: Path | None = None


def load_config(
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    home_override: Path | None = None,
) -> AgentConfig:
    import os

    env = os.environ if env is None else env
    home = Path(home_override or env.get("K8S_AGENT_HOME") or Path.home() / ".k8s-agent")

    merged: dict[str, object] = {"home": home}
    config_file = home / "config.yaml"
    if config_file.is_file():
        try:
            raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid config file: {config_file}") from exc
        unknown = set(raw) - _FILE_KEYS
        if unknown:
            raise ConfigError(f"unknown config keys in {config_file}: {sorted(unknown)}")
        merged.update(raw)

    if env.get("K8S_AGENT_K8S_VERSION"):
        merged["k8s_version"] = env["K8S_AGENT_K8S_VERSION"]
    if env.get("K8S_AGENT_NO_LLM", "").lower() in _TRUTHY:
        merged["llm_enabled"] = False
    if env.get("K8S_AGENT_KUBECONFORM_PATH"):
        merged["kubeconform_path"] = env["K8S_AGENT_KUBECONFORM_PATH"]

    for key, value in (cli_overrides or {}).items():
        if value is not None:
            merged[key] = value

    try:
        return AgentConfig(**merged)
    except ValidationError as exc:
        raise ConfigError("invalid agent configuration") from exc
```

`__init__.py`: `__version__ = "0.1.0"` 한 줄. `tests/unit/agent/__init__.py`: 빈 파일.

- [ ] **Step 4: 통과 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_config.py" -v` / Expected: `OK (7 tests)`
- [ ] **Step 5: Commit** — `git add src/k8sagent tests/unit/agent && git commit -m "feat: k8sagent package skeleton, errors, config loading"`

**완료 조건:** 7개 테스트 통과. `AgentConfig`에 토큰 값 필드가 없음(코드 리뷰로 확인).

---

### Task 2: Subprocess Runner with Secret Redaction

**목표:** git/kubeconform/kubectl 호출 공용 subprocess 래퍼. 지정된 비밀 문자열이 stdout/stderr/예외 메시지에서 항상 `***`로 마스킹된다.

**이유:** Task 4(토큰 인증 git), Task 13(검증 도구)이 공유. redaction을 한 곳에 강제해야 토큰 유출 경로가 구조적으로 사라진다.

**Files:**
- Create: `src/k8sagent/procutil.py`
- Test: `tests/unit/agent/test_procutil.py`

**Interfaces:**
- Produces:
  - `ProcResult` (frozen dataclass): `returncode: int`, `stdout: str`, `stderr: str`
  - `run_command(argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None, timeout: float = 120.0, redact: Sequence[str] = ()) -> ProcResult`
  - `redact_text(text: str, secrets: Sequence[str]) -> str`
- Consumes: `errors.AgentError`

**에러·보안:** `env`는 **전달된 것만** 사용(None이면 `os.environ` 복사) — 호출자가 최소 env를 구성할 수 있게 한다. 타임아웃·OSError는 `AgentError`로 감싸되 메시지도 redact. 빈 문자열 secret은 무시(전체 마스킹 사고 방지).

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/agent/test_procutil.py`

```python
import unittest

from k8sagent.errors import AgentError
from k8sagent.procutil import ProcResult, redact_text, run_command


class ProcutilTests(unittest.TestCase):
    def test_run_echo(self):
        result = run_command(["echo", "hello"])
        self.assertIsInstance(result, ProcResult)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_stdout_redacted(self):
        result = run_command(["echo", "token=s3cr3t done"], redact=["s3cr3t"])
        self.assertNotIn("s3cr3t", result.stdout)
        self.assertIn("***", result.stdout)

    def test_stderr_redacted(self):
        result = run_command(
            ["sh", "-c", "echo bad-s3cr3t >&2; exit 1"], redact=["s3cr3t"]
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("s3cr3t", result.stderr)

    def test_timeout_raises_redacted_error(self):
        with self.assertRaises(AgentError) as ctx:
            run_command(["sh", "-c", "sleep 5"], timeout=0.2, redact=["sleep"])
        self.assertNotIn("sleep", str(ctx.exception))

    def test_missing_binary_raises(self):
        with self.assertRaises(AgentError):
            run_command(["definitely-not-a-binary-xyz"])

    def test_redact_empty_secret_ignored(self):
        self.assertEqual(redact_text("abc", ["", "b"]), "a***c")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_procutil.py" -v` / Expected: `ModuleNotFoundError`
- [ ] **Step 3: 구현** — `procutil.py`

```python
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from k8sagent.errors import AgentError


@dataclass(frozen=True)
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


def redact_text(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 120.0,
    redact: Sequence[str] = (),
) -> ProcResult:
    run_env = dict(os.environ) if env is None else dict(env)
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(redact_text(f"command timed out after {timeout}s: {argv[0]}", redact)) from exc
    except OSError as exc:
        raise AgentError(redact_text(f"command failed to start: {argv[0]}: {exc}", redact)) from exc
    return ProcResult(
        returncode=proc.returncode,
        stdout=redact_text(proc.stdout or "", redact),
        stderr=redact_text(proc.stderr or "", redact),
    )
```

- [ ] **Step 4: 통과 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_procutil.py" -v` / Expected: `OK (6 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: agent subprocess runner with secret redaction"`

**완료 조건:** 6개 테스트 통과. redaction이 stdout/stderr/예외 3경로 모두에서 검증됨.

---

### Task 3: Session Model, Store, State Machine

**목표:** `~/.k8s-agent/sessions/<id>/session.json`에 세션을 원자적으로 저장/로드/재개하고, 상태 전이를 화이트리스트로 강제한다.

**이유:** 대화형/비대화형 워크플로우 모두 세션이 단일 진실 소스다. 재개(resume)와 비대화형 다단계 커맨드(analyze→select→answer→generate→validate)가 이것에 의존한다.

**Files:**
- Create: `src/k8sagent/session.py`
- Test: `tests/unit/agent/test_session.py`

**Interfaces:**
- Produces:
  - `SessionState(str, Enum)`: `CREATED="created"`, `REPO_READY="repo_ready"`, `ANALYZED="analyzed"`, `COMPONENTS_SELECTED="components_selected"`, `INTENT_DRAFTED="intent_drafted"`, `INTENT_RESOLVED="intent_resolved"`, `PLAN_APPROVED="plan_approved"`, `GENERATED="generated"`, `VALIDATED="validated"`, `COMPLETED="completed"`, `FAILED="failed"`
  - `RepoSource(BaseModel)`: `kind: Literal["local", "git_url"]`, `location: str`(경로 또는 URL — 자격증명 미포함), `ref: str | None`, `commit_sha: str | None`, `cache_path: str | None`
  - `AgentSession(BaseModel)`: `session_id: str`, `created_at: str`, `updated_at: str`, `state: SessionState`, `source: RepoSource | None = None`, `repo_path: str | None = None`, `output_dir: str | None = None`, `selected_components: list[str] = []`, `excluded_components: list[str] = []`, `answers: dict[str, str | int | bool] = {}`, `applied_changes: list[dict] = []`(직렬화된 ChangeSet), `k8s_version: str`, `llm_enabled: bool`
  - `advance(session: AgentSession, new_state: SessionState, clock) -> AgentSession` — 전이 검증, `updated_at` 갱신, 위반 시 `SessionError`
  - `SessionStore(home: Path, clock: Callable[[], datetime] = ..., id_factory: Callable[[], str] | None = None)`: `.create(k8s_version, llm_enabled) -> AgentSession`, `.save(session) -> None`(tmp 파일 + `os.replace` 원자 쓰기), `.load(session_id) -> AgentSession`, `.list_sessions() -> list[AgentSession]`
- Consumes: `errors.SessionError`

**허용 전이:** 위 데이터 흐름의 순방향 체인 + `plan_approved→intent_resolved`, `validated→generated`, 임의 상태→`failed`. 그 외 전부 `SessionError`.

**에러·보안:** 세션 JSON에 토큰이 실릴 수 있는 필드 자체가 없다(`RepoSource.location`은 자격증명 없는 URL — Task 4가 보장). 손상된 JSON 로드는 `SessionError`. `id_factory` 기본값은 `lambda: f"{clock():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/agent/test_session.py`

```python
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8sagent.errors import SessionError
from k8sagent.session import AgentSession, SessionState, SessionStore, advance

FIXED = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def make_store(tmp: str) -> SessionStore:
    return SessionStore(Path(tmp), clock=lambda: FIXED, id_factory=lambda: "s-test01")


class SessionTests(unittest.TestCase):
    def test_create_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            session = store.create(k8s_version="1.29", llm_enabled=False)
            self.assertEqual(session.session_id, "s-test01")
            self.assertEqual(session.state, SessionState.CREATED)
            store.save(session)
            loaded = store.load("s-test01")
            self.assertEqual(loaded, session)

    def test_valid_transition_chain(self):
        session = AgentSession(
            session_id="s", created_at="t", updated_at="t",
            state=SessionState.CREATED, k8s_version="1.29", llm_enabled=True)
        for state in [SessionState.REPO_READY, SessionState.ANALYZED,
                      SessionState.COMPONENTS_SELECTED, SessionState.INTENT_DRAFTED,
                      SessionState.INTENT_RESOLVED, SessionState.PLAN_APPROVED,
                      SessionState.GENERATED, SessionState.VALIDATED,
                      SessionState.COMPLETED]:
            session = advance(session, state, clock=lambda: FIXED)
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_backward_loops_allowed(self):
        base = dict(session_id="s", created_at="t", updated_at="t",
                    k8s_version="1.29", llm_enabled=True)
        s1 = AgentSession(state=SessionState.PLAN_APPROVED, **base)
        self.assertEqual(advance(s1, SessionState.INTENT_RESOLVED, clock=lambda: FIXED).state,
                         SessionState.INTENT_RESOLVED)
        s2 = AgentSession(state=SessionState.VALIDATED, **base)
        self.assertEqual(advance(s2, SessionState.GENERATED, clock=lambda: FIXED).state,
                         SessionState.GENERATED)

    def test_invalid_transition_rejected(self):
        session = AgentSession(
            session_id="s", created_at="t", updated_at="t",
            state=SessionState.CREATED, k8s_version="1.29", llm_enabled=True)
        with self.assertRaises(SessionError):
            advance(session, SessionState.GENERATED, clock=lambda: FIXED)

    def test_any_state_can_fail(self):
        session = AgentSession(
            session_id="s", created_at="t", updated_at="t",
            state=SessionState.ANALYZED, k8s_version="1.29", llm_enabled=True)
        self.assertEqual(advance(session, SessionState.FAILED, clock=lambda: FIXED).state,
                         SessionState.FAILED)

    def test_load_missing_session_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SessionError):
                make_store(tmp).load("nope")

    def test_session_file_never_contains_token_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            session = store.create(k8s_version="1.29", llm_enabled=True)
            store.save(session)
            raw = (Path(tmp) / "sessions" / "s-test01" / "session.json").read_text(encoding="utf-8")
            payload = json.loads(raw)
            self.assertNotIn("token", raw.lower())
            self.assertNotIn("api_key", set(payload))

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            store.save(store.create(k8s_version="1.29", llm_enabled=True))
            self.assertEqual([s.session_id for s in store.list_sessions()], ["s-test01"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_session.py" -v` / Expected: `ModuleNotFoundError`
- [ ] **Step 3: 구현** — `session.py`. 핵심 조각:

```python
_FORWARD = [
    SessionState.CREATED, SessionState.REPO_READY, SessionState.ANALYZED,
    SessionState.COMPONENTS_SELECTED, SessionState.INTENT_DRAFTED,
    SessionState.INTENT_RESOLVED, SessionState.PLAN_APPROVED,
    SessionState.GENERATED, SessionState.VALIDATED, SessionState.COMPLETED,
]
ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    state: {nxt} for state, nxt in zip(_FORWARD, _FORWARD[1:])
}
ALLOWED_TRANSITIONS[SessionState.PLAN_APPROVED].add(SessionState.INTENT_RESOLVED)
ALLOWED_TRANSITIONS[SessionState.VALIDATED].add(SessionState.GENERATED)
for state in list(SessionState):
    if state is not SessionState.FAILED:
        ALLOWED_TRANSITIONS.setdefault(state, set()).add(SessionState.FAILED)


def advance(session: AgentSession, new_state: SessionState, clock) -> AgentSession:
    if new_state not in ALLOWED_TRANSITIONS.get(session.state, set()):
        raise SessionError(f"illegal transition {session.state.value} -> {new_state.value}")
    return session.model_copy(update={"state": new_state, "updated_at": _fmt(clock())})
```

`SessionStore.save`: `sessions/<id>/` 생성 → `session.json.tmp`에 `session.model_dump_json(indent=2)` 기록 → `os.replace`. `load`: 파일 부재/`json.JSONDecodeError`/`ValidationError` → `SessionError`. `list_sessions`: `sessions/*/session.json` 정렬 로드.

- [ ] **Step 4: 통과 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_session.py" -v` / Expected: `OK (8 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: agent session store and state machine"`

**완료 조건:** 8개 테스트 통과. 전이 화이트리스트 위반이 전부 `SessionError`.

---

### Task 4: Repository Acquisition (local + Git URL + token + cache)

**목표:** 로컬 경로 검증, Git URL clone/fetch/checkout, `K8S_AGENT_GIT_TOKEN` 기반 private HTTPS 인증, `~/.k8s-agent/cache/` 캐시, 정확한 commit SHA 기록. 토큰은 디스크·argv·로그 어디에도 남지 않는다.

**이유:** MVP 1~2단계(저장소 수용, 정확한 리비전 준비)가 이 모듈이다. 저장소에 clone 코드가 전무함을 확인했다(§1.2).

**Files:**
- Create: `src/k8sagent/repo.py`
- Test: `tests/unit/agent/test_repo.py`, `tests/unit/agent/helpers.py` (git 픽스처 헬퍼 시작)

**Interfaces:**
- Produces:
  - `AcquiredRepo` (frozen dataclass): `repo_path: Path`, `source: RepoSource`
  - `acquire_local(path: str, ref: str | None = None, *, cache_root: Path | None = None, runner=run_command) -> AcquiredRepo` — `resolve_repository_path`로 정규화, 디렉터리 아니면 `RepoAcquisitionError`. **ref 미지정**: 작업 트리를 그대로 분석(kind="local", 사용자 작업물 무접촉). **ref 지정(D11)**: `acquire_git(f"file://{resolved}", ref, cache_root=…)`에 위임 — 캐시 사본에 clone+checkout하므로 역시 원본 무접촉. 반환 source는 kind="git_url", location=`file://` URL(세션 재현 가능)
  - `acquire_git(url: str, ref: str | None, *, cache_root: Path, token: str | None, runner=run_command, clock=None) -> AcquiredRepo` — SSH URL(`git@` 또는 `ssh://` 접두)은 즉시 `RepoAcquisitionError("SSH URLs are not supported; use an HTTPS URL or a local path")` (D12)
  - `is_git_url(text: str) -> bool` — `https://`, `http://`, `git@`, `ssh://`, `file://` 접두 판정(라우팅용 — SSH는 acquire_git가 거부)
- Consumes: `procutil.run_command`, `preanalyzer.path_safety.resolve_repository_path`, `session.RepoSource`, `errors.RepoAcquisitionError`

**acquire_git 제어 흐름:**
1. `cache_dir = cache_root / hashlib.sha256(url.encode()).hexdigest()[:16]`
2. `cache_dir/.git` 없으면 `git clone --no-tags <url> <cache_dir>`, 있으면 `git -C <cache_dir> fetch origin --prune`
3. ref 해석 순서(각각 `git rev-parse --verify`): 그대로(`<ref>^{commit}`) → `origin/<ref>` → 실패 시 `RepoAcquisitionError("ref not found: <ref>")`. ref 미지정이면 `origin/HEAD`
4. `git -C <cache_dir> checkout --detach <해석된 SHA>`
5. `commit_sha = git rev-parse HEAD` 결과를 `RepoSource.commit_sha`에 기록
6. 반환: `AcquiredRepo(repo_path=cache_dir, source=RepoSource(kind="git_url", location=url, ref=ref, commit_sha=sha, cache_path=str(cache_dir)))`

**토큰 주입 (https URL + token 존재 시에만):**
- askpass 셸 스크립트를 `cache_root/askpass.sh`로 1회 생성(chmod 0o700). 내용은 토큰을 **포함하지 않는다**:

```sh
#!/bin/sh
case "$1" in
  Username*) echo "${K8S_AGENT_GIT_ASKPASS_USER:-x-access-token}" ;;
  *) echo "$K8S_AGENT_GIT_ASKPASS_PASS" ;;
esac
```

- git subprocess env: `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=<askpass.sh>`, `K8S_AGENT_GIT_ASKPASS_PASS=<token>` (+ `PATH`, `HOME` 등 최소 상속). URL은 무변경 → `.git/config`에 자격증명이 영속되지 않는다.
- 모든 git 호출에 `redact=[token]` 전달 → stderr에 토큰이 에코돼도 `***`.
- 플랫폼 노트: askpass는 POSIX 셸 전제(현 환경 Linux/WSL2). Windows 지원은 MVP 밖으로 명시.

**에러·보안:** clone/fetch/checkout 실패 → returncode 검사 후 `RepoAcquisitionError(redacted stderr 요약)`. 토큰이 세션·예외·캐시 디스크에 없음을 테스트로 강제.

- [ ] **Step 1: 실패 테스트 작성** — `helpers.py`에 로컬 git 픽스처 빌더:

```python
def make_git_repo(base: Path, *, files: dict[str, str] | None = None) -> Path:
    """base 아래에 커밋 1개를 가진 실제 git 저장소를 만든다."""
    repo = base / "origin-repo"
    repo.mkdir()
    for rel, text in (files or {"Dockerfile": "FROM python:3.11\nCMD [\"python\", \"app.py\"]\n"}).items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return repo
```

`test_repo.py` 핵심 케이스:

```python
class AcquireLocalTests(unittest.TestCase):
    def test_local_path_resolved(self):        # fixture repo 경로 → AcquiredRepo(kind="local"), repo_path == 원본
    def test_local_missing_path_raises(self):  # RepoAcquisitionError
    def test_local_with_ref_clones_to_cache(self):
        # make_git_repo에 커밋 2개 → acquire_local(path, ref=<첫 SHA>, cache_root=tmp)
        # → repo_path가 cache_root 하위, HEAD == 첫 SHA, 원본 저장소 HEAD 불변,
        #   source.kind == "git_url", source.location이 file:// URL (D11)

class AcquireGitTests(unittest.TestCase):
    def test_ssh_url_rejected(self):
        # acquire_git("git@github.com:a/b.git", ...) / "ssh://..." →
        # RepoAcquisitionError, 메시지에 "SSH URLs are not supported" (D12)
    def test_clone_records_exact_sha(self):
        # make_git_repo → file:// URL → acquire_git → commit_sha == rev-parse HEAD of origin
    def test_second_acquire_uses_cache_fetch(self):
        # 같은 URL 2회 → cache_dir 동일, .git 재사용 (clone이 아닌 fetch 경로 — FakeRunner로 argv 검증)
    def test_ref_branch_and_sha_checkout(self):
        # origin에 두 번째 커밋 → ref=<첫 SHA> 로 acquire → repo HEAD == 첫 SHA
    def test_unknown_ref_raises(self):

class TokenSafetyTests(unittest.TestCase):
    def test_token_passed_via_env_not_argv(self):
        # FakeRunner가 (argv, env, redact) 기록. token이 어떤 argv에도 없음,
        # env["K8S_AGENT_GIT_ASKPASS_PASS"] == token, redact에 token 포함
    def test_askpass_script_contains_no_token(self):
        # askpass.sh 파일 내용에 token 부재
    def test_failure_message_redacted(self):
        # FakeRunner가 stderr에 token 포함 실패 반환 → RepoAcquisitionError 문자열에 token 부재
    def test_url_without_token_gets_no_askpass(self):
        # token=None → env에 K8S_AGENT_GIT_ASKPASS_PASS 미설정
```

(FakeRunner는 `helpers.py`에: 호출 기록 리스트 + 시나리오별 `ProcResult` 반환. 실제 git을 쓰는 테스트는 `file://` URL이라 네트워크 불필요.)

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_repo.py" -v` / Expected: `ModuleNotFoundError`
- [ ] **Step 3: 구현** — 위 제어 흐름대로 `repo.py` 작성. git 호출은 전부 `runner(...)` 경유(주입 가능). askpass 스크립트 생성은 `_ensure_askpass(cache_root) -> Path`로 분리.
- [ ] **Step 4: 통과 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_repo.py" -v` / Expected: `OK (12 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: repository acquisition with token-safe git auth and cache"`

**완료 조건:** file:// clone 왕복이 실제 git으로 검증되고, 토큰 4중 안전(디스크·argv·예외·redact)이 테스트로 고정됨.

---

### Task 5: Analysis Adapter + Output-Dir Scan Exclusion

**목표:** 기존 결정론 파이프라인(`run_phase1_analysis` + `reconcile`)을 에이전트 산출물 디렉터리(`<repo>/k8s-agent-output/analysis/`)에 연결하고, 그 디렉터리를 스캐너 제외 목록에 추가한다.

**이유:** MVP 3단계(기존 파이프라인 실행). 산출물이 저장소 안에 쓰이므로 재분석 시 생성 매니페스트가 evidence로 역유입되는 경로를 반드시 차단해야 한다(§1.4). **이 태스크가 preanalyzer를 수정하는 유일한 태스크다.**

**Files:**
- Create: `src/k8sagent/analysis.py`
- Modify: `src/preanalyzer/path_safety.py:17-40` (`REPO_EXCLUDED_GLOBS`에 `"k8s-agent-output/**"`, `"**/k8s-agent-output/**"` 추가, `EXCLUDED_DIR_NAMES`에 `"k8s-agent-output"` 추가)
- Modify: `src/preanalyzer/rules_version.py` (`RULES_VERSION = "2026.07"` → `"2026.07.1"` — 스캔 규칙 변경은 P10 재현성 계약상 버전 범프 필수)
- Test: `tests/unit/agent/test_analysis.py`

**Interfaces:**
- Produces:
  - `OUTPUT_DIR_NAME = "k8s-agent-output"`
  - `AnalysisBundle` (frozen dataclass): `snapshot: RepositorySnapshot`, `inventory: ArtifactInventory`, `evidence: EvidenceModel`, `rules: RuleInferenceSet`, `reconciliation: ReconciliationResult`
  - `run_agent_analysis(repo_path: Path, *, url: str | None, ref: str | None, clock: Callable[[], datetime]) -> AnalysisBundle` — 내부에서 `output_dir = repo_path / OUTPUT_DIR_NAME / "analysis"` 고정
- Consumes: `preanalyzer.pipeline.run_phase1_analysis`(52-112행 — 00~04 YAML을 그 안에서 기록), `preanalyzer.reconciliation.engine.reconcile`

**데이터/제어 흐름:**
1. `run_phase1_analysis(repo=repo_path, output_dir=<analysis dir>, url=url, ref=ref, clock=clock, mode="workspace", semantic_mode="disabled")` → `(snapshot, inventory, evidence, rules)` (00~04 파일은 함수가 기록)
2. `reconciliation = reconcile(rules, evidence, accepted_commands=[])` (D6: semantic disabled 고정이므로 항상 빈 리스트가 충실한 입력)
3. 기존 번호 관례를 따라 어댑터가 추가 기록: `06-component-model.yaml`, `07-runtime-model.yaml`, `08-dependency-model.yaml`, `09-kubernetes-intent.yaml`(baseline), `10-unresolved-questions.yaml` — `yaml.safe_dump(sort_keys=False)` 사용(기존 `_write_yaml`과 동일 방식, 어댑터에 자체 `_write_yaml` 헬퍼)
4. 예외(`ValueError` 등)는 `AnalysisError`로 감싼다.

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/agent/test_analysis.py`

```python
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree

from k8sagent.analysis import OUTPUT_DIR_NAME, run_agent_analysis

FIXTURE = Path("tests/fixtures/repos/node-express-like")
CLOCK = lambda: datetime(2026, 7, 13, tzinfo=timezone.utc)


class AnalysisAdapterTests(unittest.TestCase):
    def _copy_fixture(self, tmp: str) -> Path:
        repo = Path(tmp) / "repo"
        copytree(FIXTURE, repo)
        return repo

    def test_writes_phase1_and_reconciliation_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            bundle = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            out = repo / OUTPUT_DIR_NAME / "analysis"
            for name in ("00-repository-snapshot.yaml", "03-rule-inference.yaml",
                         "06-component-model.yaml", "09-kubernetes-intent.yaml",
                         "10-unresolved-questions.yaml"):
                self.assertTrue((out / name).is_file(), name)
            self.assertTrue(bundle.reconciliation.intent.components)

    def test_output_dir_not_reinventoried(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            # 산출물이 있는 상태로 재분석해도 inventory에 k8s-agent-output 파일이 없어야 한다
            bundle = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            listed = [str(item["path"]) for item in bundle.inventory.kubernetes_manifests]
            self.assertFalse([p for p in listed if OUTPUT_DIR_NAME in p])

    def test_deterministic_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            first = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            second = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            self.assertEqual(first.rules, second.rules)
            self.assertEqual(first.evidence, second.evidence)


if __name__ == "__main__":
    unittest.main()
```

주의: `ArtifactInventory.kubernetes_manifests` 필드명은 `src/preanalyzer/models/inventory.py`에서 구현 시 확인하고, 검사 대상을 inventory 전 카테고리로 확장해도 좋다(제외가 목적).

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_analysis.py" -v` / Expected: 첫 테스트 `ModuleNotFoundError`, path_safety 수정 전이면 `test_output_dir_not_reinventoried` FAIL
- [ ] **Step 3: 구현** — `path_safety.py` 3줄 추가 + `rules_version.py` 범프(`"2026.07.1"`) + `analysis.py` 작성(위 흐름 그대로, ~60행)
- [ ] **Step 4: 통과 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_analysis.py" -v` / Expected: `OK (3 tests)`
- [ ] **Step 5: 전체 회귀** — Run: `$RUN_UNIT discover -s tests -v` / Expected: `OK` (path_safety 변경이 기존 스위트를 깨지 않음 — `test_scanner.py:91`은 `assertIn`이라 안전. 만약 excluded_patterns 스냅샷을 exact-equality로 단언하는 테스트가 발견되면 그 단언만 새 패턴 포함으로 갱신하고 커밋 메시지에 명시)
- [ ] **Step 6: Commit** — `git commit -m "feat: agent analysis adapter; exclude k8s-agent-output from scans"`

**완료 조건:** 픽스처 저장소에서 00~10 산출물 생성, 재분석 오염 없음, 전체 스위트 green.

---

### Task 6: Deployment Candidates + Selection + Dependency Warnings

**목표:** 분석 결과에서 배포 후보 컴포넌트를 추출하고, 사용자 선택을 적용하며, 제외된 컴포넌트에 대한 의존성을 **경고로만** 알린다(선택을 몰래 바꾸지 않는다).

**이유:** MVP 4~5단계. `reconcile()`은 전 컴포넌트를 무조건 포함하므로 선택 계층이 필요하다.

**Files:**
- Create: `src/k8sagent/components.py`
- Test: `tests/unit/agent/test_components.py`

**Interfaces:**
- Produces:
  - `DeployableCandidate(BaseModel)`: `component_id: str`, `root_path: str | None`, `role: str`, `deployable: bool`(role=="application"), `port: int | None`, `command: str | None`, `secret_env: list[str]`, `config_env: list[str]`
  - `extract_candidates(bundle: AnalysisBundle) -> list[DeployableCandidate]` — `reconciliation.component_model` + `intent.components`에서 구성, `component_id` 정렬
  - `SelectionResult(BaseModel)`: `selected: list[str]`, `excluded: list[str]`, `warnings: list[str]`
  - `apply_selection(bundle: AnalysisBundle, selected: list[str]) -> SelectionResult`
- Consumes: `analysis.AnalysisBundle`

**apply_selection 규칙:**
- `selected`에 존재하지 않는 component_id가 있으면 `ChangeSetError`가 아닌 `AnalysisError`(“unknown component”).
- deployable=False(role이 dependency/infrastructure 등)인 항목을 선택하면 오류가 아니라 경고 추가(“component X has role Y; it will still be rendered as a workload only if evidence supports it” — 실제 렌더 여부는 Intent 빌더가 role로 판정).
- 경고 생성: `dependency_model.edges` 중 `source_component ∈ selected`이고 `target`이 **후보 id 집합에 속하면서** excluded인 것 → `"selected 'a' depends on excluded 'b' (<dependency_type>)"`. target이 후보 집합 밖(외부 시스템 이름)이면 경고 대상 아님.

- [ ] **Step 1: 실패 테스트 작성** — 케이스: (a) node-express-like 픽스처에서 후보 ≥1 추출·정렬 (b) 전체 선택 → 경고 없음 (c) 인위 bundle(2 컴포넌트 + 의존 엣지)로 하나 제외 → 정확한 경고 문자열 1건 (d) 미지 id 선택 → `AnalysisError` (e) 외부 타깃 엣지는 경고 미생성. 인위 bundle은 `ReconciliationResult`를 직접 구성(모델은 전부 공개 계약).
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_components.py" -v`
- [ ] **Step 3: 구현** (~70행, 순수 함수 2개)
- [ ] **Step 4: 통과 확인** — Expected: `OK (5 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: deployment candidate extraction and selection warnings"`

**완료 조건:** 경고가 선택을 변경하지 않음이 테스트로 고정(선택 리스트가 입력과 동일하게 반환).

---

### Task 7: Application Topology Model

**목표:** 선택된 컴포넌트와 의존 관계를 담는 직렬화 가능한 `ApplicationTopology`를 만들고 `analysis/topology.yaml`로 기록한다.

**이유:** MVP 6단계. 이후 Intent 빌더·LLM 설명·질문 문안의 유일한 입력 요약본.

**Files:**
- Create: `src/k8sagent/models/__init__.py`, `src/k8sagent/models/topology.py`
- Test: `tests/unit/agent/test_topology.py`

**Interfaces:**
- Produces:
  - `TopologyComponent(BaseModel)`: `component_id: str`, `root_path: str | None`, `role: str`, `port: Tracked[int] | None`, `command: Tracked[str] | None`, `config_env: list[str]`, `secret_env: list[str]`
  - `TopologyEdge(BaseModel)`: `source: str`, `target: str`, `dependency_type: str`, `target_selected: bool`
  - `ApplicationTopology(BaseModel)`: `commit_sha: str | None`, `components: list[TopologyComponent]`(선택된 것만), `excluded: list[str]`, `edges: list[TopologyEdge]`, `warnings: list[str]`
  - `build_topology(bundle: AnalysisBundle, selection: SelectionResult) -> ApplicationTopology`
  - `write_topology(topology, output_dir: Path) -> Path` — `analysis/topology.yaml`
- Consumes: `preanalyzer.models.fields.Tracked`(D8), Task 5·6 산출

**Tracked 직렬화 주의:** `Tracked`는 pydantic dataclass여서 BaseModel 필드로 쓸 수 있다(기존 `preanalyzer.models.intent.Workload`가 동일 패턴 — 검증 근거). `model_dump()` 왕복 테스트 필수.

- [ ] **Step 1: 실패 테스트 작성** — (a) build: 선택 2/제외 1 시나리오에서 components·excluded·edges.target_selected 정확성 (b) YAML 왕복: `write_topology` 후 `yaml.safe_load` → `ApplicationTopology.model_validate` 성공 (c) 결정론: 같은 입력 2회 → dump 동일 (d) secret **값** 부재: dump 직렬화 문자열에 fixture의 env 값 문자열이 없음(이름만 존재)
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_topology.py" -v`
- [ ] **Step 3: 구현** — `reconcile` 산출물 필드 매핑(runtime_model에서 port/command, intent에서 config_env/secret_env). 정렬: components는 component_id, edges는 (source, target).
- [ ] **Step 4: 통과 확인** — Expected: `OK (4 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: application topology model"`

**완료 조건:** 왕복 직렬화 + 결정론 + secret 값 부재가 테스트로 고정.

---

### Task 8: Agent Kubernetes Intent + `set_intent_path`

**목표:** MVP 리소스 7종을 표현하는 리치 Intent 모델과, 경로 문법으로 필드를 갱신하는 단일 진입점 `set_intent_path`(위저드 답변·ChangeSet 공용)를 만든다.

**이유:** MVP 7단계. 기존 Intent는 필드가 부족하고 Jinja 렌더러에 묶여 있다(D7). 모든 값 변경이 한 함수를 지나야 출처 추적과 검증이 일관된다.

**Files:**
- Create: `src/k8sagent/models/intent.py`
- Test: `tests/unit/agent/test_intent.py`

**Interfaces:**
- Produces (모두 `BaseModel`):

```python
class ImageSpec(BaseModel):
    registry: Tracked[str] | None = None
    name: Tracked[str] | None = None
    tag: Tracked[str] | None = None          # 미설정 시 정책 기본 "latest"는 질문 default로만 제안

class WorkloadSpec(BaseModel):
    image: ImageSpec = Field(default_factory=ImageSpec)
    replicas: Tracked[int] | None = None     # 미설정 → Deployment에서 필드 생략(K8s 기본 1)
    container_port: Tracked[int] | None = None
    command: Tracked[str] | None = None

class ServiceSpec(BaseModel):
    port: Tracked[int] | None = None         # type은 ClusterIP 고정(템플릿 상수)

class IngressSpec(BaseModel):
    host: Tracked[str] | None = None
    path: Tracked[str] | None = None         # 미설정 → "/" (렌더러 상수)

class SecretRefSpec(BaseModel):
    env_name: str                            # 예: DB_PASSWORD (evidence에서 옴)
    secret_name: Tracked[str] | None = None  # 기존 Secret 이름 — 반드시 사용자 답변
    secret_key: Tracked[str] | None = None

class PVCSpec(BaseModel):
    size: Tracked[str] | None = None         # 예: "1Gi"
    storage_class: Tracked[str] | None = None
    mount_path: Tracked[str] | None = None

class ComponentIntentSpec(BaseModel):
    component_id: str
    role: str
    workload: WorkloadSpec = Field(default_factory=WorkloadSpec)
    service: ServiceSpec | None = None
    configmap: dict[str, Tracked[str]] = Field(default_factory=dict)  # KEY -> 값(evidence/user만)
    secret_refs: list[SecretRefSpec] = Field(default_factory=list)
    ingress: IngressSpec | None = None
    pvc: PVCSpec | None = None

class AgentKubernetesIntent(BaseModel):
    namespace: Tracked[str] | None = None
    create_namespace: bool = True
    components: list[ComponentIntentSpec] = Field(default_factory=list)
```

  - `build_intent(topology: ApplicationTopology, baseline: KubernetesIntent) -> AgentKubernetesIntent` — baseline(`preanalyzer.models.intent`)에서 port/command/secret_env를 승계(Tracked 그대로 복사 → 출처 보존), `image.name`은 baseline workload의 값 승계, role != "application" 컴포넌트는 workload 없이 목록에만 유지
  - `set_intent_path(intent, path: str, value: object | None, *, source: str) -> AgentKubernetesIntent` — 순수 함수(`model_copy(deep=True)` 후 갱신). `value=None`은 unset. 반환 전 값 검증
  - `INTENT_PATHS: list[re.Pattern]` — 허용 경로 문법(아래) 원장. Task 10의 ChangeSet도 이것을 소비
  - `intent_path_exists(intent, path) -> bool`, `get_intent_path(intent, path) -> object | None`

**경로 문법 (전체 원장 — 이후 태스크가 그대로 사용):**

```text
namespace
create_namespace
components.<cid>.workload.image.registry
components.<cid>.workload.image.name
components.<cid>.workload.image.tag
components.<cid>.workload.replicas
components.<cid>.workload.container_port
components.<cid>.workload.command
components.<cid>.service.port
components.<cid>.ingress.host
components.<cid>.ingress.path
components.<cid>.configmap.<KEY>
components.<cid>.secret_refs.<ENV_NAME>.secret_name
components.<cid>.secret_refs.<ENV_NAME>.secret_key
components.<cid>.pvc.size
components.<cid>.pvc.storage_class
components.<cid>.pvc.mount_path
```

`<cid>`: `[a-z0-9]([-a-z0-9]*[a-z0-9])?`, `<KEY>`/`<ENV_NAME>`: `[A-Za-z_][A-Za-z0-9_]*`.

**터미널 값 검증 규칙(`set_intent_path` 내부, 위반 시 `ChangeSetError`):** port/container_port/service.port: int 1..65535 · replicas: int 1..50 · namespace/image.name/secret_name: RFC1123 label(`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$`) · ingress.host: 소문자 DNS 이름(점 허용) · image.registry: 호스트[:포트][/경로] 패턴 · image.tag: `^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$` · pvc.size: `^[1-9][0-9]*(Gi|Mi)$` · mount_path: `/`로 시작하는 POSIX 절대경로 · secret_key: `^[-._a-zA-Z0-9]+$` · command/configmap 값: 개행 없는 비어있지 않은 str.

**적용 의미론:** `service.port` set 시 `service`가 None이면 `ServiceSpec` 생성. `ingress.*`/`pvc.*` 동일(부분 설정 허용 — 렌더 가능 여부는 Task 9 gap 규칙이 판정). `secret_refs.<ENV>`는 기존 env_name 항목만 갱신 가능(새 env 발명 불가 — evidence 우선 원칙). unset으로 마지막 필드가 모두 None이 된 `ingress`/`pvc`는 None으로 되돌린다.

- [ ] **Step 1: 실패 테스트 작성** — 최소 케이스: (a) build_intent가 baseline port/command Tracked를 source 보존 승계 (b) set namespace → `Tracked(value, source="user_decision", confidence=HIGH)` (c) 잘못된 port 값 → `ChangeSetError` (d) 미허용 경로 → `ChangeSetError` (e) 존재하지 않는 cid → `ChangeSetError` (f) service 자동 생성 (g) unset으로 ingress 제거 (h) secret_refs에 새 ENV 추가 시도 → `ChangeSetError` (i) 순수성: 원본 intent 불변 (j) dump 왕복.
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_intent.py" -v`
- [ ] **Step 3: 구현** — 경로 파서는 정규식 매칭 → (component 탐색 → 스펙 보장 → 필드 set) 순. Tracked 생성: `Tracked(value=value, source=source, confidence=Confidence.HIGH if source == "user_decision" else Confidence.MEDIUM, evidence_refs=[])`.
- [ ] **Step 4: 통과 확인** — Expected: `OK (10+ tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: agent kubernetes intent model and path-based updates"`

**완료 조건:** 경로 원장·값 검증·순수성·출처 보존이 전부 테스트로 고정.

---

### Task 9: Unresolved-Field Discovery + Deterministic Questions + Answer Application

**목표:** Intent에서 미해결 필드를 결정론적으로 찾아 구조화 질문을 만들고, 답변을 파싱·검증해 `set_intent_path`로 적용한다. LLM 없이 완주 가능한 폴백 경로가 이 태스크에서 완성된다.

**이유:** MVP 8~10단계. "no guessing when evidence is missing" — 빈 값은 질문이 되지, 기본값이 되지 않는다.

**Files:**
- Create: `src/k8sagent/gaps.py`, `src/k8sagent/questions.py`
- Test: `tests/unit/agent/test_gaps_questions.py`

**Interfaces:**
- Produces:
  - `UnresolvedField(BaseModel)`: `path: str`, `reason: str`, `severity: Literal["blocking", "optional"]`
  - `find_unresolved(intent: AgentKubernetesIntent) -> list[UnresolvedField]` — path 정렬, 결정론
  - `Question(BaseModel)`: `id: str`(예: `Q-components.web.workload.image.registry`), `path: str`, `text: str`, `answer_type: Literal["string","int","bool","port","k8s_name","host","registry","image_tag","quantity","mount_path","secret_key","choice"]`, `candidates: list[str] = []`, `default: str | None = None`, `severity: str`
  - `build_questions(unresolved: list[UnresolvedField], topology: ApplicationTopology) -> list[Question]`
  - `parse_answer(question: Question, raw: str) -> object` — 타입별 파싱·검증, 실패 시 `ChangeSetError`(재질문용)
  - `apply_answer(intent, question, value) -> AgentKubernetesIntent` — `set_intent_path(..., source="user_decision")` 위임
- Consumes: Task 8 전체

**Gap 규칙 (전체 원장):**

| 조건 | path | severity | 근거 |
|---|---|---|---|
| `namespace` 미설정 | `namespace` | blocking | 리소스 배치 불가 |
| application 컴포넌트의 `image.registry` 미설정 | `components.<cid>.workload.image.registry` | blocking | 이미지 좌표 불완전 |
| `image.name` 미설정 | 〃 `.image.name` | blocking | 〃 |
| `image.tag` 미설정 | 〃 `.image.tag` | optional (질문 default="latest") | 정책 기본을 사용자가 **확인**하는 형태 — 무단 추측 아님 |
| `service` 존재 & `service.port` 미설정 | 〃 `.service.port` | blocking | Service 렌더 불가 |
| `container_port` 미설정 & service 존재 | 〃 `.workload.container_port` | blocking | targetPort 필요 |
| `secret_refs[*].secret_name` 또는 `.secret_key` 미설정 | 해당 경로 | blocking | 제품 결정: Secret 미해결 시 반드시 질문 |
| `ingress` 존재 & `host` 미설정 | 〃 `.ingress.host` | blocking | host 없는 Ingress 렌더 금지 |
| `pvc` 존재 & (`size`/`mount_path` 미설정) | 해당 경로 | blocking | 불완전 PVC 렌더 금지 |
| `configmap` 키의 값 미설정(Tracked.value None) | 〃 `.configmap.<KEY>` | optional | 미답 시 해당 키 생략 렌더 |

ingress/pvc **자체를 만들지 여부**는 gap이 아니라 위저드/CLI의 opt-in 질문이다(Task 15·16: `components.<cid>.ingress.host`를 set하면 생김). blocking gap이 0이면 `intent_resolved` 전이 가능.

**결정론 질문 문안 테이블(발췌 — 전 answer_type에 하나씩 구현):** `registry` → `"컴포넌트 '<cid>'의 컨테이너 이미지를 어느 레지스트리에서 가져옵니까? (예: registry.example.com:5000)"` · `port` → `"컴포넌트 '<cid>'가 수신하는 컨테이너 포트는 몇 번입니까?"`(topology의 port 후보가 있으면 candidates로 제시) · `k8s_name`(namespace) → `"리소스를 배치할 네임스페이스 이름은 무엇입니까?"`.

- [ ] **Step 1: 실패 테스트 작성** — (a) 빈 intent(1 컴포넌트) → blocking gap 정확 집합(namespace, registry, name) (b) service 있는 intent → port gap 추가 (c) secret_env 2개 → secret_name/key gap 4개 (d) 모든 blocking 해소 후 `find_unresolved` blocking 0 (e) 질문 결정론: 같은 입력 2회 → 동일 리스트 (f) `parse_answer` 유효/무효 케이스(port "8080"→8080, "70000"→오류, quantity "1Gi" ok "1TB" 오류, bool "y"/"n") (g) `apply_answer` 후 Tracked source=="user_decision" (h) tag 질문의 default=="latest".
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_gaps_questions.py" -v`
- [ ] **Step 3: 구현** — gap 규칙은 위 표를 if-체인으로 직역(~80행). 질문 문안은 dict 테이블 `_TEXT_BUILDERS: dict[str, Callable[[str, str], str]]`.
- [ ] **Step 4: 통과 확인** — Expected: `OK (12+ tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: unresolved-field discovery and deterministic questions"`

**완료 조건:** LLM 완전 부재 상태에서 질문 생성→답변→해소 루프가 테스트로 완주.

---

### Task 10: ChangeSet Model, Validation, Diff, Apply

**목표:** 모든 상태 변경(NL 요청·수정 제안·비대화형 답변 파일)을 지나가게 할 typed ChangeSet과 `검증 → diff → (승인은 호출자) → 적용` 파이프라인.

**이유:** 제품 결정의 핵심 안전 장치. LLM이 만든 것이든 사람이 만든 것이든 같은 검증을 통과해야 한다.

**Files:**
- Create: `src/k8sagent/changeset.py`
- Test: `tests/unit/agent/test_changeset.py`

**Interfaces:**
- Produces:
  - `Change(BaseModel)`: `op: Literal["set", "unset"]`, `path: str`, `value: str | int | bool | None = None` (`op="set"`이면 value 필수 — model_validator로 강제)
  - `ChangeSet(BaseModel)`: `changes: list[Change]`(min 1, max 20 — `Field(min_length=1, max_length=20)`), `origin: Literal["wizard", "nl_request", "correction", "answers_file"]`, `summary: str = ""`
  - `validate_changeset(cs: ChangeSet, intent: AgentKubernetesIntent) -> None` — 각 change에 대해 경로 문법·존재하는 cid·값 검증을 **dry-run 적용**으로 확인(`set_intent_path`를 복사본에 적용). 실패 시 `ChangeSetError(어느 change가 왜)`
  - `FieldDiff(BaseModel)`: `path: str`, `before: object | None`, `after: object | None`
  - `diff_changeset(cs, intent) -> list[FieldDiff]` — `get_intent_path`로 before 추출
  - `apply_changeset(cs, intent, *, source: str) -> AgentKubernetesIntent` — 검증 후 순차 적용, 순수 함수
  - `render_diff_text(diffs: list[FieldDiff]) -> str` — `path: before -> after` 행 포맷(대화형·비대화형 공용 표시)
- Consumes: Task 8의 `set_intent_path`/`get_intent_path`/`INTENT_PATHS`

**에러·보안:** origin이 무엇이든 검증은 동일(LLM 우회 경로 없음). Secret **값**을 넣을 수 있는 경로 자체가 원장에 없다(secret_name/secret_key는 이름·키 참조일 뿐). value에 개행·NUL 포함 시 거부.

- [ ] **Step 1: 실패 테스트 작성** — (a) set namespace 검증·diff·적용 왕복 (b) 미허용 경로 → `ChangeSetError`에 해당 path 문자열 포함 (c) 잘못된 값 (d) 빈 changes → pydantic ValidationError (e) 21개 changes → ValidationError (f) unset diff(before 있음, after None) (g) apply 순수성(원본 불변) (h) 부분 실패 시 전체 거부(2번째 change가 무효면 1번째도 미적용).
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_changeset.py" -v`
- [ ] **Step 3: 구현** — validate는 복사본에 전 change 적용 시도(전부 성공해야 통과) → apply는 검증 후 재적용. ~90행.
- [ ] **Step 4: 통과 확인** — Expected: `OK (8 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: typed changeset validation, diff, and apply"`

**완료 조건:** all-or-nothing 적용과 경로/값 검증이 테스트로 고정.

---

### Task 11: OpenAI-Compatible LLM Client (Structured Ops + Fallbacks)

**목표:** 기존 `SemanticLLMSettings` 설정으로 초기화되는 `AgentLLMClient`에 5개 typed 연산을 구현한다. 모든 응답은 pydantic 검증 통과 필수, 실패 시 1회 재시도 후 `None`(호출자가 결정론 폴백 사용).

**이유:** MVP의 LLM 허용 범위(설명·질문 문안·NL→ChangeSet·오류 설명·수정 제안)를 한 모듈로 격리. `None` 반환 규약이 "LLM 장애가 파이프라인을 중단시키지 않는다"(architecture.md 2.8)를 계승한다.

**Files:**
- Create: `src/k8sagent/llm.py`
- Test: `tests/unit/agent/test_llm.py`, `helpers.py`에 `FakeLLM` 추가

**Interfaces:**
- Produces:
  - `AgentLLMClient`:
    - `@classmethod from_env(cls, env=None) -> AgentLLMClient | None` — `load_semantic_llm_settings` 사용(D4), `SemanticLLMConfigError` 시 `None`(예외 아님 — LLM은 항상 선택적)
    - `explain_analysis(self, topology: ApplicationTopology) -> str | None`
    - `phrase_question(self, question: Question) -> str | None` — 반환 문자열은 **문안만** 교체. candidates/answer_type/default는 호출자가 유지
    - `nl_to_changeset(self, request: str, intent: AgentKubernetesIntent, allowed_paths: list[str]) -> ChangeSet | None` — 응답 JSON을 `ChangeSet.model_validate` 후 `validate_changeset`까지 통과해야 반환. `origin`은 강제로 `"nl_request"` 덮어쓰기
    - `explain_validation_failure(self, report: AgentValidationReport) -> str | None` (report 모델은 Task 13 — 구현 순서상 Task 13 뒤에 이 메서드의 통합 테스트를 추가해도 되고, 여기서는 `dict` 수준 payload로 작성)
    - `propose_correction(self, report_payload: dict, intent: AgentKubernetesIntent, allowed_paths: list[str]) -> ChangeSet | None` — `origin="correction"` 강제
  - `LLMProtocol(Protocol)` — 위 5 메서드 시그니처. `FakeLLM`(tests/helpers)과 `AgentLLMClient`가 공히 만족. 위저드·CLI는 Protocol 타입만 소비
- Consumes: `preanalyzer.semantic.llm_config.load_semantic_llm_settings`, `openai.OpenAI`(기존 의존성), Task 8·10 모델

**공통 호출 규약(내부 `_call_json(system: str, payload: dict, adapter: TypeAdapter) -> object | None`):**
1. `client.chat.completions.create(model=…, temperature=0, response_format={"type": "json_object"}, messages=[system, user(json payload)])`
2. code-fence strip(기존 `openai_provider._strip_code_fence`와 동일 로직 — 사설 함수이므로 6행 복사, 출처 주석) → `json.loads` → pydantic 검증
3. 실패 시 실패 사유를 첨부해 1회 재시도 → 재실패·예외·타임아웃 → `None`. 그 이상 재생성 금지(architecture.md 4.5 계승)

**payload 안전:** 각 연산의 payload 빌더는 인자로 받은 모델의 `model_dump()`만 직렬화한다. `AgentKubernetesIntent`/`ApplicationTopology`/`Question`에는 토큰·Secret 값 필드가 타입 수준에서 없다(Task 3·7·8에서 보장). git 토큰, `SemanticLLMSettings.api_key`, 세션 객체는 payload 빌더의 시그니처에 없다 — 전달 경로 자체가 없음.

**nl_to_changeset 시스템 프롬프트 요지(전문은 구현 시 상수로):** "You convert a user's natural-language request about Kubernetes deployment intent into a JSON ChangeSet. Output exactly one JSON object: {\"changes\":[{\"op\":\"set\",\"path\":\"...\",\"value\":...}],\"summary\":\"...\"}. Use only paths from allowed_paths. Never output YAML, secret values, or paths not in the list. If the request cannot be expressed with allowed paths, output {\"changes\":[],\"summary\":\"cannot_express\"}" — 빈 changes는 pydantic min_length=1에 걸려 `None` 폴백으로 수렴.

- [ ] **Step 1: 실패 테스트 작성** — openai 클라이언트를 스텁(생성자 주입 `client=`)으로 대체: (a) 정상 JSON → ChangeSet 반환·origin 강제 덮어쓰기 (b) 미허용 경로 포함 응답 → 1회 재시도 후 None (c) 깨진 JSON → 재시도 → None (d) code-fence 감싼 JSON → 성공 (e) 예외(connection) → None (f) `from_env` 설정 부재 → None (g) phrase_question이 str 아닌 응답 → None (h) payload에 api_key/token 문자열 부재 단언(스텁이 받은 messages 전문 검사).
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_llm.py" -v`
- [ ] **Step 3: 구현** — 각 연산은 `_call_json` + 연산별 system 상수 + payload 빌더 + 후검증. `FakeLLM`은 시나리오 dict(연산명→반환값 목록)로 구동.
- [ ] **Step 4: 통과 확인** — Expected: `OK (8+ tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: agent llm client with schema-validated operations"`

**완료 조건:** 5연산 전부 "검증 실패 → None" 경로가 테스트로 고정. payload 비밀 부재 단언 존재.

---

### Task 12: Per-Resource Python Renderers + Stable YAML

**목표:** 검증된 Intent만 입력받는 리소스별 순수 함수 렌더러(Namespace/Deployment/Service/ConfigMap/Ingress/PVC + Secret 참조는 Deployment env로)와 결정론 YAML 직렬화.

**이유:** MVP 13단계 + 제품 결정(Jinja 금지, LLM·저장소 접근 금지, 동일 Intent = 동일 YAML).

**Files:**
- Create: `src/k8sagent/render/__init__.py`, `render/resources.py`, `render/policy.py`, `render/serialize.py`
- Test: `tests/unit/agent/test_render.py`

**Interfaces:**
- Produces:
  - `policy.labels(component_id: str) -> dict[str, str]` — `app.kubernetes.io/name`, `app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by: k8s-agent` (기존 `preanalyzer.renderer.policy.labels`와 같은 키, managed-by 값만 다름 — 별도 제품 표면이므로 독립 구현)
  - `policy.annotations(commit_sha: str | None) -> dict[str, str]` — `k8s-agent/commit-sha`, `k8s-agent/version`
  - `serialize.to_yaml(doc: dict) -> str` — `yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=False)` + 후행 개행 1개
  - `resources.render_namespace(intent) -> dict | None` — `namespace` set & `create_namespace`일 때만
  - `resources.render_deployment(component: ComponentIntentSpec, namespace: str | None, commit_sha: str | None) -> dict`
  - `resources.render_service(component, namespace, commit_sha) -> dict | None`
  - `resources.render_configmap(component, namespace, commit_sha) -> dict | None` — 값 있는 키만, 키 정렬
  - `resources.render_ingress(component, namespace, commit_sha) -> dict | None` — host 있을 때만, `pathType: Prefix`, path 기본 `/`
  - `resources.render_pvc(component, namespace, commit_sha) -> dict | None` — size+mount_path 모두 있을 때만, `accessModes: [ReadWriteOnce]`(상수)
  - `RenderedManifests` (frozen dataclass): `files: dict[str, str]`(상대경로→YAML), `deferred: list[str]`(사유 문자열)
  - `render_all(intent: AgentKubernetesIntent, commit_sha: str | None) -> RenderedManifests`
  - `write_manifests(rendered, output_dir: Path) -> list[Path]` — `manifests/` 아래 기록(디렉터리 선삭제 후 재생성 — 이전 산출물 잔존 방지)
- Consumes: Task 8 모델만. **이 패키지는 `preanalyzer.analyzer`·`k8sagent.llm`·`k8sagent.repo`를 import하지 않는다** (테스트로 강제)

**Deployment 렌더 사양 (dict 구성 순서가 곧 출력 순서):**

```python
def render_deployment(component, namespace, commit_sha):
    cid = component.component_id
    w = component.workload
    container: dict = {"name": cid, "image": _image_ref(w.image)}
    if w.command is not None and w.command.value:
        container["command"] = shlex.split(w.command.value)
    if w.container_port is not None and w.container_port.value is not None:
        container["ports"] = [{"containerPort": w.container_port.value}]
    env = [
        {"name": ref.env_name,
         "valueFrom": {"secretKeyRef": {"name": ref.secret_name.value, "key": ref.secret_key.value}}}
        for ref in sorted(component.secret_refs, key=lambda r: r.env_name)
        if ref.secret_name and ref.secret_name.value and ref.secret_key and ref.secret_key.value
    ]
    if env:
        container["env"] = env
    if _configmap_data(component):
        container["envFrom"] = [{"configMapRef": {"name": f"{cid}-config"}}]
    if component.pvc is not None and component.pvc.mount_path and component.pvc.mount_path.value:
        container["volumeMounts"] = [{"name": f"{cid}-data", "mountPath": component.pvc.mount_path.value}]

    pod_spec: dict = {"containers": [container]}
    if "volumeMounts" in container:
        pod_spec["volumes"] = [{"name": f"{cid}-data",
                                "persistentVolumeClaim": {"claimName": f"{cid}-data"}}]
    spec: dict = {
        "selector": {"matchLabels": {"app.kubernetes.io/name": cid}},
        "template": {"metadata": {"labels": labels(cid)}, "spec": pod_spec},
    }
    if component.workload.replicas is not None and component.workload.replicas.value is not None:
        spec = {"replicas": component.workload.replicas.value, **spec}
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": _metadata(cid, namespace, cid, commit_sha), "spec": spec}
```

`_image_ref`: `f"{registry}/{name}:{tag or 'latest'}"` — 단, **registry/name이 None이면 이 함수에 도달하지 않는다**: `render_all`이 blocking gap이 남은 컴포넌트를 `deferred`에 넣고 파일을 만들지 않는다(기존 렌더러의 defer 정책 계승, renderer/engine.py 54-68행과 동형). tag 미설정 시 "latest"는 Task 9에서 사용자가 default 확인을 거친 뒤에만 도달하는 게 정상 경로지만, 방어적으로 렌더러도 latest를 쓴다(값 발명이 아니라 이미지 참조 문법의 생략 기본값).

**파일 레이아웃:** `namespace.yaml`(있을 때), `<cid>/deployment.yaml`, `<cid>/service.yaml`, `<cid>/configmap.yaml`, `<cid>/ingress.yaml`, `<cid>/pvc.yaml`. `files` dict는 정렬 삽입.

- [ ] **Step 1: 실패 테스트 작성** — (a) 완전 해소 intent → 6종 파일 + 기대 YAML 골든 문자열(assertEqual로 byte 비교, 최소 deployment 1개는 전문 골든) (b) 결정론: `render_all` 2회 → files dict 동일 (c) secret ref → `valueFrom.secretKeyRef` 존재, `kind: Secret` 문서 부재, `__REPLACE_ME__`·값 문자열 부재 (d) registry 미해소 컴포넌트 → deferred + 파일 없음 (e) replicas 미설정 → `replicas` 키 부재 (f) configmap 값 없는 키 생략 (g) ingress host 없으면 파일 없음 (h) import 경계: `import k8sagent.render.resources` 후 `sys.modules`에 `k8sagent.llm`·`preanalyzer.analyzer.scanner` 부재 단언.
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_render.py" -v`
- [ ] **Step 3: 구현** — 위 사양 + Service/ConfigMap/Ingress/PVC/Namespace(각 ~20행).
- [ ] **Step 4: 통과 확인** — Expected: `OK (10+ tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: deterministic python manifest renderers"`

**완료 조건:** 골든 byte 비교 + import 경계 테스트 통과. Secret 값·placeholder가 출력에 없음.

---

### Task 13: Validator Adapters + PASS/FAIL/PARTIAL Aggregation

**목표:** `YAML 파싱 → 내부 불변식 → kubeconform → kubectl dry-run(client)` 체인을 어댑터로 실행하고 단일 집계 상태를 산출한다. K8s 버전은 설정 기본값 + CLI override.

**이유:** MVP 14단계 + 제품 결정(집계 3상태, 도구 자동 설치 금지, 미실행 단계 pass 기록 금지).

**Files:**
- Create: `src/k8sagent/models/report.py`, `src/k8sagent/validate.py`
- Test: `tests/unit/agent/test_validate.py`

**Interfaces:**
- Produces:
  - `CheckResult(BaseModel)`: `name: Literal["yaml_syntax","intent_invariants","kubeconform","kubectl_dry_run"]`, `status: Literal["pass","fail","skipped"]`, `detail: str | None = None`, `skipped_reason: Literal["tool_not_found","prior_check_failed"] | None = None`
  - `AgentValidationReport(BaseModel)`: `aggregate: Literal["PASS","FAIL","PARTIAL"]`, `k8s_version: str`, `checks: list[CheckResult]`
  - `aggregate_checks(checks: list[CheckResult]) -> str`:

```python
def aggregate_checks(checks):
    if any(c.status == "fail" for c in checks):
        return "FAIL"
    if any(c.skipped_reason == "tool_not_found" for c in checks):
        return "PARTIAL"
    return "PASS"
```

  - `run_validation(manifest_dir: Path, intent: AgentKubernetesIntent, *, k8s_version: str, kubeconform_path: Path | None, runner=run_command, project_root: Path | None = None) -> AgentValidationReport`
  - `write_report(report, output_dir: Path) -> Path` — `validation/report.yaml`
- Consumes: `preanalyzer.validator.kubeconform_tool.resolve_kubeconform`(공개 함수 — 관리형 `.tools/` 경로 재사용), `procutil.run_command`, Task 8 모델

**체크 어댑터 사양:**
1. `yaml_syntax`: `manifest_dir.rglob("*.yaml")` 각 파일 `yaml.safe_load`. 실패 → fail(파일명+오류), 이후 체크 전부 `skipped(prior_check_failed)`.
2. `intent_invariants`(결정론, 도구 불필요): 렌더 문서와 intent 대조 — (i) Service의 `targetPort`(=port)와 Deployment `containerPort` 일치 (ii) Service selector ⊆ pod template labels (iii) Ingress backend service가 렌더된 Service와 이름·포트 일치 (iv) 모든 문서의 `metadata.namespace` 동일(namespace 리소스 제외) (v) `secretKeyRef.name/key` 비어있지 않음. 위반 → fail(위반 목록).
3. `kubeconform`: 해석 순서 = 명시 `kubeconform_path`(config/CLI) → `resolve_kubeconform(project_root or Path.cwd(), None)` → `shutil.which("kubeconform")`. 전부 실패 → `skipped(tool_not_found)`. 실행: `[-strict, -summary, -kubernetes-version, <normalized>, <dir>]` — 버전 정규화는 `validator/pipeline.py:12-19`의 `_normalize_kubernetes_version`과 동일 규칙("1.29"→"1.29.0"). 사설 함수이므로 8행 복제(출처 주석).
4. `kubectl_dry_run`: `shutil.which("kubectl")` 없으면 `skipped(tool_not_found)`. 있으면 `kubectl apply --dry-run=client -f <dir> -R`. **어느 단계도 도구를 설치하지 않는다.**

실행 순서는 1→2→3→4이며, 1·2가 fail이면 3·4는 `skipped(prior_check_failed)`(집계는 이미 FAIL). 3이 fail이어도 4는 실행한다(둘은 독립 판정 — 더 많은 증거가 수정 제안에 유리).

- [ ] **Step 1: 실패 테스트 작성** — FakeRunner + tmp manifest로: (a) 전부 pass → PASS (b) kubeconform 미존재(kubeconform_path=None, which 패치) → PARTIAL + `skipped_reason="tool_not_found"` (c) kubeconform rc=1 → FAIL + kubectl은 실행됨 (d) YAML 문법 오류 파일 → FAIL + 이후 3체크 `prior_check_failed` (e) invariant 위반(targetPort 불일치 fixture) → FAIL + 위반 문자열 (f) 버전 정규화("1.29"→argv에 "1.29.0") (g) report.yaml 왕복 로드 (h) `aggregate_checks` 단위 3케이스.
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_validate.py" -v`
- [ ] **Step 3: 구현** — 어댑터 4개 + 집계 + 기록(~150행).
- [ ] **Step 4: 통과 확인** — Expected: `OK (10 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: validation chain with PASS/FAIL/PARTIAL aggregation"`

**완료 조건:** 3상태 집계의 경계 케이스가 전부 테스트로 고정. 실행 안 된 체크가 pass로 기록되는 경로 없음.

---

### Task 14: Validation-Failure Corrections (Deterministic Table + LLM Proposal + Single Cycle)

**목표:** 검증 실패를 설명하고, 결정론 매핑 테이블(우선) 또는 LLM으로 수정 ChangeSet을 제안하며, 승인 시 정확히 1회 재생성+재검증한다.

**이유:** MVP 15~18단계. 자율 수리 루프 금지 — 사이클 수는 승인 횟수와 정확히 같다.

**Files:**
- Create: `src/k8sagent/corrections.py`
- Test: `tests/unit/agent/test_corrections.py`

**Interfaces:**
- Produces:
  - `explain_failure(report: AgentValidationReport, llm: LLMProtocol | None) -> str` — LLM 있으면 `explain_validation_failure` 시도, None이면 결정론 폴백: fail 체크의 `detail`을 그대로 나열한 요약(“kubeconform: <detail 첫 줄>”)
  - `propose_correction(report, intent, llm) -> tuple[ChangeSet | None, str]` — (제안, 출처 라벨 "rule_table"|"llm"|"none"). 결정론 테이블 먼저, 매칭 없고 llm 있으면 `llm.propose_correction`, 반환된 ChangeSet은 `validate_changeset` 재통과 필수
  - `CORRECTION_RULES: list[tuple[re.Pattern, Callable[[re.Match, AgentKubernetesIntent], ChangeSet | None]]]` — MVP 테이블 3건:
    1. `r"port .*?(\d+).*(invalid|out of range)"` (kubeconform/invariant detail) → 해당 컴포넌트 port unset ChangeSet(질문 재개 유도)
    2. `r"(metadata\.name|namespace).*(RFC 1123|a lowercase RFC)"` → 위반 값 소문자·`-` 치환 정규화 값으로 set(원 값에서 결정론 변환 — 발명 아님)
    3. `r"quantity|storage.*invalid"` → 해당 `pvc.size` unset(질문 재개)
  - `run_correction_cycle(session, intent, manifest_dir, *, report, llm, approve: Callable[[str], bool], k8s_version, kubeconform_path, output_dir, commit_sha) -> tuple[AgentKubernetesIntent, AgentValidationReport, bool]` — 흐름: explain → propose → 제안 없으면 (intent, report, False) → diff 텍스트를 `approve()`에 전달 → 거부 시 미적용 (…, False) → 승인 시 `apply_changeset(source="correction")` → `render_all`+`write_manifests` → `run_validation` 1회 → 새 report 반환 (…, True). **이 함수는 자신을 재호출하지 않는다.**
- Consumes: Task 10·11·12·13

- [ ] **Step 1: 실패 테스트 작성** — (a) 테이블 rule 2 매칭 → 정규화 set ChangeSet (b) 매칭 없음+FakeLLM 제안 → llm 라벨, `validate_changeset` 통과 확인 (c) FakeLLM이 미허용 경로 제안 → (None, "none") (d) approve=False → intent 불변·재검증 미실행(FakeRunner 호출 0회) (e) approve=True → 재생성 1회+재검증 1회(호출 횟수 단언) (f) explain_failure LLM 없음 → 결정론 요약에 fail detail 포함.
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_corrections.py" -v`
- [ ] **Step 3: 구현** — 테이블+사이클 함수(~120행).
- [ ] **Step 4: 통과 확인** — Expected: `OK (6 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: validation correction proposals with single approved cycle"`

**완료 조건:** 승인 없이는 어떤 수정도 적용되지 않고, 승인 1회당 재생성·재검증이 정확히 1회임이 호출 횟수로 단언됨.

---

### Task 15: Non-Interactive CLI (`analyze` / `select` / `answer` / `generate` / `validate` / `sessions`)

**목표:** 스크립트·CI에서 쓸 수 있는 비대화형 커맨드 체계와 exit code 규약, 답변 파일 입력.

**이유:** 제품 결정(비대화형 지원). 위저드(Task 16)도 같은 서비스 함수를 재사용하므로 CLI가 먼저다.

**Files:**
- Create: `src/k8sagent/cli.py`, `src/k8sagent/__main__.py`
- Create: `tests/fixtures/agent/answers-node.yaml`
- Test: `tests/unit/agent/test_cli_agent.py`

**Interfaces:**
- Produces (커맨드 트리 — 전부 `python -m k8sagent <cmd>`):

```text
analyze <path|url> [--ref R] [--no-llm] [--k8s-version V]   # 세션 생성→획득→분석→후보 출력→세션ID 출력
select <session_id> (--components a,b | --all)              # 선택 적용, 경고 stdout, intent 초안+질문 파일 기록
answer <session_id> --answers-file FILE                    # 답변 일괄 적용(YAML: {<intent path>: value})
generate <session_id> --approve-plan                       # 플랜 요약 출력 후 --approve-plan 있을 때만 렌더
validate <session_id> [--k8s-version V]                    # 검증 실행, 집계 출력
sessions list | sessions show <session_id>
start [...]                                                # Task 16
```

  - `main(argv: list[str] | None = None) -> int` — exit code: `0` 성공(validate는 PASS), `1` AgentError/예외, `2` usage, `3` validate FAIL, `4` validate PARTIAL
  - 답변 파일 형식(`answers-node.yaml` 픽스처):

```yaml
answers:
  namespace: demo
  components.web.workload.image.registry: registry.example.com:5000
  components.web.workload.image.tag: "1.0.0"
  components.web.service.port: 3000
  components.web.workload.container_port: 3000
```

    → 내부적으로 `ChangeSet(origin="answers_file", changes=[Change(op="set", path=k, value=v) ...])`로 변환 후 공통 검증·적용. **비대화형 승인 규약:** `--answers-file` 제공과 `--approve-plan` 플래그가 명시적 승인 행위다. 자연어 요청은 비대화형에서 지원하지 않는다(승인 대화가 불가능하므로 — 제품 결정의 승인 요구 준수).
  - 세션 영속 산출물: `analyze`가 `intent/` 없이 종료, `select`가 `intent/intent.yaml`+`intent/questions.yaml`, `answer`가 갱신된 intent, `generate`가 `manifests/`+`intent/plan.txt`, `validate`가 `validation/report.yaml`
  - `build_manifest_plan(intent) -> str` — 렌더 예정 리소스/보류 사유의 결정론 요약(“web: Deployment, Service(3000), ConfigMap(2 keys); api: deferred — image.registry unresolved”)
- Consumes: Tasks 1~13 전부. LLM은 `--no-llm`/`K8S_AGENT_NO_LLM`/설정으로 끌 수 있고, 꺼져 있으면 `AgentLLMClient` 생성 자체를 건너뛴다.

**에러·보안:** 모든 커맨드는 상태 전이 검증(`advance`)을 통과해야 진행 — 예: `generate`를 `analyzed` 상태에서 부르면 `SessionError` 메시지에 필요한 선행 커맨드 안내. stdout에 토큰·Secret 값이 나갈 경로 없음(입력 자체에 없음).

- [ ] **Step 1: 실패 테스트 작성** — `test_cli_agent.py`는 기존 `tests/unit/test_cli.py` 패턴(main(argv) 직접 호출) + `K8S_AGENT_HOME=tmp` 환경 패치:

```python
class AgentCliFlowTests(unittest.TestCase):
    def test_full_noninteractive_flow_exit_codes(self):
        # fixture repo 복사 → analyze(0) → select --all(0) → answer(0)
        # → generate --approve-plan(0) → validate(0|3|4 중 기대값)
        # kubeconform/kubectl 유무에 의존하지 않도록 validate는 runner 주입 불가한 CLI 경계라
        # 종료 코드를 {0, 4}로 단언(FAIL이면 실패) — 세부 판정은 report.yaml 로드로 검증
    def test_generate_without_approve_plan_refuses(self):
        # exit 1 + manifests/ 미생성 + 세션 상태 불변
    def test_generate_before_select_rejected(self):   # exit 1, SessionError 안내
    def test_answer_invalid_value_exit1(self):        # port: "abc" → exit 1, intent 불변
    def test_sessions_list_and_show(self):
    def test_unknown_command_exit2(self):
    def test_analyze_local_path(self):                # 세션ID가 stdout에 출력
```

- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_cli_agent.py" -v`
- [ ] **Step 3: 구현** — `cli.py`는 파싱+서비스 함수 호출만(로직은 기존 태스크 모듈에). `__main__.py`는 `raise SystemExit(main())`.
- [ ] **Step 4: 통과 확인** — Expected: `OK (7 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: non-interactive agent CLI with session workflow"`

**완료 조건:** 픽스처 저장소로 analyze→…→validate 전 구간이 CLI로 완주(테스트로 고정), exit code 규약 문서화.

---

### Task 16: Interactive `start` Wizard (REPL)

**목표:** MVP 1~18단계를 한 세션에서 안내하는 대화형 위저드. 하이브리드 모델: 결정론 질문 + 자연어 변경 + 결정론 수동 변경(`set <path> <value>`).

**이유:** 제품 결정(interactive `start`). 모든 로직은 Tasks 1~15의 서비스 함수 재사용 — 위저드는 IO 순서만 소유한다.

**Files:**
- Create: `src/k8sagent/interactive.py`
- Test: `tests/unit/agent/test_interactive.py`, `helpers.py`에 `ScriptedConsole` 추가

**Interfaces:**
- Produces:
  - `Console` (dataclass): `input_fn: Callable[[str], str]`(기본 `input`), `out: TextIO`(기본 `sys.stdout`). `ask(prompt) -> str`, `say(text) -> None`, `confirm(prompt) -> bool`("y"/"yes"만 True)
  - `Wizard(config: AgentConfig, store: SessionStore, console: Console, llm: LLMProtocol | None, runner=run_command, clock=...)`: `.run(resume_session_id: str | None = None) -> int`
  - `run_start(args, config) -> int` — CLI `start` 커맨드 진입점 (`--session` 재개, `--no-llm`)
- Consumes: Tasks 1~15 전부

**위저드 단계 (MVP 단계 번호 매핑):**
1. [1~2] 저장소 입력 프롬프트(`path or URL`), URL이면 ref 질문 → `acquire_local`/`acquire_git` → SHA 표시
2. [3] 분석 실행 → LLM `explain_analysis` 있으면 표시, None이면 결정론 요약(컴포넌트 수·역할·포트 표)
3. [4~5] 후보 테이블 표시 → 콤마 목록 선택 → 의존성 경고 표시(선택 유지)
4. [6~8] topology/intent/gap 구축 → 미해결 필드 수 보고
5. [9~10] 질문 루프: blocking 질문 순회 — LLM `phrase_question` 문안(None이면 결정론 문안), `parse_answer` 실패 시 사유와 함께 재질문(최대 3회 후 건너뛰고 unresolved 유지), 답변은 즉시 적용·세션 저장. ingress/pvc opt-in 질문(`confirm`) 포함
6. [11~12] `build_manifest_plan` 표시 → 명령 루프: `approve` / `set <path> <value>` / `nl <자연어 요청>` / `show` / `quit`. `nl`: `llm.nl_to_changeset` → None이면 "구조화 실패 — set 명령을 사용하세요" → 성공 시 diff 표시 → `confirm` → 적용(거부 시 폐기). `set`: 단일 change ChangeSet으로 동일 경로. **모든 변경 후 plan 재표시**
7. [13~14] `approve` → 렌더 → 검증 → 집계·체크별 상태 표시
8. [15~18] FAIL이면 `explain_failure` 표시 → `propose_correction` → 제안 있으면 diff+`confirm` → `run_correction_cycle` → 새 결과 표시 → 다시 이 단계(제안이 없거나 거부하면 세션을 `validated` 상태로 저장하고 종료 안내) — 사이클마다 승인이 필요하므로 무한 루프 아님. PASS/PARTIAL이면 산출물 경로 요약 후 `completed`

**재개:** `start --session <id>` → 상태별 진입점 매핑(예: `intent_drafted`면 5번부터). 세션 저장은 각 상태 전이 직후.

- [ ] **Step 1: 실패 테스트 작성** — `ScriptedConsole(inputs: list[str])`이 순서대로 응답, 출력은 버퍼에 축적: (a) 해피패스: 픽스처 저장소 경로→전체 선택→질문 답변→approve→(FakeRunner로 검증 pass) → completed, 출력에 "PASS" 포함 (b) `nl` 요청 → FakeLLM ChangeSet → diff 표시 → "n" 거부 → intent 불변 (c) `nl` 승인 → 적용 후 plan 재표시 (d) LLM 없음(None) → 질문 문안이 결정론 테이블 문안과 일치 (e) 잘못된 답변 3회 → 질문 skip·unresolved 유지 (f) 재개: `intent_resolved` 세션 저장 후 `--session`으로 plan 단계 진입 (g) quit → 세션 저장·비파괴 종료.
- [ ] **Step 2: 실패 확인** — Run: `$RUN_UNIT discover -s tests/unit/agent -p "test_interactive.py" -v`
- [ ] **Step 3: 구현** — 상태 전이 헬퍼 + 단계 함수 8개(~250행). 비즈니스 로직 신규 작성 금지(전부 위임).
- [ ] **Step 4: 통과 확인** — Expected: `OK (7 tests)`
- [ ] **Step 5: Commit** — `git commit -m "feat: interactive start wizard"`

**완료 조건:** scripted IO로 승인 게이트 3종(플랜·NL 변경·수정)이 전부 "거부 시 미적용"으로 검증됨.

---

### Task 17: Acceptance E2E + Documentation + Full Regression

**목표:** 픽스처 저장소 대상 E2E 수용 테스트(비대화형 + 대화형 scripted), 문서 갱신, 전체 회귀.

**이유:** MVP 완결 판정 + 저장소 문서 관례 유지(AGENTS.md Completion).

**Files:**
- Create: `tests/acceptance/test_agent_workflow.py`
- Create: `src/k8sagent/CLAUDE.md` (src/CLAUDE.md와 동형의 모듈맵 — Purpose/모듈맵/불변식/검증 명령)
- Modify: `README.md` (에이전트 사용법 절 추가 — analyze→validate 예시, `start` 예시, 환경변수 표: `K8S_AGENT_HOME`, `K8S_AGENT_GIT_TOKEN`, `K8S_AGENT_NO_LLM`, `K8S_AGENT_K8S_VERSION`, `SEMANTIC_LLM_*` 재사용 명시. **무인증 온프렘 엔드포인트 주의**: `load_semantic_llm_settings`는 빈 `SEMANTIC_LLM_API_KEY`를 거부하므로(llm_config.py:63-69) AGENTS.md의 인증 헤더 없는 로컬 엔드포인트를 쓸 때는 더미 값(예: `none`)을 넣으라고 기재)
- Modify: `AGENTS.md` Context Loading 절에 `src/k8sagent/` 모듈맵 4행 추가
- Modify: `docs/architecture.md` §2 — 신규 절 "2.14 Interactive Agent Orchestrator ✅" 추가(레이어 표의 Orchestrator 행이 구현되었음을 상태 마커로 기록. 기존 절 본문은 미수정)

**E2E 테스트 사양:**

```python
class NonInteractiveE2ETests(unittest.TestCase):
    def test_node_express_full_flow(self):
        # git fixture: make_git_repo(files=node-express-like 파일들 복사)
        # → analyze(file:// URL, --ref main) : commit SHA가 세션에 기록됨
        # → select --all → answer(fixture answers) → generate --approve-plan
        # → manifests/ 골든 파일 존재 + deployment.yaml에 secretKeyRef만(값 없음)
        # → validate : report.yaml의 aggregate ∈ {PASS, PARTIAL}
        #   (kubeconform은 프로젝트 .tools에 있으므로 보통 실행됨 — kubectl 부재 시 PARTIAL)
        # → 같은 입력으로 generate 재실행 → manifests byte 동일 (결정론 E2E)
    def test_reanalysis_not_contaminated(self):
        # validate까지 간 저장소를 재-analyze → evidence/rule 산출물이 1차와 동일

class InteractiveE2ETests(unittest.TestCase):
    def test_scripted_wizard_completes(self):
        # ScriptedConsole + FakeLLM으로 로컬 픽스처 → completed
```

- [ ] **Step 1: E2E 테스트 작성 → 실패 확인** — Run: `$RUN_UNIT discover -s tests/acceptance -p "test_agent_workflow.py" -v`
- [ ] **Step 2: 통과할 때까지 통합 결함 수정** (신규 코드 범위 내에서만)
- [ ] **Step 3: 문서 4건 갱신** — 위 명세 그대로. 문서에 커맨드 예시는 실제 실행해 본 출력으로 기입
- [ ] **Step 4: kubeconform preflight + 전체 회귀** — Run:

```bash
python3 scripts/ensure_kubeconform.py --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
python3 scripts/validate_context_paths.py .
git diff --check
```

Expected: 전부 성공, 기존 368개 + 신규 ~100개 테스트 green.
- [ ] **Step 5: Commit** — `git commit -m "test: agent e2e acceptance; docs: agent usage"`

**완료 조건:** 전체 스위트 green, 문서-코드 일치(README 예시가 실행 검증됨), `13-validation-report` 유사물(`validation/report.yaml`)에 kubeconform pass/fail이 기록됨(AGENTS.md Required Tooling 준수).

---

## Part 5 — MVP Requirement Traceability Audit

| 요구(fixed scope/decisions) | 태스크 | 검증 방법 |
|---|---|---|
| 1 로컬 경로/Git URL 수용 | 4, 15 | test_repo, test_cli_agent |
| 2 정확한 리비전 준비/기록 | 4 (+기존 snapshot) | test_repo `test_clone_records_exact_sha`, E2E |
| 3 기존 결정론 파이프라인 실행 | 5 | test_analysis |
| 4 배포 후보 탐지 | 6 | test_components |
| 5 컴포넌트 선택 + 제외 의존성 경고 | 6, 16 | test_components (c)/(e) |
| 6 Application Topology | 7 | test_topology |
| 7 Kubernetes Intent | 8 | test_intent |
| 8 미해결 필드 탐지 | 9 | test_gaps_questions |
| 9~10 구조화 질문/답변 적용 | 9, 15, 16 | 〃 + CLI/위저드 테스트 |
| 11 매니페스트 플랜 표시 | 15 (`build_manifest_plan`), 16 | test_cli_agent, test_interactive |
| 12 NL 변경 승인 게이트 | 10, 11, 16 | test_interactive (b)/(c) |
| 13 순수 Python 렌더러 YAML | 12 | test_render 골든/경계 |
| 14 로컬 검증 4단계 | 13 | test_validate |
| 15 실패 설명 | 14 | test_corrections (f) |
| 16 구조화 수정 제안 | 14 | test_corrections (a)/(b) |
| 17 승인 후에만 수정 적용 | 14 | test_corrections (d) |
| 18 승인당 1회 재생성·재검증 | 14 | test_corrections (e) |
| 세션 생성/영속/재개 | 3, 16 | test_session, test_interactive (f) |
| 설정 로딩·우선순위 | 1 | test_config |
| 토큰 4중 안전 + redaction | 2, 4 | test_procutil, TokenSafetyTests |
| PASS/FAIL/PARTIAL 집계 | 13 | test_validate |
| K8s 버전 기본+override | 1, 13, 15 | test_config, test_validate (f), CLI `--k8s-version` |
| LLM 구조화 출력+폴백 | 11 | test_llm |
| Secret 값 미생성·참조만 | 8, 12 | test_render (c) |
| 결정론 분석기의 LLM 독립 | 5 (D6), 12 import 경계 | test_render (h), semantic_mode="disabled" 고정 |
| 저장소 캐싱 | 4 | test_repo `test_second_acquire_uses_cache_fetch` |
| 산출물 위치 규약(홈/저장소 분리) | 1, 3, 5 | test_session, test_analysis |
| 비대화형 워크플로우 | 15 | test_cli_agent 전체 플로우 |
| 대화형 워크플로우 | 16 | test_interactive |
| 문서 갱신 + 전체 회귀 | 17 | E2E + 4중 검증 명령 |
| 범위 밖(배포/Helm/StatefulSet 등) 미구현 | 전체 | 커맨드·렌더러·상태 기계에 해당 표면 자체가 없음 |

**검증되지 않은 가정 (구현 태스크에서 확인할 것):**
- A-1: `Tracked`(pydantic dataclass)가 신규 BaseModel의 `dict[str, Tracked[str]]` 값 타입으로도 직렬화 왕복이 매끄러운지 — Task 7·8의 왕복 테스트가 1차 검증 지점. 문제 시 `TypeAdapter` 명시 직렬화로 우회.
- A-2: `ArtifactInventory` 카테고리 필드명(Task 5 테스트에서 사용) — 구현 시 `models/inventory.py` 확인 후 확정.
- A-3: 이 환경의 kubeconform `.tools/` 설치 상태 — Task 17 Step 4의 preflight가 판정. 미설치면 E2E는 PARTIAL 기대값으로 작성돼 있어 실패하지 않음.

## Part 6 — Risks and Mitigations

| 위험 | 영향 | 완화 |
|---|---|---|
| `path_safety` 변경이 기존 스냅샷 단언과 충돌 | 기존 스위트 red | Task 5 Step 5에서 전체 회귀를 태스크 내 게이트로 강제. `assertIn` 확인 완료(§1.4) |
| Git ref 해석의 원격별 편차(origin/HEAD 부재 등) | 획득 실패 | 해석 순서 명시(SHA→ref→origin/ref) + 실패 시 명확한 `RepoAcquisitionError`. file:// 실 git 테스트로 로컬 검증 |
| LLM이 ChangeSet 스키마를 자주 못 맞춤 | NL 기능 체감 저하 | 실패는 항상 None→`set` 수동 명령 폴백 존재. 스키마·허용경로를 프롬프트에 동봉, 1회 재시도만 |
| kubeconform/kubectl 부재 환경에서 E2E 기대값 흔들림 | flaky 테스트 | 집계 기대값을 `{PASS, PARTIAL}`로 작성, FAIL만 실패 처리. 도구 존재 검사로 분기하지 않음(집계 자체가 그 정보를 담음) |
| 위저드 테스트의 입력 시나리오 취약성 | 유지보수 비용 | 프롬프트 문자열 매칭이 아닌 입력 순서 계약으로 작성, 질문 순서는 결정론(정렬) 보장 |
| 세션 스키마 진화 | 재개 실패 | MVP는 스키마 버전 필드 없이 pydantic 관용 파싱(`extra="ignore"` 기본) + 손상 시 `SessionError`로 명시 실패. 마이그레이션은 범위 밖으로 명시 |
| askpass 방식의 플랫폼 제약(Windows) | 미지원 플랫폼 | 현 환경(Linux/WSL2) 명시, Windows는 문서에 미지원 기재 |

## Part 7 — Final End-to-End Verification Commands

구현 완료 선언 전 순서대로 전부 실행 (superpowers:verification-before-completion):

```bash
# 1. 도구 preflight
python3 scripts/ensure_kubeconform.py --check

# 2. 전체 테스트 (기존 368 + 신규)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v

# 3. 컨텍스트 경로 검증 + diff 위생
python3 scripts/validate_context_paths.py .
git status --short && git diff --check

# 4. 실 사용 스모크 (픽스처 저장소, LLM 없이)
TMP=$(mktemp -d) && cp -r tests/fixtures/repos/node-express-like "$TMP/repo"
export K8S_AGENT_HOME="$TMP/home" K8S_AGENT_NO_LLM=1
PYTHONPATH=src .venv/bin/python3 -m k8sagent analyze "$TMP/repo"        # → 세션ID 확인
PYTHONPATH=src .venv/bin/python3 -m k8sagent select <SID> --all
PYTHONPATH=src .venv/bin/python3 -m k8sagent answer <SID> --answers-file tests/fixtures/agent/answers-node.yaml
PYTHONPATH=src .venv/bin/python3 -m k8sagent generate <SID> --approve-plan
PYTHONPATH=src .venv/bin/python3 -m k8sagent validate <SID>; echo "exit=$?"
# 기대: manifests/ 생성, validation/report.yaml aggregate ∈ {PASS, PARTIAL}, exit ∈ {0, 4}

# 5. 결정론 확인 (재생성 전 사본과 byte 비교)
cp -r "$TMP/repo/k8s-agent-output/manifests" "$TMP/manifests-before"
PYTHONPATH=src .venv/bin/python3 -m k8sagent generate <SID> --approve-plan
diff -r "$TMP/manifests-before" "$TMP/repo/k8s-agent-output/manifests" && echo DETERMINISTIC

# 6. 토큰 비영속 grep (private repo 테스트 후)
grep -R "K8S_AGENT_GIT_TOKEN\|$K8S_AGENT_GIT_TOKEN" "$K8S_AGENT_HOME" && echo LEAK || echo CLEAN
```
