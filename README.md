# k8s-deploy-preanalyzer

기존 애플리케이션 저장소를 읽어서 Kubernetes 매니페스트를 만들기 전에 필요한 배포 근거, 중간 모델, 매니페스트 초안, 검증 결과, 미해결 질문을 생성하는 사전 분석 워크플로우입니다.

이 도구는 저장소 내용을 LLM에 통째로 넘겨 Kubernetes YAML을 바로 만들지 않습니다. 먼저 Dockerfile, Compose, package metadata, 소스 구조를 결정론적으로 분석하고, 확인할 수 없는 값은 추측하지 않고 질문이나 unresolved 항목으로 남깁니다.

## What is this?

`k8s-deploy-preanalyzer`는 애플리케이션 저장소에서 Kubernetes 배포 준비에 필요한 정보를 추출합니다.

- 배포 단위 후보(component), 런타임, 포트, 환경변수 이름, 볼륨, 의존 서비스 후보를 찾습니다.
- 근거가 있는 값과 없는 값을 분리해 `value / source / confidence / classification / evidence_refs` 형태로 추적합니다.
- Intent Model과 검증된 템플릿을 거쳐 Kubernetes 리소스를 렌더링합니다.
- Secret 값은 산출물, 로그, LLM 입력에 넣지 않고 이름과 분류 정보만 남깁니다.
- LLM 연동은 선택 사항이며, 켜더라도 제한된 semantic task 보강에만 사용합니다.

## Repository Assessment Beta

`repository-agent`는 v1 beta CLI입니다. 이 경로는 Repository Assessment Beta이며, not a complete migration agent입니다. 입력 저장소를 분석해 Confirmed, Unknown, Conflict가 분리된 평가 보고서를 만들지만 Kubernetes manifests are not generated in v1.

```bash
.venv/bin/repository-agent assess tests/fixtures/migration_agent/node-docker
```

기본 산출물은 `.repository-agent/runs/<run-id>` 아래에 저장됩니다.

- `discovery.json`
- `repository-understanding.yaml`
- `repository-assessment.json`
- `repository-assessment.md`

## When to use it

다음 상황에서 유용합니다.

- 기존 Node, Python/FastAPI, Java/Spring, Docker Compose 기반 앱을 Kubernetes로 옮기기 전에 배포 입력을 정리할 때
- Dockerfile, Compose, package metadata가 섞인 저장소에서 런타임 명령, 포트, 환경변수, 볼륨, 서비스 의존성을 근거 기반으로 확인할 때
- Secret 값을 노출하지 않고 ConfigMap/Secret 후보를 분리해야 할 때
- CI에서 "매니페스트 검증이 어디까지 되었는지"를 산출물로 남기고 싶을 때
- Platform/DevOps 엔지니어가 최종 환경값을 넣기 전에 검토 가능한 출발점을 만들 때

## Quick Start

Python 3.11 이상이 필요합니다. 시스템 Python에 직접 패키지를 설치하지 않고 프로젝트 전용 가상환경을 사용합니다.

```bash
git clone <repo-url>
cd k8s-deploy-workflow

uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 -e .
```

`uv`가 없으면 표준 `venv`를 만든 뒤 editable install을 사용해도 됩니다.

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -e .
```

설치가 끝나면 세 CLI를 사용할 수 있습니다.

```bash
.venv/bin/k8s-agent --help
.venv/bin/preanalyzer --help
.venv/bin/repository-agent --help
```

Kubernetes schema 검증에는 프로젝트가 관리하는 `kubeconform` 바이너리가 필요합니다. 아래 명령은 없으면 설치하고, 실행 가능 여부까지 확인합니다.

```bash
python3 scripts/ensure_kubeconform.py --check
```

먼저 포함된 샘플 저장소를 Agent MVP 흐름으로 실행합니다. LLM 설정이 없어도 결정론 분석과 가능한 검증까지 진행합니다.

```bash
.venv/bin/k8s-agent prepare \
  --local-path tests/fixtures/repos/node-express-like \
  --target development
