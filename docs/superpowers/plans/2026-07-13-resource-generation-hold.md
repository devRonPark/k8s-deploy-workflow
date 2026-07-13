# Resource Generation Hold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Track task status with checkbox (`- [ ]`) syntax. Within each task, follow Red -> Green -> Refactor.

**Goal:** Stop generating invalid Kubernetes resources when required values are unresolved, and report those resources to operators as `생성 보류`.

**Architecture:** Extend the existing renderer-level `DeferredResource` concept into a structured generation hold that can be reported to users. The renderer decides whether a resource can be safely written; the pipeline carries generation holds into `13-validation-report.yaml`; profile merge can later resolve held service-port cases without LLM guessing.

**Tech Stack:** Python 3.11+, Pydantic v2, `unittest`, existing `TemplateRenderer`, `ValidationPipeline`, `DeploymentProfile`, and numbered pipeline artifacts.

## Global Constraints

- Use `unittest`; do not introduce new dependencies.
- Do not ask the LLM to pick operational values.
- Do not automatically choose one candidate port.
- Do not expose `deferred` as the main user-facing term; use `생성 보류` in reports and documentation.
- Kubeconform must validate only YAML files that were actually generated.
- Held resources must not count as Kubernetes schema validation failures.
- Generated invalid YAML must still be reported as validation failure.
- Do not treat a partially generated manifest set as production deploy-ready.
- Keep Secret values out of logs, evidence, LLM input, fixtures, and generated artifacts.
- Before sample repository validation or completion claims involving generated manifests, run `python3 scripts/ensure_kubeconform.py --check`.

---

## File Structure

- Modify `src/preanalyzer/renderer/engine.py`
  - Owns resource renderability checks and creates structured generation-hold entries.
- Modify `src/preanalyzer/models/report.py`
  - Adds serializable generation-hold models under `ValidationReport`.
- Modify `src/preanalyzer/validator/pipeline.py`
  - Accepts generation holds and preserves them in validation reports without treating them as kubeconform failures.
- Modify `src/preanalyzer/pipeline.py`
  - Passes renderer holds into validation, enriches holds from unresolved questions where available, and writes stable YAML.
- Modify `src/preanalyzer/models/profile.py`
  - Adds the smallest component-level service-port override model needed to resolve held Ingress resources.
- Modify `src/preanalyzer/reconciliation/profile_merge.py`
  - Applies component service-port overrides to `KubernetesIntent`.
- Modify `tests/unit/test_renderer.py`
  - Covers Ingress generation hold and valid Ingress rendering.
- Modify `tests/unit/test_validator.py`
  - Covers validation report serialization with generation holds.
- Modify `tests/unit/test_profile_merge.py`
  - Covers profile service-port override and question satisfaction.
- Modify `tests/acceptance/test_demo_repos.py`
  - Covers `port-conflict-node` and `jpetstore-like` no longer rendering invalid Ingress YAML.
- Modify `README.md`
  - Adds operator-facing explanation of `생성 보류` in the output inspection guidance.

---

## Task 1: Renderer Holds Unsafe Ingress Resources

**목표:** Ingress에 필요한 service port가 확정되지 않으면 Ingress YAML을 쓰지 않고 구조화된 `생성 보류` 항목을 만든다.

**변경 범위:** `TemplateRenderer`와 renderer unit tests만 다룬다. Report 모델, pipeline, profile schema는 이 태스크에서 건드리지 않는다.

**완료 조건:**

- `component.ingress.host`가 있어도 service port가 `None`이면 `<component>/ingress.yaml`이 생성되지 않는다.
- renderer result에 `status="generation_held"`, `display_status="생성 보류"`, `resource.kind="Ingress"`, `reason.code="unresolved_service_port"`가 남는다.
- service port가 concrete integer이면 기존처럼 Ingress YAML이 생성된다.
- 렌더된 파일 어디에도 `number: None` 또는 `number: "None"`이 없다.

**실행할 테스트 범위:**

- 개발 중: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_renderer.RendererTests -v`
- 태스크 완료: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_renderer -v`

**전체 테스트 필요 여부:** 필요 없음. renderer 단위 정책만 변경하며 pipeline/report 연결은 아직 변경하지 않는다.

**Red -> Green -> Refactor:**

- Red: `tests/unit/test_renderer.py`에 실패 테스트를 추가한다.
  - `test_holds_ingress_without_service_port`
  - `test_renders_ingress_with_service_port`
  - `test_rendered_yaml_never_contains_none_service_port`
