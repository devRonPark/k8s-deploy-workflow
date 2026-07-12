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

전체는 Step 0~15. **Step 0~6 (결정론 사전분석, "Phase 1")까지 완료**.
탐지 대상 예: `Dockerfile`·`compose`·`package.json`·`pom.xml`·`pyproject.toml`.

- Step 0~6 ✅ — snapshot / artifact inventory / 배포파일 파싱 / component 탐지 / 언어·빌드 탐지 / 런타임 추출 / 포트·env·volume·의존 분석
- Step 7~15 ⬜ — Application Topology → Kubernetes Intent → 템플릿 렌더링 → 검증 → 배포 → 스모크 → 리페어

Phase 1 체인 (저장소에서 바로 YAML로 가는 지름길은 없다 — 각 단계가 `00~03-*.yaml`로 남는다):

```text
repository_snapshot → artifact_inventory → evidence_model → rule_inference
```

Semantic agent는 도메인 모델·읽기 도구·예산 추적·검증기 + **bounded agent 상태기계**와
**OpenAI 호환 온프렘 LLM provider**까지 배선됨 (phase1 파이프라인에 통합).
Topology/Intent 모델·매니페스트 생성·배포·검증은 아직 미구현.

## 개발 환경 설정

시스템 Python에 `pip`이 없을 수 있어 프로젝트 전용 가상환경을 쓴다.

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python3 "pydantic>=2.8" "PyYAML>=6.0"
```

`uv`가 없으면 표준 `venv` + `pip install -e .`로 대체.

## 테스트 실행

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

`tests/fixtures/repos/` 아래 샘플 레포 3종(`jpetstore-like`, `fastapi-fullstack-like`, `node-express-like`)이 end-to-end 검증에 쓰인다.

## Phase 1 직접 실행

```python
from datetime import datetime, timezone
from pathlib import Path
from preanalyzer.pipeline import run_phase1_analysis

run_phase1_analysis(
    repo=Path("./my-repo"), output_dir=Path("./out"),
    url="https://github.com/example/my-repo", ref="main",
    clock=lambda: datetime.now(timezone.utc),
)
```

`./out/`에 `00-repository-snapshot.yaml` ~ `03-rule-inference.yaml` 4개가 생성된다.

Snapshot 모드·Compose·Component ownership·Semantic budget·**Semantic LLM provider**(온프렘 OpenAI 호환 연동) 등 세부는 [docs/pipeline-details.md](./docs/pipeline-details.md) 참고.

## 프로젝트 구조

오케스트레이션은 `src/preanalyzer/pipeline.py`, 모듈 상세는 각 디렉터리 CLAUDE.md 참고.

```text
src/preanalyzer/    # analyzer(scanner/parsers/evidence/rule) + models + pipeline
tests/              # unit · acceptance · fixtures/repos
docs/               # architecture.md, pipeline-details.md, adr, tasks
```

> 주의: designed 상태와 implemented 상태를 혼동하지 말 것. 코드 쪽 진실은
> [docs/architecture.md](./docs/architecture.md) §2의 구현 상태 마커다.