```

명령은 `run_id`, `state`, `run_root`, 다음 행동을 출력합니다. 산출물은 출력된 `run_root` 아래에 저장됩니다.

자주 보는 후속 명령은 다음과 같습니다.

```bash
.venv/bin/k8s-agent status <run-id>
.venv/bin/k8s-agent explain <run-id> <decision-or-field>
.venv/bin/k8s-agent export <run-id> --output out/manifests --overwrite
```

중단된 run은 source drift 정책을 명시해 재개할 수 있습니다.

```bash
.venv/bin/k8s-agent resume <run-id> --drift-policy replan
```

## Run on your repository

샘플 실행 후에는 자신의 저장소 경로를 넘겨 실행합니다.

```bash
.venv/bin/k8s-agent prepare \
  --local-path ./my-repo \
  --target development
```

원격 저장소도 사용할 수 있습니다.

```bash
.venv/bin/k8s-agent prepare \
  --repo-url https://github.com/acme/my-repo.git \
  --ref main \
  --target staging
```

`--target`은 현재 `development`, `staging`, `production` 중 하나입니다. 확인이 필요한 값이 있으면 run directory의 질문 산출물에 남기고, 자동 실행에서는 answers file을 넣어 이어갈 수 있습니다.

```bash
.venv/bin/k8s-agent prepare \
  --local-path ./my-repo \
  --target development \
  --non-interactive \
  --answers-file answers.yaml
```

고급 단계별 실행이 필요하면 같은 run artifact를 기준으로 분석, 계획, 생성, 검증을 분리할 수 있습니다.

```bash
.venv/bin/k8s-agent analyze --local-path ./my-repo --target development
.venv/bin/k8s-agent plan <run-id>
.venv/bin/k8s-agent generate <run-id> --profile-revision 1
.venv/bin/k8s-agent validate <run-id>
```

저수준 preanalyzer만 단독으로 실행할 수도 있습니다. 이 명령은 Agent run state 없이 번호가 붙은 분석 산출물을 지정한 출력 디렉터리에 씁니다.

```bash
.venv/bin/preanalyzer analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --no-llm \
  --out out/node-express-like
```

## Optional LLM integration

LLM은 필수가 아닙니다. 다만 OpenAI-compatible endpoint를 연결하면 제한된 semantic task에서 런타임 명령 같은 애매한 값을 보강하는 데 사용할 수 있습니다. LLM은 최종 Kubernetes YAML을 자유 생성하지 않으며, 전체 저장소를 컨텍스트로 받지 않습니다.

Agent MVP에서는 `K8S_AGENT_LLM_*` 환경변수를 우선 사용합니다.

```bash
export K8S_AGENT_LLM_BASE_URL="https://your-llm.example/v1"
export K8S_AGENT_LLM_MODEL="your-model"
export K8S_AGENT_LLM_API_KEY="your-key"
export K8S_AGENT_LLM_TIMEOUT_SECONDS="30"
```

`K8S_AGENT_LLM_MODEL`을 생략하면 에이전트가 먼저 `GET /models`로 실제 모델 ID를 확인합니다.

```bash
curl "$K8S_AGENT_LLM_BASE_URL/models"
```

인증이 없는 로컬 OpenAI-compatible endpoint에서는 `K8S_AGENT_LLM_API_KEY`를 설정하지 않습니다. 이 경우 요청 헤더에는 `Authorization`을 넣지 않고 `Content-Type: application/json`만 사용합니다. 실제 API key, token, password는 커밋하지 마세요.

기존 `SEMANTIC_LLM_*` 환경변수도 호환 경로로 읽지만, Agent MVP에서는 `K8S_AGENT_LLM_*`를 먼저 봅니다.

저수준 preanalyzer에서 LLM을 켜는 예시는 다음과 같습니다.

```bash
.venv/bin/preanalyzer analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --semantic-mode openai_compatible \
  --out out/node-express-like-llm