- Green: `src/preanalyzer/renderer/engine.py`에서 기존 `DeferredResource`를 유지하거나 확장해 `GenerationHold` 형태의 dataclass를 추가한다. 기존 `RenderResult.deferred` 필드는 호환을 위해 유지하되, 새 코드에서는 `RenderResult.generation_holds`를 주 필드로 쓴다.
- Refactor: 중복된 hold 생성 로직을 `_hold_ingress(...)` 같은 작은 helper로 정리하되, 템플릿 렌더링 흐름 전체를 재구조화하지 않는다.

**구현 메모:**

- `TemplateRenderer.render(...)`의 Ingress 블록은 현재 `service_port=port`로 workload port를 넘긴다. 우선순위는 `component.service.port.value`가 있으면 service port를 쓰고, 없으면 workload port를 fallback으로 쓴다. 둘 다 없으면 Ingress를 생성 보류한다.
- 생성 보류는 optional feature 미요청과 구분한다. `component.ingress` 또는 `component.ingress.host`가 없으면 hold가 아니라 미생성이다.
- 기존 dependency component의 `role_dependency_no_workload`는 이번 태스크의 핵심이 아니므로 표현을 바꾸지 않는다.

---

## Task 2: Validation Report Shows Generation Holds

**목표:** `13-validation-report.yaml`에 생성 보류 리소스를 사용자-facing 상태 `생성 보류`로 기록하고, kubeconform 실패와 구분한다.

**변경 범위:** report 모델, validator report 반환, pipeline의 renderer 결과 전달까지 포함한다. Profile override는 포함하지 않는다.

**완료 조건:**

- `ValidationReport`가 `generation_holds` 목록을 직렬화한다.
- `ValidationPipeline.run(...)`은 `generation_holds` 인자를 받아 report에 보존한다.
- generation hold가 있어도 kubeconform stage status를 `fail`로 바꾸지 않는다.
- `run_analysis(...)` 출력의 `13-validation-report.yaml`에 `generation_holds`가 포함된다.
- `05-reconciliation-report.yaml`의 기존 `deferred` 정보는 깨지지 않거나, 새 `generation_holds`와 일관된 값으로 유지된다.

**실행할 테스트 범위:**

- 개발 중: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator.ValidatorTests -v`
- 태스크 완료: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator tests.unit.test_pipeline_full_outputs -v`

**전체 테스트 필요 여부:** 필요 없음. report/pipeline 인접 테스트로 충분하다. 전체 테스트는 Task 4에서 실행한다.

**Red -> Green -> Refactor:**

- Red: `tests/unit/test_validator.py`에 `test_generation_holds_are_reported_without_failing_kubeconform`를 추가한다. Mock kubeconform pass 상황에서 `report.generation_holds[0].display_status == "생성 보류"`를 확인한다.
- Red: `tests/unit/test_pipeline_full_outputs.py`에 Ingress 생성 보류가 `13-validation-report.yaml`에 쓰이는지 확인하는 focused test를 추가한다. 기존 fixture를 쓰되 새 test가 너무 크면 renderer result를 직접 pipeline 하위 함수로 검증하지 말고 `run_analysis(...)`를 사용한다.
- Green: `src/preanalyzer/models/report.py`에 Pydantic 모델을 추가한다.
  - `GenerationHoldCandidate`
  - `GenerationHoldReason`
  - `GenerationHoldResource`
  - `GenerationHoldResolution`
  - `GenerationHold`
  - `ValidationReport.generation_holds: list[GenerationHold]`
- Green: `src/preanalyzer/validator/pipeline.py`의 `run(...)`에 `generation_holds: list[GenerationHold] | None = None`을 추가하고 반환 report에 넣는다.
- Green: `src/preanalyzer/pipeline.py`에서 `TemplateRenderer(...).render(intent)`의 generation holds를 `ValidationPipeline().run(...)`으로 전달한다.
- Refactor: renderer dataclass -> report model 변환은 `pipeline.py`에 한정한다. validator가 renderer dataclass를 import하지 않게 유지한다.

**구현 메모:**

