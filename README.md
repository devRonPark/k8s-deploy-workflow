# k8s-deploy-preanalyzer

GitHub 저장소를 분석해서 Kubernetes 매니페스트 생성에 필요한 정보를 뽑아내는 워크플로우.
전체 설계는 [`onprem-llm-k8s-manifest-preanalysis-workflow.md`](./onprem-llm-k8s-manifest-preanalysis-workflow.md) 참고.

## 핵심 설계 원칙

- **결정론 우선, LLM은 나중**: 파일 탐지·파싱·근거(evidence) 생성 단계에는 LLM을 쓰지 않는다. LLM은 Repository 전체가 아니라 정제된 Evidence Bundle만 본다.
- **추측 금지**: 확인할 수 없는 값은 조용히 기본값을 채우지 않고 `unresolved` + 질문으로 남긴다.
- **근거 추적성**: 모든 추출/해석 필드는 `value / source / confidence / classification / evidence_refs`를 가진다.
- **비밀값 비유출**: Secret은 이름·출처·분류 근거만 기록하고 값 자체는 LLM에도, 산출물에도 흘리지 않는다.
- **재현성**: 동일 commit + 동일 Profile + 동일 rules_version → 동일 산출물.

## 현재 개발 현황

전체 워크플로우는 Step 0~15로 구성되며, **Step 0~6 (결정론적 사전분석, "Phase 1")까지 완료된 상태**다.

| Step | 내용 | 상태 |
|---|---|---|
| 0 | Repository Snapshot | ✅ 완료 |
| 1 | Artifact Inventory (Dockerfile/compose/package.json 등 탐지) | ✅ 완료 |
| 2 | 기존 배포 파일 분석 (Dockerfile/compose 파싱) | ✅ 완료 |
| 3 | Component/Service 후보 탐지 | ✅ 완료 |
| 4 | 언어/프레임워크/빌드 방식 탐지 | ✅ 완료 |
| 5 | 런타임 정보 추출 (버전/포트/실행커맨드) | ✅ 완료 |
| 6 | 포트/env/volume/의존관계 분석 | ✅ 완료 |
| 7 | Application Topology Model 생성 | ⬜ 미착수 |
| 8 | Kubernetes Intent Model 생성 | ⬜ 미착수 |
| 9 | 불확실 값 질문 생성 (LLM 개입 시작점) | ⬜ 미착수 |
| 10 | Deployment Profile 병합 | ⬜ 미착수 |
| 11 | 템플릿 기반 매니페스트 렌더링 | ⬜ 미착수 |
| 12 | Kubernetes 유효성 검증 | ⬜ 미착수 |
| 13 | 배포 테스트 | ⬜ 미착수 |
| 14 | 스모크 테스트 | ⬜ 미착수 |
| 15 | 리페어 루프 | ⬜ 미착수 |

Phase 1이 처리하는 파이프라인 체인:

```
repository_snapshot → artifact_inventory → evidence_model → rule_inference
```

Repository에서 바로 YAML로 가는 지름길은 없다 — 각 단계가 산출물(`00~03-*.yaml`)로 명시적으로 남는다.

Phase 1이 산출하는 것 (`03-rule-inference.yaml` 기준):
- Runtime 후보: 언어/버전, 포트, 실행 커맨드 (Dockerfile `FROM`/`EXPOSE`/`CMD` 기반)
- Dependency edge 후보: `depends_on`, `DATABASE_URL` 등 compose 근거 기반
- Secret 후보: 이름만 (값 없음)
- 손상된 파일(`package.json`, `pom.xml`, `pyproject.toml`)을 만나도 죽지 않고 경고만 기록
- Compose override(`docker-compose.override.yml`) 병합, 정의되지 않은 key는 경고로 기록

## Semantic analysis support status

The repository now includes deterministic support code that prepares for a bounded semantic agent, but it does not yet run an LLM or persist a final semantic-analysis artifact.

Implemented support:
- Semantic task models and runtime-command task building for deterministic runtime gaps.
- Constrained semantic read/search/inspect tools scoped to one component.
- Deterministic semantic candidate verification.
- Task-level semantic tool budget tracking through `SemanticToolSession`.

Not implemented:
- LLM executor or semantic orchestrator.
- Persisted semantic output artifact.
- Application Topology Model.
- Kubernetes Intent Model.
- Manifest rendering, validation, deployment, smoke testing, or repair loop.

Phase 1이 하지 않는 것: 실제 매니페스트 생성, LLM 기반 의미 분석/추론, 배포·검증·복구.

## 개발 환경 설정

시스템 Python에는 `pip`이 없는 환경일 수 있으므로, 프로젝트 전용 가상환경을 사용한다.

```bash
# uv로 venv 생성 (시스템 site-packages 상속 — PyYAML 등을 재설치하지 않기 위함)
uv venv --system-site-packages .venv

# 의존성 설치 (pydantic 등)
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0"
```

`uv`가 없다면 표준 `venv` + `pip`으로 대체 가능:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 테스트 실행

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

단위 테스트와 acceptance 테스트는 아래 명령으로 함께 실행한다. `tests/fixtures/repos/` 아래 샘플 레포 3종(`jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`)이 end-to-end 검증에 사용된다.

## Phase 1 파이프라인 직접 실행해보기

```python
from datetime import datetime, timezone
from pathlib import Path
from preanalyzer.pipeline import run_phase1_analysis

clock = lambda: datetime.now(timezone.utc)
run_phase1_analysis(
    repo=Path("./my-repo"),
    output_dir=Path("./out"),
    url="https://github.com/example/my-repo",
    ref="main",
    clock=clock,
)
```

`./out/` 아래에 `00-repository-snapshot.yaml`, `01-artifact-inventory.yaml`, `02-evidence-model.yaml`, `03-rule-inference.yaml` 4개 파일이 생성된다.