```

## What to inspect first

`k8s-agent` run에서는 출력된 `run_root` 아래의 파일을 먼저 확인하세요.

- `agent` 디렉터리의 `questions.yaml`: 도구가 안전하게 결정하지 못한 값과 답변 후보
- `profile` 디렉터리의 `deployment-profile.yaml`: 질문과 정책을 반영한 배포 입력
- `generated` 디렉터리의 `manifest-bundle.yaml`: 렌더링된 Kubernetes 리소스 묶음
- `validation` 디렉터리의 `13-validation-report.yaml`: YAML syntax, internal manifest checks, project-managed kubeconform 검증 결과

저수준 `preanalyzer analyze` 산출물에서는 아래 파일을 먼저 봅니다.

- `06-component-model.yaml`: 감지된 배포 단위와 component 경계
- `10-unresolved-questions.yaml`: 도구가 안전하게 결정하지 못한 값
- `11-deployment-profile.yaml`: 실행에 사용된 deployment profile 값. profile을 주지 않으면 `null`
- `12-generated-manifests/`: Intent Model과 템플릿에서 렌더링된 Kubernetes 리소스 파일
- `13-validation-report.yaml`: YAML syntax, internal manifest checks, project-managed kubeconform 검증 결과. `generation_holds`는 안전하게 만들 수 없어 `생성 보류`된 리소스와 필요한 해소 값을 보여줍니다.

전체 preanalyzer 파이프라인은 `00-repository-snapshot.yaml`부터 `15-smoke-test-plan.yaml`까지의 산출물을 만들 수 있습니다.

`13-validation-report.yaml`에 `kubeconform: skipped`, `kubeconform: not-run`, 또는 `tool-missing`이 기록되어 있으면 Kubernetes schema 검증이 완료된 것이 아닙니다. 이 경우 `python3 scripts/ensure_kubeconform.py --check`를 먼저 확인하세요.

## Current status and limitations

현재 Kubernetes Deploy Agent MVP는 "source 획득 → 분석 → Intent → 질문/답변 → Profile → 템플릿 렌더링 → 검증 → 제한적 리페어 → 보고/export" 흐름이 샘플 저장소 기준으로 관통합니다.

- Step 0~6: snapshot, artifact inventory, 배포파일 파싱, component 탐지, 언어/빌드 탐지, 런타임 추출, 포트/env/volume/의존 분석
- Step 5~7: bounded semantic agent, 도구 예산, verifier, OpenAI-compatible provider 경로
- Step 8~10: Reconciliation, Profile merge, unresolved 질문 생성
- Step 11: Deployment, Service, ServiceAccount, ConfigMap, Secret placeholder, Ingress 템플릿 렌더링
- Step 12: YAML syntax, internal manifest checks, project-managed kubeconform 검증 체인
- Agent MVP: prepare/resume/status/explain/export와 단계별 analyze/plan/generate/validate 명령, 10개 fixture acceptance matrix, reproducible manifest bundle 검증

이 프로젝트는 아직 한 번의 명령으로 운영 클러스터에 배포하는 도구가 아닙니다. 확인할 수 없는 값은 자동으로 꾸며내지 않고 질문이나 unresolved 항목으로 남깁니다.

## Development

테스트 실행:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

상세 문서:

- [docs/pipeline-details.md](./docs/pipeline-details.md): 기능별 세부 규칙
- [docs/architecture.md](./docs/architecture.md): 구현 상태와 아키텍처 경계
- [docs/testing/agent-mvp-test-matrix.md](./docs/testing/agent-mvp-test-matrix.md): Agent MVP fixture matrix와 CI 검증 명령
- [onprem-llm-k8s-manifest-preanalysis-workflow.md](./onprem-llm-k8s-manifest-preanalysis-workflow.md): 전체 워크플로우 설계

## Project structure

```text
src/k8s_agent/      # Agent MVP CLI, run state, questions, profile, render, validation
src/preanalyzer/    # analyzer(scanner/parsers/evidence/rule) + models + pipeline
tests/              # unit, acceptance, fixtures/repos
docs/               # architecture, pipeline details, ADR, task docs
scripts/            # repo maintenance and kubeconform setup helpers
```