- `ValidationReport`는 Pydantic 모델이므로 renderer dataclass 대신 `model_validate(...)` 가능한 dict를 전달해도 된다.
- `generation_holds`는 validation stage가 아니다. stages에는 기존 `yaml_syntax`, `kubeconform`, `dry_run`만 남기고, 생성 보류는 별도 최상위 필드로 둔다.
- `achieved_level`은 이번 태스크에서 억지로 낮추지 않는다. 단, report에 generation holds가 있으면 사용자는 전체 deploy-ready가 아니라는 신호를 볼 수 있어야 한다. achieved level 정책 조정은 Task 4 검증 결과에 따라 필요한 최소 변경만 한다.

---

## Task 3: Profile Can Resolve Component Service Port Holds

**목표:** 운영자가 deployment profile에 component별 service port를 명시해 생성 보류된 Ingress를 해소할 수 있게 한다.

**변경 범위:** DeploymentProfile schema와 profile merge 정책, 관련 unit tests만 포함한다. Renderer나 validator 정책은 Task 1~2 결과를 사용한다.

**완료 조건:**

- profile이 다음 형태를 허용한다.

```yaml
components:
  web:
    service:
      port: 8081
```

- `merge(...)`가 `components.<id>.service.port`를 해당 component의 `ServiceIntent.port`와 workload port fallback에 반영한다.
- 해당 profile field가 unresolved port question을 만족시켜 질문 목록에서 제거된다.
- unknown component id는 조용히 무시하지 않고 profile validation 또는 merge에서 명확히 실패한다.

**실행할 테스트 범위:**

- 개발 중: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_profile_merge.ProfileMergeTests -v`
- 태스크 완료: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_profile_merge tests.unit.test_intermediate_models -v`

**전체 테스트 필요 여부:** 필요 없음. profile schema와 merge 정책의 변경이며 관련 unit tests로 범위가 닫힌다.

**Red -> Green -> Refactor:**

- Red: `tests/unit/test_profile_merge.py`에 `test_component_service_port_profile_resolves_port_question`를 추가한다. port conflict를 가진 reconciliation result를 만들고 profile override 후 `ServiceIntent.port.value == 8081`과 port question 제거를 확인한다.
- Red: `tests/unit/test_profile_merge.py`에 `test_component_service_port_unknown_component_rejected`를 추가한다.
- Green: `src/preanalyzer/models/profile.py`에 `ComponentProfile`과 `ComponentServiceProfile` Pydantic 모델을 추가한다.
- Green: `src/preanalyzer/reconciliation/profile_merge.py`에서 component override를 적용한다.
- Refactor: 기존 top-level `registry`, `namespace`, `ingress_host`, `image_tag` 동작은 그대로 유지한다. component profile은 service port 해소에만 사용한다.

**구현 메모:**

- `Tracked[int]` source는 `deployment_profile`, confidence는 `HIGH`, evidence_refs는 빈 목록으로 둔다.
- 기존 질문의 `profile_field`가 `port`처럼 일반 이름이면 component profile path와 바로 매칭되지 않을 수 있다. 이 경우 질문 제거 로직은 `answer_type == "port"`와 component id를 함께 확인하는 작은 helper로 구현한다.
- unknown component id 검증은 profile model만으로는 intent component 목록을 알 수 없으므로 `merge(...)`에서 `ValueError("unknown deployment profile component: <id>")`를 내는 방식이 적절하다.

---

## Task 4: Sample Repositories Report Holds Instead Of Invalid Ingress YAML

**목표:** 현재 발견된 `jpetstore-like`, `port-conflict-node` 엣지 케이스가 깨진 Ingress YAML 대신 `생성 보류`로 끝나는지 end-to-end로 검증한다.

**변경 범위:** acceptance tests, README output guidance, 필요하면 achieved level/report wording의 작은 조정까지 포함한다.

**완료 조건:**

- `port-conflict-node`는 port 질문을 유지하고 Ingress YAML을 생성 보류한다.
- `jpetstore-like`는 필요한 service port가 없으면 Ingress YAML을 생성 보류한다.
- 두 fixture의 generated manifests에 `number: None`, `number: "None"`, `__UNRESOLVED__`가 없다.
- kubeconform이 skipped가 아닌 환경에서는 두 fixture가 `"None"` port 때문에 fail하지 않는다.
- README가 `13-validation-report.yaml`의 `generation_holds`와 `생성 보류` 의미를 짧게 설명한다.

**실행할 테스트 범위:**

- 개발 중: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_demo_repos.PortConflictTests tests.acceptance.test_demo_repos.DemoSpectrumTests -v`
- 태스크 완료:
  - `python3 scripts/ensure_kubeconform.py --check`
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_demo_repos -v`
  - 5개 fixture repo sample validation command 또는 동등한 one-off `run_analysis(...)` loop