## Snapshot 모드 (재현성)

`run_phase1_analysis(..., mode=...)`로 분석 입력의 재현성 기준을 선택한다.

| mode | 분석 대상 | 재현성 의미 |
|---|---|---|
| `workspace` (기본) | 현재 working tree | 커밋하지 않은 변경·untracked 파일 포함. `workspace_hash`(분석 대상 파일 내용 해시)가 재현성 키이며, dirty 여부·수정/untracked 파일 목록을 snapshot에 기록 |
| `commit` | `git archive HEAD` 트리 | working tree 상태와 무관하게 **동일 commit → byte-identical 산출물**. 커밋되지 않은 값은 산출물·prompt에 노출되지 않음 |

Snapshot metadata에 `snapshot_mode`, `workspace_hash`, `workspace_dirty`, `modified_files`, `untracked_files`가 포함된다. `commit` 모드에서 git 저장소가 아니면 working tree로 fallback하고 warning을 남긴다.

## Compose 지원 범위

- **override 병합**: Compose 공식 병합 규칙을 따른다 — mapping 재귀 병합, `ports`(host_ip/published/target/protocol 키)·`volumes`(target 키)·`secrets`/`configs` 키 기준 병합, `environment`/`labels` map·list 표현 통합, `command`/`entrypoint`/`healthcheck.test` 교체, `!override`/`!reset` 태그 지원. port 병합 결과는 `docker compose config`와 대조하는 golden test로 검증한다.
- **port 파싱**: `raw` 원문을 항상 보존하고 host IP·IPv6 bracket·protocol·`${VAR}`·`${VAR:-default}`·range를 인식한다. 단일 정수로 확정할 수 없는 값(default 없는 `${VAR}`, range)은 **추측하지 않고** `resolved=false` + `warning`으로 기록한다.
- **environment**: 원문 값은 저장하지 않는다(secret 정책). bare key(`- DEBUG`)는 `source: host_environment`로, 명시적 빈 값과 구분해 기록한다.
- **제한**: env 값 interpolation은 의도적으로 수행하지 않는다(secret 비유출). port range는 개별 포트로 전개하지 않는다.

## Component ownership

- Compose service 후보와 package(manifest) 후보를 **union + reconcile**한다. compose `build.context`가 가리키는 root의 package는 해당 service에 흡수되고, 매칭되지 않는 monorepo package는 별도 component로 남는다.
- **image-only service**(`root_path=None`)는 source root를 소유하지 않아 runtime/framework가 잘못 연결되지 않는다.
- artifact는 **longest-prefix** 규칙으로 가장 구체적인 component에 귀속된다(중첩 package 오귀속 방지).

## Semantic budget

- Semantic tool 호출은 `SemanticToolSession`을 통해 실행되며 task 단위 `BudgetLedger`가 tool call·distinct tool·unique file·source line·schema retry를 **누적 강제**한다. 한도 도달 시 이후 호출은 실행 없이 `budget_exhausted`로 거부되고, 직전까지의 evidence는 보존된다.

## Semantic LLM provider

실제 모델 연동은 OpenAI 호환 Chat Completions API와 OpenAI Python SDK를 사용한다.

필요한 환경변수:

```bash
export SEMANTIC_LLM_BASE_URL="https://your-llm.example/v1"
export SEMANTIC_LLM_MODEL="your-model"
export SEMANTIC_LLM_API_KEY="..."
export SEMANTIC_LLM_TIMEOUT_SECONDS="30"
```

`SEMANTIC_LLM_API_KEY` 값은 커밋하지 않는다. 실제 값은 `.env`처럼 git에서 제외되는 로컬 파일이나 실행 환경에만 둔다. `.env.example`은 이름과 예시 형식만 남기는 용도로 사용한다.

Provider 생성:

```python
from preanalyzer.semantic import OpenAIChatDecisionProvider

provider = OpenAIChatDecisionProvider.from_env()
```

이 provider는 기존 `run_semantic_agent(...)`의 `decision_provider` 인자로 사용할 수 있다. 모델은 전체 repository를 받지 않고, 한 task의 제한된 `SemanticDecisionContext`만 받는다. 도구 허용 목록, 예산, component 범위, 검증기는 기존 agent loop가 계속 강제한다.

## Python requirements

- `requirements.txt`의 `-r`/`-c` include, index/`--hash` 옵션, editable/VCS/direct-URL 참조를 일반 package와 분리한다. VCS URL의 credential은 저장하지 않고 `#egg=` 이름만 남긴다.

## 프로젝트 구조

```
src/preanalyzer/
  analyzer/
    scanner.py           # Step 0-1: snapshot + artifact inventory
    parsers/              # Step 2: Dockerfile/compose/maven/nodejs/python 파서
    evidence_builder.py    # 파싱 결과 → 근거(evidence) 모델
    rule_inference.py      # 근거 → 후보(candidate) 추론
  models/                 # pydantic 데이터 모델 (snapshot/inventory/evidence/rule_inference)
  pipeline.py             # 전체 Phase 1 오케스트레이션 + YAML 출력
tests/
  unit/                   # 단위 테스트
  acceptance/             # 샘플 레포 기반 end-to-end 테스트
  fixtures/repos/         # 테스트용 샘플 레포 3종
docs/superpowers/         # 개발 과정 기록 (plan, task brief/report, review)
```

## 다음 단계

Step 7(Application Topology Model) 이후의 최종 모델과 Kubernetes 산출물 생성은 아직 구현 전이다. 다만 런타임 명령처럼 결정론만으로 확정하기 어려운 일부 값을 다루기 위한 semantic task 모델, 제한된 읽기 도구, 예산 추적, 결정론적 검증기는 준비되어 있다.
