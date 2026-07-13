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

Kubernetes schema 검증을 위해 프로젝트가 관리하는 `kubeconform` 바이너리를 확인합니다.

```bash
python3 scripts/ensure_kubeconform.py --check
```

먼저 포함된 샘플 저장소를 LLM 없이 분석해 봅니다.

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --no-llm \
  --out out/node-express-like
```

명령은 `achieved_level=<level> out=out/node-express-like` 형식의 요약을 출력하고, `out/node-express-like/` 아래에 분석 산출물을 씁니다.

## Run on your repository

샘플 실행 후에는 자신의 저장소 경로를 넘겨 실행합니다.

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  ./my-repo \
  --no-llm \
  --out out/my-repo
```

namespace, registry, image tag, ingress host처럼 환경마다 달라지는 값을 제공하려면 deployment profile을 작성해 `--profile`로 전달합니다.

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  ./my-repo \
  --profile path/to/profile \
  --no-llm \
  --out out/my-repo
```

## Optional LLM integration

LLM은 필수가 아닙니다. 다만 OpenAI-compatible endpoint를 연결하면 제한된 semantic task에서 런타임 명령 같은 애매한 값을 보강하는 데 사용할 수 있습니다. LLM은 최종 Kubernetes YAML을 자유 생성하지 않으며, 전체 저장소를 컨텍스트로 받지 않습니다.

환경변수를 설정합니다.

```bash
export SEMANTIC_LLM_BASE_URL="https://your-llm.example/v1"
export SEMANTIC_LLM_MODEL="your-model"
export SEMANTIC_LLM_API_KEY="your-key"
export SEMANTIC_LLM_TIMEOUT_SECONDS="30"
```

실제 모델 ID를 추측하지 말고 endpoint에서 먼저 확인합니다.

```bash
curl "$SEMANTIC_LLM_BASE_URL/models"
```

반환된 모델 ID를 `SEMANTIC_LLM_MODEL`에 넣습니다. 실제 API key, token, password는 커밋하지 마세요.

인증이 없는 로컬 OpenAI-compatible endpoint를 쓰는 경우에도 현재 설정 로더는 `SEMANTIC_LLM_API_KEY`가 비어 있으면 거부합니다. 이런 endpoint가 placeholder key를 허용한다면 비밀값이 아닌 값을 사용합니다.

```bash
export SEMANTIC_LLM_API_KEY="none"
```

LLM 연동 실행 예시는 다음과 같습니다.

```bash
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  tests/fixtures/repos/node-express-like \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --semantic-mode openai_compatible \
  --out out/node-express-like-llm
```

## What to inspect first

처음에는 모든 번호 파일을 다 읽기보다 아래 산출물부터 확인하세요.

- `06-component-model.yaml`: 감지된 배포 단위와 component 경계
- `10-unresolved-questions.yaml`: 도구가 안전하게 결정하지 못한 값
- `11-deployment-profile.yaml`: 실행에 사용된 deployment profile 값. profile을 주지 않으면 `null`
- `12-generated-manifests/`: Intent Model과 템플릿에서 렌더링된 Kubernetes 리소스 파일
- `13-validation-report.yaml`: YAML, kubeconform, kubectl dry-run 검증 결과. `generation_holds`는 안전하게 만들 수 없어 `생성 보류`된 리소스와 필요한 해소 값을 보여줍니다.

전체 파이프라인은 `00-repository-snapshot.yaml`부터 `15-smoke-test-plan.yaml`까지의 산출물을 만들 수 있습니다.

`13-validation-report.yaml`에 `kubeconform: skipped`가 기록되어 있으면 Kubernetes schema 검증이 완료된 것이 아닙니다. 이 경우 `python3 scripts/ensure_kubeconform.py --check`를 먼저 확인하세요.

## Current status and limitations

현재 코드는 Step 12까지 MVP 흐름이 연결되어 있습니다. "분석 → Intent → 템플릿 렌더링 → 검증 리포트"가 샘플 저장소 기준으로 관통합니다.

- Step 0~6: snapshot, artifact inventory, 배포파일 파싱, component 탐지, 언어/빌드 탐지, 런타임 추출, 포트/env/volume/의존 분석
- Step 5~7: bounded semantic agent, 도구 예산, verifier, OpenAI-compatible provider 경로
- Step 8~10: Reconciliation, Profile merge, unresolved 질문 생성
- Step 11: Deployment, Service, ServiceAccount, ConfigMap, Secret placeholder, Ingress 템플릿 렌더링
- Step 12: YAML syntax, project-managed kubeconform, kubectl dry-run 검증 체인
- Step 13~15: Deployment Check, Smoke Test 실행, Repair Loop 자동화는 아직 미구현. 현재는 checklist와 smoke-test-plan 초안 생성 수준

이 프로젝트는 아직 한 번의 명령으로 운영 클러스터에 배포하는 도구가 아닙니다. 확인할 수 없는 값은 자동으로 꾸며내지 않고 질문이나 unresolved 항목으로 남깁니다.

## Development

테스트 실행:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

상세 문서:

- [docs/pipeline-details.md](./docs/pipeline-details.md): 기능별 세부 규칙
- [docs/architecture.md](./docs/architecture.md): 구현 상태와 아키텍처 경계
- [onprem-llm-k8s-manifest-preanalysis-workflow.md](./onprem-llm-k8s-manifest-preanalysis-workflow.md): 전체 워크플로우 설계

## Project structure

```text
src/preanalyzer/    # analyzer(scanner/parsers/evidence/rule) + models + pipeline
tests/              # unit, acceptance, fixtures/repos
docs/               # architecture, pipeline details, ADR, task docs
scripts/            # repo maintenance and kubeconform setup helpers
```