**전체 테스트 필요 여부:** 필요함. 이 태스크는 renderer, report, profile, pipeline, acceptance를 모두 통과한 기능 묶음의 마지막 검증이므로 전체 suite를 실행한다. 실행 전 사용자에게 “기능 묶음 완료 검증이라 전체 테스트를 실행한다”고 짧게 알린다.

**Red -> Green -> Refactor:**

- Red: `tests/acceptance/test_demo_repos.py`의 `PortConflictTests`에 generation hold와 no invalid YAML assertions를 추가한다.
- Red: `DemoSpectrumTests.test_jpetstore_no_dockerfile_defers_and_flags_build` 또는 새 test에서 `jpetstore-like`의 `13-validation-report.yaml` generation hold와 no invalid YAML assertions를 추가한다.
- Green: Task 1~3 후에도 실패하는 acceptance gap만 최소 수정한다. 예를 들어 `run_analysis(...)`가 report에 hold candidates를 넣지 못하면 `pipeline.py`에서 unresolved questions를 이용해 candidates를 보강한다.
- Green: `README.md`의 “What to inspect first” 또는 validation report 설명에 `generation_holds`와 `생성 보류` 의미를 추가한다.
- Refactor: sample validation helper가 필요하면 test 내부 private helper로만 둔다. 운영 코드에 sample 전용 로직을 넣지 않는다.

**구현 메모:**

- Candidate values는 `10-unresolved-questions.yaml`의 port question candidates를 우선 사용한다. renderer가 후보를 모르면 빈 후보 목록이어도 되지만, acceptance에서는 `port-conflict-node`가 `8080`, `8081` 후보를 report에 보여주는지 확인한다.
- `jpetstore-like`는 후보가 없을 수 있다. 이 경우 reason과 suggested resolution이 충분하면 된다.
- kubeconform schema fetch가 sandbox/network로 실패하면 승인 요청 후 재실행한다. `kubeconform: skipped`는 완료로 보고하지 않는다.

---

## Final Verification And Commit Guidance

기능 묶음 완료 후 실행한다. 전체 테스트는 renderer/report/profile/pipeline/acceptance를 모두 건드리는 변경이므로 필요하다.

```bash
git status --short
git diff --check
python3 scripts/ensure_kubeconform.py --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
python3 scripts/validate_context_paths.py .
```

5개 샘플 저장소 검증도 별도로 수행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp

import yaml

from preanalyzer.pipeline import run_analysis

repos = [
    "fastapi-fullstack-like",
    "fastapi-shell-entrypoint",
    "jpetstore-like",
    "node-express-like",
    "port-conflict-node",
]
profile = Path("tests/fixtures/profiles/dev-profile.yaml")
root = Path(mkdtemp(prefix="generation-hold-sample-repos-"))
clock = lambda: datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
for name in repos:
    out = root / name
    report = run_analysis(
        Path("tests/fixtures/repos") / name,
        out,
        url=None,
        ref="main-fixture",
        clock=clock,
        semantic_mode="disabled",
        profile_path=profile,
    )
    data = yaml.safe_load((out / "13-validation-report.yaml").read_text(encoding="utf-8"))
    kubeconform = next(s for s in data["validation_report"]["stages"] if s["stage"] == "kubeconform")
    print(name, "level=", report.achieved_level, "kubeconform=", kubeconform["status"], "holds=", len(data["validation_report"].get("generation_holds", [])))
print("output_root=", root)
PY
```

Expected:

- `kubeconform` is not `skipped`.
- `jpetstore-like` and `port-conflict-node` have generation holds for Ingress instead of invalid `"None"` port YAML.
- Real generated YAML failures, if any remain, are still reported as validation failures.

Commit strategy:

- Commit after each task if verification for that task passes.
- Suggested commit messages:
  - `feat: hold ingress generation when service port unresolved`
  - `feat: report held resources in validation output`
  - `feat: allow profile service port overrides`
  - `test: cover generation holds in sample repos`

---

## Self-Review

- Spec coverage: Renderer hold, user-facing `생성 보류`, validation report placement, profile resolution, current sample regressions, kubeconform behavior, and README wording are each covered by Tasks 1-4.
- Placeholder scan: This plan intentionally contains no placeholder markers or unspecified implementation slots.
- Type consistency: The plan consistently uses `generation_holds` for report output, `GenerationHold` for serializable report models, and `생성 보류` for user-facing display.
