# k8s-deploy-preanalyzer

GitHub 저장소를 분석해 Kubernetes 매니페스트 생성에 필요한 정보를 뽑아내는 워크플로우.
전체 설계는 [onprem-llm-k8s-manifest-preanalysis-workflow.md](./onprem-llm-k8s-manifest-preanalysis-workflow.md),
기능별 세부 규칙은 [docs/pipeline-details.md](./docs/pipeline-details.md) 참고.

## 핵심 설계 원칙

- **결정론 우선, LLM은 나중**: 탐지·파싱·근거 생성엔 LLM을 쓰지 않는다. LLM은 저장소 전체가 아니라 정제된 Evidence Bundle만 본다.
- **추측 금지**: 확인 불가한 값은 기본값 대신 `unresolved` + 질문으로 남긴다.
- **근거 추적성**: 모든 필드는 `value / source / confidence / classification / evidence_refs`를 가진다.
- **비밀값 비유출**: Secret은 이름·출처·분류만 기록하고 값은 LLM·산출물에 흘리지 않는다.
- **재현성**: 동일 commit + Profile + rules_version → 동일 산출물.

## 현재 개발 현황

전체는 Step 0~15. 현재 코드는 **Step 12까지 MVP 흐름이 연결된 상태**다.
단, Step 5~12는 전체 설계의 모든 세부 기능이 아니라 "분석 → Intent → 템플릿 렌더링 → 검증 리포트"가
fixture 기반으로 관통하는 최소 구현이다. Step 13~15는 자동 실행이 아니라 checklist/plan 산출 수준이다.

- Step 0~6 ✅ — snapshot / artifact inventory / 배포파일 파싱 / component 탐지 / 언어·빌드 탐지 / 런타임 추출 / 포트·env·volume·의존 분석
- Step 5~7 ◐ — bounded semantic agent / 도구 예산 / verifier / OpenAI-compatible provider 경로. 현재는 runtime command 보강 중심
- Step 8~10 ◐ — Reconciliation / Profile merge / unresolved 질문 생성. 충돌 정책과 user_decision provenance는 아직 MVP 수준
- Step 11 ✅ — Template Renderer: Deployment, Service, ServiceAccount, ConfigMap, Secret placeholder, Ingress 템플릿 렌더링
- Step 12 ◐ — YAML syntax → project-managed kubeconform → kubectl dry-run 검증 체인. linter/policy engine은 미구현
- Step 13~15 ⬜ — Deployment Check / Smoke Test 실행 / Repair Loop 자동화는 미구현. readiness checklist와 smoke-test-plan 초안만 생성

결정론 분석 체인 (저장소에서 바로 YAML로 가는 지름길은 없다):

```text
repository_snapshot → artifact_inventory → evidence_model → rule_inference
```

Semantic agent는 도메인 모델·읽기 도구·예산 추적·검증기 + **bounded agent 상태기계**와
**OpenAI 호환 온프렘 LLM provider**까지 배선됨. 전체 분석 파이프라인은 `00-repository-snapshot.yaml`부터
`15-smoke-test-plan.yaml`까지 산출할 수 있으며, `13-validation-report.yaml`의 `kubeconform: skipped`는
Kubernetes schema 검증이 완료되지 않았다는 뜻이다.

## 개발 환경 설정

시스템 Python에 `pip`이 없을 수 있어 프로젝트 전용 가상환경을 쓴다.

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0"
```

`uv`가 없으면 표준 `venv` + `pip install -e .`로 대체.

## Required manifest validation tool

Install/check the project-managed kubeconform binary before running manifest validation:

```bash
python3 scripts/ensure_kubeconform.py --check
```

The binary is installed under `.tools/` and is not committed. Supported platforms are Linux amd64, Linux arm64, and Windows amd64.

## 테스트 실행

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

`tests/fixtures/repos/` 아래 샘플 레포 3종(`jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`)이 end-to-end 검증에 쓰인다.

## 직접 실행

```python
from datetime import datetime, timezone
from pathlib import Path
from preanalyzer.pipeline import run_analysis

run_analysis(
    repo=Path("./my-repo"), output_dir=Path("./out"),
    url="https://github.com/example/my-repo", ref="main",
    clock=lambda: datetime.now(timezone.utc),
)
```

`./out/`에 `00-repository-snapshot.yaml` ~ `15-smoke-test-plan.yaml` 산출물이 생성된다.
결정론 사전분석 4개 파일만 필요하면 `run_phase1_analysis(...)`를 사용할 수 있다.

Snapshot 모드·Compose·Component ownership·Semantic budget·**Semantic LLM provider**(온프렘 OpenAI 호환 연동) 등 세부는 [docs/pipeline-details.md](./docs/pipeline-details.md) 참고.

## 대화형 Kubernetes Agent MVP

저장소를 분석한 뒤 질문 답변을 반영해 `k8s-agent-output/` 아래에 매니페스트와 검증 리포트를 만든다.
CLI는 세션 단위로 이어서 실행할 수 있다.

```bash
PYTHONPATH=src .venv/bin/python3 -m k8sagent analyze tests/fixtures/repos/node-express-like --no-llm
PYTHONPATH=src .venv/bin/python3 -m k8sagent select <session-id> --all
PYTHONPATH=src .venv/bin/python3 -m k8sagent answer <session-id> --answers-file tests/fixtures/agent/answers-node.yaml
PYTHONPATH=src .venv/bin/python3 -m k8sagent generate <session-id> --approve-plan
PYTHONPATH=src .venv/bin/python3 -m k8sagent validate <session-id>
```

스크립트 없이 진행하려면:

```bash
PYTHONPATH=src .venv/bin/python3 -m k8sagent start --no-llm
```

주요 환경 변수:

- `K8S_AGENT_HOME`: 세션과 캐시 저장 위치. 기본값은 `.k8s-agent/`.
- `K8S_AGENT_GIT_TOKEN`: 비공개 Git 저장소 clone에 쓰는 토큰 변수명.
- `K8S_AGENT_NO_LLM`: `1`이면 LLM을 쓰지 않고 결정론 질문만 사용.
- `K8S_AGENT_K8S_VERSION`: 검증 대상 Kubernetes 버전.
- `K8S_AGENT_LLM_BASE_URL`: 기본값 `http://192.168.30.167:30000/v1`.
- `K8S_AGENT_LLM_MODEL`: 비워두면 `GET /models`로 실제 모델 ID를 먼저 확인.
- `K8S_AGENT_LLM_TIMEOUT_SECONDS`: LLM HTTP 요청 제한 시간.

Agent LLM 호출은 `Authorization` 헤더를 보내지 않고 `Content-Type: application/json`만 사용한다.
LLM은 질문 문구·구조화된 변경 제안·오류 설명에만 쓰이며 Kubernetes YAML을 직접 만들지 않는다.

## 프로젝트 구조

오케스트레이션은 `src/preanalyzer/pipeline.py`, 모듈 상세는 각 디렉터리 CLAUDE.md 참고.

```text
src/preanalyzer/    # analyzer(scanner/parsers/evidence/rule) + models + pipeline
src/k8sagent/       # interactive agent sessions + intent + deterministic render/validate
tests/              # unit · acceptance · fixtures/repos
docs/               # architecture.md, pipeline-details.md, adr, tasks
```

> 주의: designed 상태와 implemented 상태를 혼동하지 말 것. 코드 쪽 진실은
> [docs/architecture.md](./docs/architecture.md) §2의 구현 상태 마커다.
