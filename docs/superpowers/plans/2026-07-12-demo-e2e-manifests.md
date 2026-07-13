# Demo End-to-End Manifest Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **진행 상황 (2026-07-13 기준):** Task 1–4 구현 완료(커밋 존재, 관련 유닛 19개 green). Task 3만 반쪽 — accepted-command 추출 로직·배선은 됐으나 신규 유닛테스트 `test_extracts_accepted_command_from_run`가 커밋(76768f7) 이후 플랜에 추가돼 아직 미반영. **다음 착수: Task 3 테스트 보완 → Task 5(렌더러).** Task 5–11 미착수.
>
> | Task | 상태 | 커밋 |
> |------|:--:|------|
> | 1 중간모델(06–11,13) | ✅ | 830e1f2, a98a0d7, c659119 |
> | 2 리컨실 엔진 | ✅ | 0500f15 (+c549d39, 3e53af7) |
> | 3 accepted command 배선 | ⚠️ 테스트 보완 필요 | 76768f7 |
> | 4 profile merge | ✅ | 42b7fe9 |
> | 5 렌더러 · 6 validator · 7 오케스트레이터 · 8 CLI · 9–11 픽스처/데모 | ❌ 미착수 | — |

**Goal:** Extend the Phase-1 pipeline past `04-semantic-analysis.yaml` so a repository becomes reconciled intermediate models (05–09), unresolved questions (10), a rendered Kubernetes manifest tree (12), and a validation report (13) reaching `achieved_level: 1` on kubeconform — driven by a new CLI, demonstrated across 5 sample repos and a live on-prem LLM.

**Architecture:** Deterministic `rule_inference` candidates (+ any verifier-accepted semantic runtime command) are promoted by a minimal Reconciliation Engine into `KubernetesIntent`; operational values (registry/namespace/host/db-host) and detected conflicts become `UnresolvedQuestions` instead of guesses; a `DeploymentProfile` merge fills those with `user_decision`; a Jinja2 `TemplateRenderer` emits manifests (deferring resources with unresolved required fields); a `ValidationPipeline` runs yaml→kubeconform→dry-run and assigns the level. The LLM stays scoped to the existing bounded runtime-command agent; its accepted command is the only LLM value that flows into a manifest.

**Tech Stack:** Python 3.11+, pydantic v2, Jinja2 (new dep), PyYAML, argparse, unittest. External binaries: `kubeconform` (required in demo/CI env), `kubectl` (optional). Existing bounded semantic agent + `OpenAIChatDecisionProvider` for live LLM.

## Global Constraints

- **P2 Intermediate model before YAML** — snapshot→inventory→evidence→rule_inference/semantic→reconciliation→component→runtime→dependency→intent→render→validate. No repository→YAML shortcut.
- **P3 Template rendering only** — the only manifest source is `TemplateRenderer`. No LLM free-form YAML.
- **P5 Ask instead of guess** — unconfirmable values become `UnresolvedQuestion`, never silent defaults.
- **P6 Tracked fields** — extracted/interpreted leaf values carry `value / source / confidence(high|medium|low|none) / evidence_refs`. The real `Tracked` (`src/preanalyzer/models/fields.py`) has exactly those four fields; `classification` lives as a sibling `str` field where needed (matching the `rule_inference` candidate dataclasses).
- **P9 Secret safety** — secret VALUES never enter models, manifests, logs, or prompts. Only name/source/evidence. Secret placeholder value is the literal `__REPLACE_ME__`.
- **P10 Reproducibility** — fixed clock + NullProvider ⇒ byte-identical `00`–`13`. Sort every list by a stable key before serialization.
- **LLM scope** — the semantic agent handles runtime-command gaps ONLY. Do not build role/boundary/dependency semantic tasks (roadmap). An LLM candidate never overrides a high-confidence deterministic candidate.
- **MVP languages** — Java(Maven), Node(npm), Python(pip/poetry). No Go/.NET.
- **Rendered value provenance** — every value in a manifest must come from Intent, Profile, or a template constant. The renderer invents nothing.
- **Unresolved placeholders** — `__UNRESOLVED__` in manifests (only under `allow_placeholders`), `__REPLACE_ME__` for secret values.
- **Determinism/clock** — `analyzed_at` and any timestamp come from the injected `clock`. Tests inject a fixed clock.
- **Verify command:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v` and `python3 scripts/validate_context_paths.py .`

## Test Execution Strategy (per-task)

각 태스크 헤더에 `실행할 테스트 범위` / `전체 테스트 필요` 라벨을 둔다. 규칙:
1. 개발 중에는 그 태스크의 새 테스트 파일만 실행한다.
2. 태스크 완료 시 관련 테스트 파일(+직접 영향받는 인접 테스트)만 실행한다.
3. 전체 `discover`는 기능 묶음 완료·커밋 전·영향범위가 넓을 때만 — 이 플랜에서는 **Task 11 한 번**. 이유는 그 태스크에 명시한다.
4. 코드 변경 없는 문서/픽스처 정리 작업은 전체 테스트를 돌리지 않는다.

---

## File Structure (decomposition lock-in)

New files, one responsibility each:

```text
src/preanalyzer/models/component.py      # 06 ComponentModel/ComponentEntry
src/preanalyzer/models/runtime.py        # 07 RuntimeModel/RuntimeEntry
src/preanalyzer/models/dependency.py     # 08 DependencyModel/DependencyEdge/EnvBinding
src/preanalyzer/models/intent.py         # 09 KubernetesIntent/ComponentIntent/Workload/ServiceIntent/IngressIntent
src/preanalyzer/models/questions.py      # 10 UnresolvedQuestions/UnresolvedQuestion
src/preanalyzer/models/profile.py        # 11 DeploymentProfile
src/preanalyzer/models/report.py         # 13 ValidationReport/StageResult
src/preanalyzer/reconciliation/__init__.py
src/preanalyzer/reconciliation/engine.py         # rules(+accepted cmd) -> ReconciliationResult
src/preanalyzer/reconciliation/profile_merge.py  # profile validate + merge into intent
src/preanalyzer/renderer/__init__.py
src/preanalyzer/renderer/policy.py       # per-resource required fields + missing action + label/annotation sets
src/preanalyzer/renderer/engine.py       # TemplateRenderer.render
src/preanalyzer/renderer/templates/*.j2  # deployment/service/configmap/secret.placeholder/serviceaccount/ingress
src/preanalyzer/validator/__init__.py
src/preanalyzer/validator/pipeline.py    # yaml_check -> kubeconform -> dry_run, level determination
src/preanalyzer/cli.py                   # argparse: analyze
tests/fixtures/profiles/dev-profile.yaml
tests/fixtures/repos/fastapi-shell-entrypoint/...   # #3
tests/fixtures/repos/port-conflict-node/...         # #5
tests/unit/test_intermediate_models.py
tests/unit/test_reconciliation.py
tests/unit/test_semantic_command_wiring.py
tests/unit/test_profile_merge.py
tests/unit/test_renderer.py
tests/unit/test_validator.py
tests/unit/test_cli.py
tests/acceptance/test_demo_repos.py
```

Modified:

```text
src/preanalyzer/pipeline.py   # collect accepted semantic commands; write 05-15
pyproject.toml                # add jinja2 dependency
```

Existing types consumed (verbatim signatures):

```python
# src/preanalyzer/models/fields.py
@dataclass(frozen=True, config=ConfigDict(use_enum_values=True))
class Tracked(Generic[T]):
    value: T | None = None
    source: str | None = None
    confidence: Confidence = Confidence.NONE   # HIGH/MEDIUM/LOW/NONE, str-valued
    evidence_refs: list[str] = field(default_factory=list)

# src/preanalyzer/models/rule_inference.py  (all frozen pydantic dataclasses)
ComponentCandidate(component_id, root_path, source, evidence_refs, classification="rule_inference")
RoleCandidate(component_id, role, source, confidence, evidence_refs, classification="rule_inference")
RuntimeCandidate(component_id, language, framework, build_tool, build_strategy, source, confidence, evidence_refs, ...)
RuntimePortCandidate(component_id, port:int, source, confidence, evidence_refs, ...)
RuntimeCommandCandidate(component_id, command, source, confidence, evidence_refs, ...)
DependencyEdgeCandidate(source_component, target, dependency_type, source, confidence, evidence_refs, ...)
SecretCandidate(component_id, name, source, evidence_refs, ...)
EnvClassification(secret_candidates: list[SecretCandidate])
class RuleInferenceSet(BaseModel):  # lists of the above + env_classification

# src/preanalyzer/pipeline.py
run_phase1_analysis(repo, output_dir, url, ref, clock, mode="workspace",
    semantic_mode="disabled", semantic_decision_provider=None, semantic_model=None,
    semantic_task_max_tool_calls=None) -> (RepositorySnapshot, ArtifactInventory, EvidenceModel, RuleInferenceSet)
# currently writes 00-04 only. _write_yaml(path, dict) sorts keys + dumps.

# src/preanalyzer/models/snapshot.py RepositorySnapshot: commit_sha, analyzer_version, rules_version, analyzed_at, ...
# src/preanalyzer/rules_version.py: RULES_VERSION (str)
```

**Conflict handling note (#5):** `RuleInferenceSet` has NO `conflicts` field. A port conflict = two `RuntimePortCandidate` with the same `component_id` and different `port`. Reconciliation DETECTS this (group by component_id) and, when >1 distinct port, emits an `UnresolvedQuestion` (answer_type `port`) with both ports as `candidates` instead of picking one.

**Accepted semantic command note (#3):** The `04` audit dict only carries candidate IDs, not the command string. Task 3 changes `pipeline._build_semantic_analysis_audit` to ALSO return `list[AcceptedSemanticCommand]` (component_id, command, evidence_refs) extracted from runs whose `verification_result.status == "accepted"`, reading `result.resolution.candidates[*].value["command"]` for the recommended candidate.

---

## Task 1: Intermediate data models (06–11, 13)

> **✅ 구현 완료** — 커밋 830e1f2/a98a0d7/c659119. 7개 모델 파일 존재, `test_intermediate_models` green. (커밋 시점엔 3개 태스크로 분리돼 있었음 — 현재 플랜은 병합본, 기능 동일.)

**목표:** 06–13 파이프라인이 주고받는 pydantic 데이터 계약을 하나로 확정 (component/runtime/dependency/intent/questions/profile/report).
**변경 범위:** `models/{component,runtime,dependency,intent,questions,profile,report}.py` 생성 + `tests/unit/test_intermediate_models.py`.
**완료 조건:** 스키마 왕복 + `DeploymentProfile` extra=forbid 거부 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_intermediate_models` (이 파일만).
**전체 테스트 필요:** 불필요 — 소비자 없는 순수 모델. 실동작 검증은 Task 2(리컨실)/Task 5(렌더러)가 담당.

> **분해 근거:** 개별 모델 파일은 그 자체로 사용자/기술 결과를 완성하지 않는(왕복 테스트뿐) 스캐폴딩이라 하나로 묶는다. 07개 파일 모두 pydantic 모델·같은 테스트 파일·같은 컨텍스트를 공유한다.

**Files:**
- Create: `src/preanalyzer/models/component.py`, `runtime.py`, `dependency.py`, `intent.py`, `questions.py`, `profile.py`, `report.py`
- Test: `tests/unit/test_intermediate_models.py`

**Interfaces:**
- Consumes: `Tracked`, `Confidence` from `models/fields.py`.
- Produces:
  ```python
  # component.py
  class ComponentEntry(BaseModel): component_id:str; role:Tracked[str]; root_path:str|None=None
  class ComponentModel(BaseModel): components:list[ComponentEntry]=[]
  # runtime.py
  class RuntimeEntry(BaseModel):
      component_id:str; language:Tracked[str]; framework:Tracked[str]|None=None
      build_strategy:str; port:Tracked[int]|None=None; command:Tracked[str]|None=None
  class RuntimeModel(BaseModel): runtimes:list[RuntimeEntry]=[]
  # dependency.py
  class DependencyEdge(BaseModel): source_component:str; target:str; dependency_type:str; confidence:Tracked[str]
  class EnvBinding(BaseModel): component_id:str; name:str; kind:str  # "configmap"|"secret"
  class DependencyModel(BaseModel): edges:list[DependencyEdge]=[]; env_bindings:list[EnvBinding]=[]
  # intent.py
  class Workload(BaseModel):
      image_name:Tracked[str]|None=None; image_registry:Tracked[str]|None=None
      image_tag:Tracked[str]|None=None; port:Tracked[int]|None=None; command:Tracked[str]|None=None
      config_env:list[str]=[]; secret_env:list[str]=[]
  class ServiceIntent(BaseModel): port:Tracked[int]|None=None
  class IngressIntent(BaseModel): host:Tracked[str]|None=None
  class ComponentIntent(BaseModel):
      component_id:str; role:str; workload:Workload|None=None
      service:ServiceIntent|None=None; ingress:IngressIntent|None=None
  class KubernetesIntent(BaseModel): namespace:Tracked[str]|None=None; components:list[ComponentIntent]=[]
  # questions.py
  class UnresolvedQuestion(BaseModel):
      id:str; field:str; question:str; reason:str
      answer_type:str; candidates:list[str]=[]; blocking_level:str; profile_field:str|None=None
  class UnresolvedQuestions(BaseModel): questions:list[UnresolvedQuestion]=[]
  # profile.py
  class DeploymentProfile(BaseModel):
      model_config = ConfigDict(extra="forbid")   # reject typo keys before merge
      registry:str|None=None; namespace:str|None=None; ingress_host:str|None=None
      image_tag:str="latest"; secret_refs:dict[str,str]=Field(default_factory=dict)
  # report.py
  class StageResult(BaseModel): stage:str; status:str; detail:str|None=None
  class ValidationReport(BaseModel): target_level:int; achieved_level:int; stages:list[StageResult]=[]
  ```

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_intermediate_models.py
import unittest
from pydantic import ValidationError
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.component import ComponentModel, ComponentEntry
from preanalyzer.models.runtime import RuntimeModel, RuntimeEntry
from preanalyzer.models.dependency import DependencyModel, DependencyEdge, EnvBinding
from preanalyzer.models.intent import KubernetesIntent, ComponentIntent, Workload, ServiceIntent
from preanalyzer.models.questions import UnresolvedQuestions, UnresolvedQuestion
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.report import ValidationReport, StageResult


class IntermediateModelTests(unittest.TestCase):
    def test_component_roundtrip(self):
        m = ComponentModel(components=[ComponentEntry(
            component_id="backend",
            role=Tracked(value="application", source="rule", confidence=Confidence.HIGH, evidence_refs=["EV-1"]),
            root_path="backend")])
        again = ComponentModel.model_validate(m.model_dump())
        self.assertEqual(again.components[0].role.value, "application")

    def test_runtime_optional_port_command(self):
        e = RuntimeEntry(component_id="backend", language=Tracked(value="python", source="rule",
            confidence=Confidence.HIGH, evidence_refs=["EV-2"]), build_strategy="dockerfile")
        self.assertIsNone(e.port)
        self.assertIsNone(e.command)

    def test_dependency_model_shapes(self):
        d = DependencyModel(
            edges=[DependencyEdge(source_component="backend", target="db", dependency_type="database",
                confidence=Tracked(value="high", source="compose_depends_on", confidence=Confidence.HIGH, evidence_refs=["EV-3"]))],
            env_bindings=[EnvBinding(component_id="backend", name="DATABASE_URL", kind="configmap")])
        self.assertEqual(d.edges[0].target, "db")
        self.assertEqual(d.env_bindings[0].kind, "configmap")

    def test_intent_application_roundtrip_and_dependency_has_no_workload(self):
        intent = KubernetesIntent(components=[
            ComponentIntent(component_id="backend", role="application",
                workload=Workload(port=Tracked(value=8000, source="dockerfile_expose", confidence=Confidence.HIGH, evidence_refs=["EV-4"]),
                                  secret_env=["POSTGRES_PASSWORD"]),
                service=ServiceIntent(port=Tracked(value=8000, source="dockerfile_expose", confidence=Confidence.HIGH, evidence_refs=["EV-4"]))),
            ComponentIntent(component_id="db", role="dependency")])
        again = KubernetesIntent.model_validate(intent.model_dump())
        self.assertEqual(again.components[0].workload.port.value, 8000)
        self.assertEqual(again.components[0].workload.secret_env, ["POSTGRES_PASSWORD"])
        self.assertIsNone(again.components[1].workload)

    def test_profile_rejects_unknown_key(self):
        with self.assertRaises(ValidationError):
            DeploymentProfile.model_validate({"registr": "r.io"})  # typo

    def test_profile_defaults(self):
        p = DeploymentProfile.model_validate({"registry": "r.io", "namespace": "demo"})
        self.assertEqual(p.image_tag, "latest")

    def test_question_roundtrip(self):
        q = UnresolvedQuestions(questions=[UnresolvedQuestion(
            id="Q-REG-001", field="image_registry", question="Which registry?", reason="no registry evidence",
            answer_type="registry", blocking_level="application_runnable", profile_field="registry")])
        self.assertEqual(UnresolvedQuestions.model_validate(q.model_dump()).questions[0].id, "Q-REG-001")

    def test_report_levels(self):
        r = ValidationReport(target_level=1, achieved_level=1, stages=[StageResult(stage="kubeconform", status="pass")])
        self.assertEqual(r.achieved_level, 1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_intermediate_models -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.models.component`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/preanalyzer/models/component.py
from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class ComponentEntry(BaseModel):
    component_id: str
    role: Tracked[str]
    root_path: str | None = None

class ComponentModel(BaseModel):
    components: list[ComponentEntry] = Field(default_factory=list)
```
```python
# src/preanalyzer/models/runtime.py
from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class RuntimeEntry(BaseModel):
    component_id: str
    language: Tracked[str]
    framework: Tracked[str] | None = None
    build_strategy: str
    port: Tracked[int] | None = None
    command: Tracked[str] | None = None

class RuntimeModel(BaseModel):
    runtimes: list[RuntimeEntry] = Field(default_factory=list)
```
```python
# src/preanalyzer/models/dependency.py
from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class DependencyEdge(BaseModel):
    source_component: str
    target: str
    dependency_type: str
    confidence: Tracked[str]

class EnvBinding(BaseModel):
    component_id: str
    name: str
    kind: str  # "configmap" | "secret"

class DependencyModel(BaseModel):
    edges: list[DependencyEdge] = Field(default_factory=list)
    env_bindings: list[EnvBinding] = Field(default_factory=list)
```
```python
# src/preanalyzer/models/intent.py
from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class Workload(BaseModel):
    image_name: Tracked[str] | None = None
    image_registry: Tracked[str] | None = None
    image_tag: Tracked[str] | None = None
    port: Tracked[int] | None = None
    command: Tracked[str] | None = None
    config_env: list[str] = Field(default_factory=list)
    secret_env: list[str] = Field(default_factory=list)

class ServiceIntent(BaseModel):
    port: Tracked[int] | None = None

class IngressIntent(BaseModel):
    host: Tracked[str] | None = None

class ComponentIntent(BaseModel):
    component_id: str
    role: str
    workload: Workload | None = None
    service: ServiceIntent | None = None
    ingress: IngressIntent | None = None

class KubernetesIntent(BaseModel):
    namespace: Tracked[str] | None = None
    components: list[ComponentIntent] = Field(default_factory=list)
```
```python
# src/preanalyzer/models/questions.py
from __future__ import annotations
from pydantic import BaseModel, Field

class UnresolvedQuestion(BaseModel):
    id: str
    field: str
    question: str
    reason: str
    answer_type: str
    candidates: list[str] = Field(default_factory=list)
    blocking_level: str
    profile_field: str | None = None

class UnresolvedQuestions(BaseModel):
    questions: list[UnresolvedQuestion] = Field(default_factory=list)
```
```python
# src/preanalyzer/models/profile.py
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

class DeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: str | None = None
    namespace: str | None = None
    ingress_host: str | None = None
    image_tag: str = "latest"
    secret_refs: dict[str, str] = Field(default_factory=dict)
```
```python
# src/preanalyzer/models/report.py
from __future__ import annotations
from pydantic import BaseModel, Field

class StageResult(BaseModel):
    stage: str
    status: str  # pass | fail | skipped | not_run
    detail: str | None = None

class ValidationReport(BaseModel):
    target_level: int
    achieved_level: int
    stages: list[StageResult] = Field(default_factory=list)
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_intermediate_models -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/models/component.py src/preanalyzer/models/runtime.py src/preanalyzer/models/dependency.py src/preanalyzer/models/intent.py src/preanalyzer/models/questions.py src/preanalyzer/models/profile.py src/preanalyzer/models/report.py tests/unit/test_intermediate_models.py
git commit -m "feat: intermediate data models (06-11,13)"
```

---

## Task 2: Reconciliation Engine (rules → intent + questions)

> **✅ 구현 완료** — 커밋 0500f15 (+ 후속 fix c549d39, 3e53af7). `test_reconciliation` 5개 green.

**목표:** 결정론적 rule 후보(+수용된 semantic command)를 `KubernetesIntent`로 승격하고, 미확정 값·포트충돌을 `UnresolvedQuestion`으로 라우팅한다 (추측 금지 P5).
**변경 범위:** `reconciliation/__init__.py`, `reconciliation/engine.py` 생성 + `tests/unit/test_reconciliation.py`.
**완료 조건:** application→workload+service, dependency→no workload, registry/namespace 질문, 포트충돌→질문+port None, 수용 command 흐름 — 5개 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_reconciliation` (이 파일만).
**전체 테스트 필요:** 불필요.

**Files:**
- Create: `src/preanalyzer/reconciliation/__init__.py`, `src/preanalyzer/reconciliation/engine.py`
- Test: `tests/unit/test_reconciliation.py`

**Interfaces:**
- Consumes: `RuleInferenceSet`, `EvidenceModel`, and `list[AcceptedSemanticCommand]` (defined here, used in Task 3).
- Produces:
  ```python
  @dataclass(frozen=True)
  class AcceptedSemanticCommand: component_id:str; command:str; evidence_refs:list[str]
  @dataclass(frozen=True)
  class ReconciliationResult:
      component_model: ComponentModel; runtime_model: RuntimeModel
      dependency_model: DependencyModel; intent: KubernetesIntent
      questions: UnresolvedQuestions
  def reconcile(rules: RuleInferenceSet, evidence: EvidenceModel,
                accepted_commands: list[AcceptedSemanticCommand] | None = None) -> ReconciliationResult
  ```
- Rules for `reconcile`:
  1. `component_model` = one `ComponentEntry` per `component_candidates`, role from best `role_candidates` (default `application`).
  2. `runtime_model`: per component, port = single `runtime_port_candidates`; if the same component has >1 distinct port → leave port `None` and emit a `port` question. command = single deterministic `runtime_command_candidates`, else an accepted semantic command (classification tracked via `source="llm_semantic_inference"`), else `None`.
  3. `intent`: application-role components get a `Workload` (port/command from runtime, `image_name`=component_id, `image_registry`/`image_tag` left `None`→question, secret_env from `env_classification.secret_candidates`). Components with a port get a `ServiceIntent`. dependency/infrastructure roles get NO workload. `namespace` left `None`→question.
  4. Ops questions always emitted when unresolved: registry (`Q-REG-001`, merged once), namespace (`Q-NS-001`). Ingress host question only when a component has ingress intent seed (skip for MVP unless traefik evidence — emit `Q-ING-001` when `compose_label` traefik fact exists).
  5. dependency_model edges from `dependency_edge_candidates`; env_bindings: secret_candidates→`kind="secret"`, everything else observed as env→`kind="configmap"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reconciliation.py
import unittest
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import (
    RuleInferenceSet, ComponentCandidate, RoleCandidate, RuntimePortCandidate,
    RuntimeCommandCandidate)
from preanalyzer.reconciliation.engine import reconcile, AcceptedSemanticCommand


def _rules(**kw):
    return RuleInferenceSet(**kw)


class ReconciliationTests(unittest.TestCase):
    def test_application_component_gets_workload_and_service(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])],
            runtime_command_candidates=[RuntimeCommandCandidate("backend", "uvicorn main:app", "dockerfile_cmd", "high", ["EV-3"])])
        r = reconcile(rules, EvidenceModel())
        ci = r.intent.components[0]
        self.assertEqual(ci.role, "application")
        self.assertEqual(ci.workload.port.value, 8000)
        self.assertEqual(ci.workload.command.value, "uvicorn main:app")
        self.assertIsNotNone(ci.service)

    def test_dependency_component_has_no_workload(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("db", None, "compose", ["EV-9"])],
            role_candidates=[RoleCandidate("db", "dependency", "infra_image_pattern", "high", ["EV-9"])])
        r = reconcile(rules, EvidenceModel())
        self.assertIsNone(r.intent.components[0].workload)

    def test_registry_and_namespace_questions_emitted(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])])
        r = reconcile(rules, EvidenceModel())
        ids = {q.id for q in r.questions.questions}
        self.assertIn("Q-REG-001", ids)
        self.assertIn("Q-NS-001", ids)

    def test_port_conflict_routes_question_not_guess(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("web", "web", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("web", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[
                RuntimePortCandidate("web", 8080, "dockerfile_expose", "high", ["EV-2"]),
                RuntimePortCandidate("web", 8081, "compose_ports", "high", ["EV-3"])])
        r = reconcile(rules, EvidenceModel())
        rt = r.runtime_model.runtimes[0]
        self.assertIsNone(rt.port)
        pq = [q for q in r.questions.questions if q.answer_type == "port"]
        self.assertEqual(len(pq), 1)
        self.assertEqual(sorted(pq[0].candidates), ["8080", "8081"])

    def test_accepted_semantic_command_flows_into_runtime(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])])
        r = reconcile(rules, EvidenceModel(),
            [AcceptedSemanticCommand("backend", "uvicorn main:app --host 0.0.0.0", ["EV-ENTRY-1"])])
        rt = r.runtime_model.runtimes[0]
        self.assertEqual(rt.command.value, "uvicorn main:app --host 0.0.0.0")
        self.assertEqual(rt.command.source, "llm_semantic_inference")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_reconciliation -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.reconciliation.engine`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/preanalyzer/reconciliation/__init__.py
```
```python
# src/preanalyzer/reconciliation/engine.py
from __future__ import annotations
from dataclasses import dataclass, field

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.models.component import ComponentModel, ComponentEntry
from preanalyzer.models.runtime import RuntimeModel, RuntimeEntry
from preanalyzer.models.dependency import DependencyModel, DependencyEdge, EnvBinding
from preanalyzer.models.intent import (
    KubernetesIntent, ComponentIntent, Workload, ServiceIntent, IngressIntent)
from preanalyzer.models.questions import UnresolvedQuestions, UnresolvedQuestion


@dataclass(frozen=True)
class AcceptedSemanticCommand:
    component_id: str
    command: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationResult:
    component_model: ComponentModel
    runtime_model: RuntimeModel
    dependency_model: DependencyModel
    intent: KubernetesIntent
    questions: UnresolvedQuestions


def _conf(name: str) -> Confidence:
    return {"high": Confidence.HIGH, "medium": Confidence.MEDIUM, "low": Confidence.LOW}.get(name, Confidence.LOW)


def reconcile(rules: RuleInferenceSet, evidence: EvidenceModel,
              accepted_commands: list[AcceptedSemanticCommand] | None = None) -> ReconciliationResult:
    accepted = {c.component_id: c for c in (accepted_commands or [])}
    roles = {}
    for rc in sorted(rules.role_candidates, key=lambda c: (c.component_id, c.role)):
        roles.setdefault(rc.component_id, rc.role)  # first (sorted) wins deterministically

    components, runtimes, intents, questions = [], [], [], []
    comp_ids = sorted({c.component_id for c in rules.component_candidates})

    ports_by_comp: dict[str, list] = {}
    for pc in rules.runtime_port_candidates:
        ports_by_comp.setdefault(pc.component_id, []).append(pc)
    cmds_by_comp = {c.component_id: c for c in rules.runtime_command_candidates}

    for cid in comp_ids:
        role = roles.get(cid, "application")
        components.append(ComponentEntry(
            component_id=cid,
            role=Tracked(value=role, source="rule_inference", confidence=Confidence.HIGH, evidence_refs=[])))

        # port
        distinct_ports = sorted({p.port for p in ports_by_comp.get(cid, [])})
        port_tracked = None
        if len(distinct_ports) == 1:
            p = ports_by_comp[cid][0]
            port_tracked = Tracked(value=p.port, source=p.source, confidence=_conf(p.confidence), evidence_refs=list(p.evidence_refs))
        elif len(distinct_ports) > 1:
            questions.append(UnresolvedQuestion(
                id=f"Q-PORT-{cid}", field="runtime.port",
                question=f"Component {cid} exposes conflicting ports; which is the runtime port?",
                reason="conflicting_port_evidence", answer_type="port",
                candidates=[str(p) for p in distinct_ports],
                blocking_level="application_runnable", profile_field=None))

        # command: deterministic > accepted semantic
        cmd_tracked = None
        if cid in cmds_by_comp:
            c = cmds_by_comp[cid]
            cmd_tracked = Tracked(value=c.command, source=c.source, confidence=_conf(c.confidence), evidence_refs=list(c.evidence_refs))
        elif cid in accepted:
            a = accepted[cid]
            cmd_tracked = Tracked(value=a.command, source="llm_semantic_inference", confidence=Confidence.MEDIUM, evidence_refs=list(a.evidence_refs))

        runtimes.append(RuntimeEntry(
            component_id=cid,
            language=Tracked(value="unknown", source="rule_inference", confidence=Confidence.LOW, evidence_refs=[]),
            build_strategy="dockerfile", port=port_tracked, command=cmd_tracked))

        # intent
        if role == "application":
            workload = Workload(
                image_name=Tracked(value=cid, source="component_id", confidence=Confidence.MEDIUM, evidence_refs=[]),
                port=port_tracked, command=cmd_tracked,
                secret_env=sorted({s.name for s in rules.env_classification.secret_candidates if s.component_id == cid}))
            service = ServiceIntent(port=port_tracked) if port_tracked is not None else None
            intents.append(ComponentIntent(component_id=cid, role=role, workload=workload, service=service))
        else:
            intents.append(ComponentIntent(component_id=cid, role=role))

    # ops questions (merged once)
    questions.append(UnresolvedQuestion(id="Q-REG-001", field="image_registry",
        question="Which container registry hosts the built images?", reason="no_registry_evidence",
        answer_type="registry", blocking_level="application_runnable", profile_field="registry"))
    questions.append(UnresolvedQuestion(id="Q-NS-001", field="namespace",
        question="Which namespace should these resources deploy to?", reason="no_namespace_evidence",
        answer_type="namespace", blocking_level="application_runnable", profile_field="namespace"))
    if evidence.facts_by_type("compose_label"):
        questions.append(UnresolvedQuestion(id="Q-ING-001", field="ingress_host",
            question="Which host should the ingress route?", reason="traefik_label_detected",
            answer_type="ingress_host", blocking_level="feature_partial", profile_field="ingress_host"))

    edges = [DependencyEdge(source_component=e.source_component, target=e.target, dependency_type=e.dependency_type,
        confidence=Tracked(value=e.confidence, source=e.source, confidence=_conf(e.confidence), evidence_refs=list(e.evidence_refs)))
        for e in sorted(rules.dependency_edge_candidates, key=lambda e: (e.source_component, e.target))]
    env_bindings = [EnvBinding(component_id=s.component_id, name=s.name, kind="secret")
        for s in sorted(rules.env_classification.secret_candidates, key=lambda s: (s.component_id, s.name))]

    return ReconciliationResult(
        component_model=ComponentModel(components=components),
        runtime_model=RuntimeModel(runtimes=runtimes),
        dependency_model=DependencyModel(edges=edges, env_bindings=env_bindings),
        intent=KubernetesIntent(namespace=None, components=intents),
        questions=UnresolvedQuestions(questions=sorted(questions, key=lambda q: q.id)))
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_reconciliation -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/reconciliation/ tests/unit/test_reconciliation.py
git commit -m "feat: minimal reconciliation engine (rules+accepted cmd -> intent+questions)"
```

---

## Task 3: Wire accepted semantic command out of the orchestrator

> **⚠️ 반쪽 완료** — 커밋 76768f7로 추출 로직·튜플 반환·배선은 구현됨(`test_returns_audit_and_accepted_list_disabled_mode` green). 단 커밋이 플랜 수정 전이라 **신규 유닛테스트 `test_extracts_accepted_command_from_run`(Step 1 두 번째 테스트)는 아직 없음.** 착수 시 그 테스트만 추가하고, 이미 통과하면 확인 커밋, 실패하면 root 수정.

**목표:** verifier가 accept한 runtime command를 semantic run 결과에서 뽑아 `_build_semantic_analysis_audit`가 `(audit, list[AcceptedSemanticCommand])`로 반환 — LLM 값이 리컨실로 흐르는 유일한 통로.
**변경 범위:** `src/preanalyzer/pipeline.py` (`_build_semantic_analysis_audit` + `_run_semantic_task_for_audit` + 내부 호출부) + `tests/unit/test_semantic_command_wiring.py`.
**완료 조건:** disabled→`[]`, accepted run→command 1건 추출 — 두 유닛테스트 통과, 기존 semantic 통합테스트 green, 커밋.
**실행할 테스트 범위:** `tests.unit.test_semantic_command_wiring` + `tests.acceptance.test_semantic_pipeline_integration` (인접 영향 파일).
**전체 테스트 필요:** 불필요 — pipeline 시그니처 확대뿐, 영향 파일 지정 실행으로 충분.

**Interfaces:**
- Produces: `_build_semantic_analysis_audit(...) -> tuple[dict, list[AcceptedSemanticCommand]]`. Accepted command extracted from each run whose `verification_result.status == "accepted"`: take the recommended candidate's `value["command"]` and its `evidence_refs`.
- `run_phase1_analysis` keeps its current return tuple (backward compatible) but internally captures the accepted-command list for Task 7 to reuse.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_semantic_command_wiring.py
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from preanalyzer.pipeline import _build_semantic_analysis_audit
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.reconciliation.engine import AcceptedSemanticCommand


class SemanticCommandWiringTests(unittest.TestCase):
    def test_returns_audit_and_accepted_list_disabled_mode(self):
        audit, accepted = _build_semantic_analysis_audit(
            repository_root=Path(tempfile.gettempdir()),
            evidence=EvidenceModel(), rules=RuleInferenceSet(),
            semantic_mode="disabled", decision_provider=None,
            semantic_model=None, semantic_task_max_tool_calls=None)
        self.assertIsInstance(audit, dict)
        self.assertEqual(accepted, [])

    def test_extracts_accepted_command_from_run(self):
        # A run whose verification accepted the recommended candidate must surface
        # exactly one AcceptedSemanticCommand carrying the candidate's command value.
        rec = SimpleNamespace(candidate_id="SC-1", component_id="backend",
            value={"command": "uvicorn main:app --host 0.0.0.0"}, evidence_refs=["EV-ENTRY-1"])
        result = SimpleNamespace(
            verification_result=SimpleNamespace(status="accepted"),
            resolution=SimpleNamespace(recommended_candidate_id="SC-1", candidates=[rec]))
        # _run_semantic_task_for_audit now returns (audit_dict, SemanticAgentRunResult|None);
        # patch it so the loop sees our accepted run without a live agent.
        with patch("preanalyzer.pipeline._run_semantic_task_for_audit",
                   return_value=({"task_id": "T-1"}, result)):
            audit, accepted = _build_semantic_analysis_audit(
                repository_root=Path(tempfile.gettempdir()),
                evidence=EvidenceModel(), rules=RuleInferenceSet(),
                semantic_mode="fake", decision_provider=object(),
                semantic_model=None, semantic_task_max_tool_calls=None)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0], AcceptedSemanticCommand(
            "backend", "uvicorn main:app --host 0.0.0.0", ["EV-ENTRY-1"]))
```

> Note: the second test stubs `_run_semantic_task_for_audit`; align the patched attribute path and the `status`/`recommended_candidate_id`/`candidates` field names with the real `models/semantic.py` / `semantic_agent.py` during implementation (see risk #1). The `fastapi-shell-entrypoint` acceptance test (Task 9) additionally exercises the live end-to-end path.

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_semantic_command_wiring -v`
Expected: FAIL — currently returns a bare dict (`ValueError: too many values to unpack`), and the loop does not yet expose a `SemanticAgentRunResult` to patch.

- [ ] **Step 3: Write minimal implementation**

In `src/preanalyzer/pipeline.py` add near the top imports:
```python
from preanalyzer.reconciliation.engine import AcceptedSemanticCommand
```
Change the end of `_build_semantic_analysis_audit` to return a tuple, building the accepted list from `runs`. The function already assembles `runs: list[dict]`; each run's `resolution`/`verification_result` are dicts, but the command VALUE is not in the dict — so extract from the live results BEFORE they are reduced. Concretely, in the loop that calls `_run_semantic_task_for_audit`, keep the `SemanticAgentRunResult`:
```python
    accepted: list[AcceptedSemanticCommand] = []
    # inside the existing runs-building loop, after obtaining `result` (SemanticAgentRunResult):
    if result is not None and result.verification_result is not None \
            and str(result.verification_result.status) == "accepted" \
            and result.resolution is not None and result.resolution.recommended_candidate_id:
        rec = next((c for c in result.resolution.candidates
                    if c.candidate_id == result.resolution.recommended_candidate_id), None)
        if rec is not None and isinstance(rec.value, dict) and "command" in rec.value:
            accepted.append(AcceptedSemanticCommand(
                component_id=rec.component_id, command=str(rec.value["command"]),
                evidence_refs=list(rec.evidence_refs)))
    ...
    return audit, accepted
```
Refactor `_run_semantic_task_for_audit` to return `(audit_dict, SemanticAgentRunResult | None)` so the caller can inspect `result`. Update the single caller `run_phase1_analysis`:
```python
        semantic_audit, accepted_commands = _build_semantic_analysis_audit(...)
        # ...write 00-04 unchanged...
```
Since `run_phase1_analysis` returns a 4-tuple today, do NOT change its signature here. Task 7 introduces `run_analysis` that calls the same helpers and consumes `accepted_commands`. For this task, only `_build_semantic_analysis_audit` changes shape; fix its one internal caller.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_semantic_command_wiring tests.acceptance.test_semantic_pipeline_integration -v`
Expected: PASS (2 new tests + existing integration test still green).

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/pipeline.py tests/unit/test_semantic_command_wiring.py
git commit -m "feat: extract verifier-accepted runtime command from semantic runs"
```

---

## Task 4: Profile merge + dev-profile fixture

> **✅ 구현 완료** — 커밋 42b7fe9. `profile_merge.py` + `dev-profile.yaml` 존재, `test_profile_merge` green.

**목표:** `DeploymentProfile`을 검증해 intent의 registry/namespace/ingress_host/image_tag를 채우고, 해소된 질문을 제거하며 `ready_for_level2`를 판정한다 (P5 채움 통로).
**변경 범위:** `reconciliation/profile_merge.py`, `tests/fixtures/profiles/dev-profile.yaml` 생성 + `tests/unit/test_profile_merge.py`.
**완료 조건:** registry/namespace 채움+질문 제거, blocking 질문 없으면 `ready_for_level2` — 두 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_profile_merge` (이 파일만).
**전체 테스트 필요:** 불필요.

**Files:**
- Create: `src/preanalyzer/reconciliation/profile_merge.py`, `tests/fixtures/profiles/dev-profile.yaml`
- Test: `tests/unit/test_profile_merge.py`

**Interfaces:**
- Consumes: `ReconciliationResult`, `DeploymentProfile`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class MergeResult: intent: KubernetesIntent; questions: UnresolvedQuestions; ready_for_level2: bool
  def merge(result: ReconciliationResult, profile: DeploymentProfile) -> MergeResult
  ```
- Behavior: set `intent.namespace` from `profile.namespace`; set each application workload's `image_registry` from `profile.registry`, `image_tag` from `profile.image_tag`; set ingress host from `profile.ingress_host` (creating `IngressIntent` on the traefik-seeded component — for MVP, the first application component when an ingress question exists). Drop questions whose `profile_field` is now satisfied (registry→Q-REG, namespace→Q-NS, ingress_host→Q-ING). `ready_for_level2 = no remaining question with blocking_level == "application_runnable"`. All profile-injected values use `source="deployment_profile"`, confidence HIGH.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_profile_merge.py
import unittest
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet, ComponentCandidate, RoleCandidate, RuntimePortCandidate
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.reconciliation.engine import reconcile
from preanalyzer.reconciliation.profile_merge import merge


def _base():
    rules = RuleInferenceSet(
        component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
        role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
        runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])])
    return reconcile(rules, EvidenceModel())


class ProfileMergeTests(unittest.TestCase):
    def test_registry_namespace_resolved_and_questions_dropped(self):
        res = _base()
        m = merge(res, DeploymentProfile(registry="reg.internal", namespace="demo"))
        ci = m.intent.components[0]
        self.assertEqual(ci.workload.image_registry.value, "reg.internal")
        self.assertEqual(m.intent.namespace.value, "demo")
        ids = {q.id for q in m.questions.questions}
        self.assertNotIn("Q-REG-001", ids)
        self.assertNotIn("Q-NS-001", ids)

    def test_ready_for_level2_when_no_blocking_questions(self):
        res = _base()
        m = merge(res, DeploymentProfile(registry="reg.internal", namespace="demo"))
        self.assertTrue(m.ready_for_level2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_profile_merge -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.reconciliation.profile_merge`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/preanalyzer/reconciliation/profile_merge.py
from __future__ import annotations
from dataclasses import dataclass

from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.intent import KubernetesIntent, IngressIntent
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.questions import UnresolvedQuestions
from preanalyzer.reconciliation.engine import ReconciliationResult


@dataclass(frozen=True)
class MergeResult:
    intent: KubernetesIntent
    questions: UnresolvedQuestions
    ready_for_level2: bool


def _pf(value: str) -> Tracked[str]:
    return Tracked(value=value, source="deployment_profile", confidence=Confidence.HIGH, evidence_refs=[])


def merge(result: ReconciliationResult, profile: DeploymentProfile) -> MergeResult:
    intent = result.intent.model_copy(deep=True)
    if profile.namespace:
        intent.namespace = _pf(profile.namespace)
    for ci in intent.components:
        if ci.workload is None:
            continue
        if profile.registry:
            ci.workload.image_registry = _pf(profile.registry)
        ci.workload.image_tag = _pf(profile.image_tag)
    if profile.ingress_host:
        app = next((c for c in intent.components if c.role == "application"), None)
        if app is not None:
            app.ingress = IngressIntent(host=_pf(profile.ingress_host))

    satisfied = set()
    if profile.registry: satisfied.add("registry")
    if profile.namespace: satisfied.add("namespace")
    if profile.ingress_host: satisfied.add("ingress_host")
    remaining = [q for q in result.questions.questions if q.profile_field not in satisfied]
    ready = not any(q.blocking_level == "application_runnable" for q in remaining)
    return MergeResult(intent=intent, questions=UnresolvedQuestions(questions=remaining), ready_for_level2=ready)
```
```yaml
# tests/fixtures/profiles/dev-profile.yaml
registry: reg.internal.demo
namespace: demo
ingress_host: app.demo.internal
image_tag: v0
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_profile_merge -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/reconciliation/profile_merge.py tests/fixtures/profiles/dev-profile.yaml tests/unit/test_profile_merge.py
git commit -m "feat: deployment profile validation + merge into intent"
```

---

## Task 5: Template Renderer (12)

**목표:** `KubernetesIntent`를 Jinja2 템플릿으로만 manifest 트리로 렌더하고, 필수값 미해소 리소스는 defer한다 (P3 템플릿 전용, 발명 금지).
**변경 범위:** `renderer/{__init__,policy,engine}.py`, `renderer/templates/*.j2` 생성; `pyproject.toml`에 jinja2 추가 + `tests/unit/test_renderer.py`.
**완료 조건:** deployment/service/sa/secret 렌더, secret 값=`__REPLACE_ME__`, registry 없으면 deployment defer, dependency는 렌더 없음 — 4개 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_renderer` (이 파일만).
**전체 테스트 필요:** 불필요 — 신규 의존성(jinja2) 추가지만 렌더러 자체 격리.

**Files:**
- Create: `src/preanalyzer/renderer/__init__.py`, `src/preanalyzer/renderer/policy.py`, `src/preanalyzer/renderer/engine.py`, `src/preanalyzer/renderer/templates/{deployment,service,configmap,secret.placeholder,serviceaccount,ingress}.yaml.j2`
- Modify: `pyproject.toml` (add `jinja2>=3.1`)
- Test: `tests/unit/test_renderer.py`

**Interfaces:**
- Consumes: `KubernetesIntent`, snapshot metadata (`commit_sha`, `rules_version`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class DeferredResource: component_id:str; resource:str; reason:str
  @dataclass(frozen=True)
  class RenderResult:
      files: dict[str, str]              # relative path -> YAML text
      deferred: list[DeferredResource]
      achieved_level_cap: int            # 1 normally, 0 if any placeholder rendered
  class TemplateRenderer:
      def __init__(self, commit_sha:str|None, rules_version:str): ...
      def render(self, intent: KubernetesIntent, allow_placeholders: bool=False) -> RenderResult
  ```
- Policy: application component with `workload.image_registry` resolved → render Deployment (+ ServiceAccount always, + ConfigMap if config_env, + Secret placeholder if secret_env, + Service if service.port, + Ingress if ingress.host). If `image_registry` unresolved and not `allow_placeholders` → defer Deployment (reason `unresolved_image_registry`) and its Service/Ingress. dependency/infrastructure role → render nothing (reason `role_dependency_no_workload`). Namespace: emit `metadata.namespace` only if `intent.namespace` set. Labels on every resource: `app.kubernetes.io/name`, `.../part-of`, `.../managed-by=preanalyzer`. Annotations: `preanalyzer/commit-sha`, `preanalyzer/rules-version`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_renderer.py
import unittest
import yaml
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.intent import KubernetesIntent, ComponentIntent, Workload, ServiceIntent
from preanalyzer.renderer.engine import TemplateRenderer


def _t(v, s="x"):
    return Tracked(value=v, source=s, confidence=Confidence.HIGH, evidence_refs=["EV"])


def _app_intent(registry=True):
    wl = Workload(image_name=_t("backend"), image_tag=_t("v0"), port=_t(8000), command=_t("uvicorn main:app"),
                  secret_env=["POSTGRES_PASSWORD"])
    if registry:
        wl.image_registry = _t("reg.internal")
    return KubernetesIntent(namespace=_t("demo"), components=[ComponentIntent(
        component_id="backend", role="application", workload=wl, service=ServiceIntent(port=_t(8000)))])


class RendererTests(unittest.TestCase):
    def test_renders_deployment_service_sa_secret(self):
        r = TemplateRenderer(commit_sha="abc123", rules_version="2026.07").render(_app_intent())
        paths = set(r.files)
        self.assertTrue(any(p.endswith("backend/deployment.yaml") for p in paths))
        self.assertTrue(any(p.endswith("backend/service.yaml") for p in paths))
        self.assertTrue(any(p.endswith("backend/serviceaccount.yaml") for p in paths))
        self.assertTrue(any(p.endswith("backend/secret.yaml") for p in paths))
        dep = yaml.safe_load(next(t for p, t in r.files.items() if p.endswith("deployment.yaml")))
        c = dep["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["image"], "reg.internal/backend:v0")
        self.assertEqual(c["ports"][0]["containerPort"], 8000)
        self.assertNotIn("resources", c)  # no invented resources
        self.assertEqual(dep["metadata"]["namespace"], "demo")
        self.assertEqual(dep["metadata"]["labels"]["app.kubernetes.io/managed-by"], "preanalyzer")

    def test_secret_placeholder_value_is_replace_me(self):
        r = TemplateRenderer("abc", "2026.07").render(_app_intent())
        sec = yaml.safe_load(next(t for p, t in r.files.items() if p.endswith("secret.yaml")))
        self.assertEqual(sec["stringData"]["POSTGRES_PASSWORD"], "__REPLACE_ME__")

    def test_defers_deployment_without_registry(self):
        r = TemplateRenderer("abc", "2026.07").render(_app_intent(registry=False))
        self.assertFalse(any(p.endswith("deployment.yaml") for p in r.files))
        self.assertTrue(any(d.resource == "Deployment" and d.reason == "unresolved_image_registry" for d in r.deferred))

    def test_dependency_component_renders_nothing(self):
        intent = KubernetesIntent(components=[ComponentIntent(component_id="db", role="dependency")])
        r = TemplateRenderer("abc", "2026.07").render(intent)
        self.assertEqual(r.files, {})
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_renderer -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.renderer.engine`.

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies: `"jinja2>=3.1"`. Install: `uv pip install --python .venv/bin/python3 "jinja2>=3.1"`.

```python
# src/preanalyzer/renderer/__init__.py
```
```python
# src/preanalyzer/renderer/policy.py
from __future__ import annotations

COMMON_LABELS = ("app.kubernetes.io/name", "app.kubernetes.io/part-of", "app.kubernetes.io/managed-by")

def labels(component_id: str) -> dict:
    return {
        "app.kubernetes.io/name": component_id,
        "app.kubernetes.io/part-of": component_id,
        "app.kubernetes.io/managed-by": "preanalyzer",
    }

def annotations(commit_sha: str | None, rules_version: str) -> dict:
    return {"preanalyzer/commit-sha": commit_sha or "unknown", "preanalyzer/rules-version": rules_version}
```
```python
# src/preanalyzer/renderer/engine.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from preanalyzer.models.intent import KubernetesIntent
from preanalyzer.renderer.policy import labels, annotations

_TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class DeferredResource:
    component_id: str
    resource: str
    reason: str


@dataclass(frozen=True)
class RenderResult:
    files: dict[str, str] = field(default_factory=dict)
    deferred: list[DeferredResource] = field(default_factory=list)
    achieved_level_cap: int = 1


class TemplateRenderer:
    def __init__(self, commit_sha: str | None, rules_version: str) -> None:
        self._env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                                undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
        self._commit_sha = commit_sha
        self._rules_version = rules_version

    def render(self, intent: KubernetesIntent, allow_placeholders: bool = False) -> RenderResult:
        files: dict[str, str] = {}
        deferred: list[DeferredResource] = []
        ns = intent.namespace.value if intent.namespace else None
        ann = annotations(self._commit_sha, self._rules_version)
        for ci in intent.components:
            if ci.role != "application" or ci.workload is None:
                deferred.append(DeferredResource(ci.component_id, "Workload", "role_dependency_no_workload"))
                continue
            wl = ci.workload
            lbl = labels(ci.component_id)
            base = {"name": ci.component_id, "namespace": ns, "labels": lbl, "annotations": ann}
            if wl.image_registry is None or wl.image_registry.value is None:
                deferred.append(DeferredResource(ci.component_id, "Deployment", "unresolved_image_registry"))
                continue
            image = f"{wl.image_registry.value}/{wl.image_name.value}:{wl.image_tag.value}"
            command = wl.command.value if wl.command else None
            port = wl.port.value if wl.port else None
            files[f"{ci.component_id}/serviceaccount.yaml"] = self._env.get_template("serviceaccount.yaml.j2").render(**base)
            files[f"{ci.component_id}/deployment.yaml"] = self._env.get_template("deployment.yaml.j2").render(
                **base, image=image, port=port, command=command,
                config_env=wl.config_env, secret_env=wl.secret_env)
            if wl.config_env:
                files[f"{ci.component_id}/configmap.yaml"] = self._env.get_template("configmap.yaml.j2").render(**base, keys=wl.config_env)
            if wl.secret_env:
                files[f"{ci.component_id}/secret.yaml"] = self._env.get_template("secret.placeholder.yaml.j2").render(**base, keys=wl.secret_env)
            if ci.service and ci.service.port and ci.service.port.value is not None:
                files[f"{ci.component_id}/service.yaml"] = self._env.get_template("service.yaml.j2").render(**base, port=ci.service.port.value)
            if ci.ingress and ci.ingress.host and ci.ingress.host.value:
                files[f"{ci.component_id}/ingress.yaml"] = self._env.get_template("ingress.yaml.j2").render(
                    **base, host=ci.ingress.host.value, service_port=port)
            else:
                deferred.append(DeferredResource(ci.component_id, "Ingress", "unresolved_ingress_host"))
        return RenderResult(files=dict(sorted(files.items())), deferred=deferred, achieved_level_cap=1)
```

Templates (`src/preanalyzer/renderer/templates/`):
```jinja
{# deployment.yaml.j2 #}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ name }}
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}  annotations:
{% for k, v in annotations.items() %}    {{ k }}: "{{ v }}"
{% endfor %}spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ name }}
    spec:
      serviceAccountName: {{ name }}
      containers:
        - name: {{ name }}
          image: {{ image }}
{% if command %}          command: ["sh", "-c", {{ command | tojson }}]
{% endif %}{% if port %}          ports:
            - containerPort: {{ port }}
{% endif %}{% if config_env %}          envFrom:
            - configMapRef:
                name: {{ name }}-config
{% endif %}{% if secret_env %}          envFrom:
            - secretRef:
                name: {{ name }}-secret
{% endif %}
```
```jinja
{# service.yaml.j2 #}
apiVersion: v1
kind: Service
metadata:
  name: {{ name }}
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}spec:
  selector:
    app.kubernetes.io/name: {{ name }}
  ports:
    - port: {{ port }}
      targetPort: {{ port }}
```
```jinja
{# serviceaccount.yaml.j2 #}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ name }}
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}
```
```jinja
{# configmap.yaml.j2 #}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ name }}-config
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}data:
{% for key in keys %}  {{ key }}: ""
{% endfor %}
```
```jinja
{# secret.placeholder.yaml.j2 #}
apiVersion: v1
kind: Secret
metadata:
  name: {{ name }}-secret
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}type: Opaque
stringData:
{% for key in keys %}  {{ key }}: "__REPLACE_ME__"
{% endfor %}
```
```jinja
{# ingress.yaml.j2 #}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ name }}
{% if namespace %}  namespace: {{ namespace }}
{% endif %}  labels:
{% for k, v in labels.items() %}    {{ k }}: {{ v }}
{% endfor %}spec:
  rules:
    - host: {{ host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ name }}
                port:
                  number: {{ service_port }}
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_renderer -v`
Expected: PASS (4 tests). If a template's YAML indentation trips `yaml.safe_load`, fix indentation in the `.j2` until the parsed structure matches the assertions.

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/renderer/ pyproject.toml tests/unit/test_renderer.py
git commit -m "feat: jinja2 template renderer with defer policy (12)"
```

---

## Task 6: Validator (13)

**목표:** manifest 트리를 yaml→kubeconform→dry-run으로 검증하고 `achieved_level`을 부여한다 (도구 부재는 skip, 실패 시 fail-fast).
**변경 범위:** `validator/{__init__,pipeline}.py` 생성 + `tests/unit/test_validator.py`.
**완료 조건:** 깨진 yaml→fail+후속 skip, kubeconform 부재→skip+level0, placeholder→level0 — 3개 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_validator` (이 파일만).
**전체 테스트 필요:** 불필요.

**Files:**
- Create: `src/preanalyzer/validator/__init__.py`, `src/preanalyzer/validator/pipeline.py`
- Test: `tests/unit/test_validator.py`

**Interfaces:**
- Produces:
  ```python
  class ValidationPipeline:
      def __init__(self, k8s_version: str = "1.29"): ...
      def run(self, manifest_dir: Path, rendered_placeholders: bool = False) -> ValidationReport
  ```
- Chain: `yaml_syntax` (parse every `*.yaml`) → `kubeconform` (`kubeconform -strict -kubernetes-version <v> -summary <dir>`, via `shutil.which`; absent → `skipped: tool_not_found`) → `dry_run` (`kubectl apply --dry-run=client`; absent → `skipped: tool_not_found`). fail-fast: after a `fail`, later stages `skipped`. Level: `rendered_placeholders` → 0; else if `yaml_syntax` pass and `kubeconform` pass → 1; if `kubeconform` skipped → 0 (unverified). `target_level=1` always here.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_validator.py
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from preanalyzer.validator.pipeline import ValidationPipeline


def _write(d: Path, name: str, text: str):
    (d / name).write_text(text, encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def test_broken_yaml_fails_syntax_then_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); _write(d, "bad.yaml", "a: [1, 2\n")
            report = ValidationPipeline().run(d)
        stages = {s.stage: s.status for s in report.stages}
        self.assertEqual(stages["yaml_syntax"], "fail")
        self.assertEqual(stages["kubeconform"], "skipped")
        self.assertEqual(report.achieved_level, 0)

    def test_missing_kubeconform_is_skipped_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); _write(d, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")
            with patch("preanalyzer.validator.pipeline.shutil.which", return_value=None):
                report = ValidationPipeline().run(d)
        stages = {s.stage: s.status for s in report.stages}
        self.assertEqual(stages["yaml_syntax"], "pass")
        self.assertEqual(stages["kubeconform"], "skipped")
        self.assertEqual(report.achieved_level, 0)  # unverified without kubeconform

    def test_placeholder_capped_at_level0(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); _write(d, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")
            report = ValidationPipeline().run(d, rendered_placeholders=True)
        self.assertEqual(report.achieved_level, 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.validator.pipeline`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/preanalyzer/validator/__init__.py
```
```python
# src/preanalyzer/validator/pipeline.py
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

import yaml

from preanalyzer.models.report import ValidationReport, StageResult


class ValidationPipeline:
    def __init__(self, k8s_version: str = "1.29") -> None:
        self._k8s_version = k8s_version

    def run(self, manifest_dir: Path, rendered_placeholders: bool = False) -> ValidationReport:
        stages: list[StageResult] = []
        yaml_ok = self._yaml_syntax(manifest_dir, stages)
        kubeconform_status = "skipped"
        if yaml_ok:
            kubeconform_status = self._kubeconform(manifest_dir, stages)
        else:
            stages.append(StageResult(stage="kubeconform", status="skipped", detail="prior stage failed"))
        # dry_run (optional, informational)
        if yaml_ok and kubeconform_status == "pass":
            self._dry_run(manifest_dir, stages)
        else:
            stages.append(StageResult(stage="dry_run", status="skipped", detail="prior stage not pass"))

        if rendered_placeholders:
            achieved = 0
        elif yaml_ok and kubeconform_status == "pass":
            achieved = 1
        else:
            achieved = 0
        return ValidationReport(target_level=1, achieved_level=achieved, stages=stages)

    def _yaml_syntax(self, d: Path, stages: list[StageResult]) -> bool:
        for path in sorted(d.rglob("*.yaml")):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                stages.append(StageResult(stage="yaml_syntax", status="fail", detail=f"{path.name}: {exc}"))
                return False
        stages.append(StageResult(stage="yaml_syntax", status="pass"))
        return True

    def _kubeconform(self, d: Path, stages: list[StageResult]) -> str:
        if shutil.which("kubeconform") is None:
            stages.append(StageResult(stage="kubeconform", status="skipped", detail="tool_not_found"))
            return "skipped"
        proc = subprocess.run(
            ["kubeconform", "-strict", "-summary", "-kubernetes-version", self._k8s_version, str(d)],
            capture_output=True, text=True, check=False)
        status = "pass" if proc.returncode == 0 else "fail"
        stages.append(StageResult(stage="kubeconform", status=status, detail=(proc.stdout or proc.stderr).strip()[:500]))
        return status

    def _dry_run(self, d: Path, stages: list[StageResult]) -> None:
        if shutil.which("kubectl") is None:
            stages.append(StageResult(stage="dry_run", status="skipped", detail="tool_not_found"))
            return
        proc = subprocess.run(["kubectl", "apply", "--dry-run=client", "-f", str(d)],
                              capture_output=True, text=True, check=False)
        stages.append(StageResult(stage="dry_run", status="pass" if proc.returncode == 0 else "fail",
                                  detail=(proc.stdout or proc.stderr).strip()[:500]))
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/validator/ tests/unit/test_validator.py
git commit -m "feat: validation pipeline yaml->kubeconform->dry-run with level (13)"
```

---

## Task 7: Orchestrator — write 05–15

**목표:** 00–04 → reconcile → (profile) merge → render → validate 전 파이프라인을 `run_analysis`로 잇고 05–15 산출물을 결정론적으로 쓴다 (P2 순서, P10 재현성).
**변경 범위:** `src/preanalyzer/pipeline.py` (`run_analysis` 추가) + `tests/unit/test_pipeline_full_outputs.py`.
**완료 조건:** 05–13 파일+12 디렉터리 생성, 두 번 실행 바이트 동일 — 두 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_pipeline_full_outputs` (이 파일만).
**전체 테스트 필요:** 불필요 — 통합이지만 픽스처 대상 지정 실행으로 검증. 광역 회귀는 Task 11에서 일괄.

**Files:**
- Modify: `src/preanalyzer/pipeline.py` (add `run_analysis`)
- Test: `tests/unit/test_pipeline_full_outputs.py`

**Interfaces:**
- Produces:
  ```python
  def run_analysis(repo, output_dir, url, ref, clock, *, mode="workspace",
      semantic_mode="disabled", semantic_decision_provider=None, semantic_model=None,
      profile_path: Path | None = None) -> ValidationReport
  ```
- Steps inside: run the existing 00–04 pipeline (reuse `snapshot`/`build_inventory`/`_parse_inventory`/`build_evidence`/`infer`/`_build_semantic_analysis_audit` — now returning accepted commands); `reconcile(rules, evidence, accepted_commands)`; if `profile_path`, load+validate `DeploymentProfile` and `merge` → use merged intent+questions; render via `TemplateRenderer(snapshot.commit_sha, RULES_VERSION)`; write `05-reconciliation-report.yaml` (component/runtime/dependency summary + ready_for_level2), `06`–`09` (component/runtime/dependency/intent), `10-unresolved-questions.yaml`, `12-generated-manifests/<files>`, then run `ValidationPipeline().run(manifest_dir, rendered_placeholders=render.achieved_level_cap==0)` → `13-validation-report.yaml`; write `14-deployment-readiness-checklist.md` (question ids) and `15-smoke-test-plan.yaml` (health-endpoint stub). Return the report.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_full_outputs.py
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from preanalyzer.pipeline import run_analysis

FIXED = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
def clock(): return FIXED
REPO = Path("tests/fixtures/repos/node-express-like")
PROFILE = Path("tests/fixtures/profiles/dev-profile.yaml")


class FullOutputTests(unittest.TestCase):
    def test_writes_05_to_13_with_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = run_analysis(REPO, out, url=None, ref=None, clock=clock,
                                  semantic_mode="disabled", profile_path=PROFILE)
        for name in ["05-reconciliation-report.yaml", "06-component-model.yaml", "07-runtime-model.yaml",
                     "08-dependency-model.yaml", "09-kubernetes-intent.yaml", "10-unresolved-questions.yaml",
                     "13-validation-report.yaml"]:
            self.assertTrue((out / name).is_file(), name)
        self.assertTrue((out / "12-generated-manifests").is_dir())
        self.assertIn(report.achieved_level, (0, 1))

    def test_determinism_two_runs_identical(self):
        import filecmp, os
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for out in (Path(a), Path(b)):
                run_analysis(REPO, out, url=None, ref=None, clock=clock, semantic_mode="disabled", profile_path=PROFILE)
            for name in ["06-component-model.yaml", "09-kubernetes-intent.yaml"]:
                self.assertEqual(Path(a, name).read_bytes(), Path(b, name).read_bytes(), name)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_pipeline_full_outputs -v`
Expected: FAIL — `ImportError: cannot import name 'run_analysis'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/preanalyzer/pipeline.py` (reuse existing helpers; import the new modules at top):
```python
import yaml as _yaml_mod  # if not already; existing module imports yaml as `yaml`
from preanalyzer.rules_version import RULES_VERSION
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.report import ValidationReport
from preanalyzer.reconciliation.engine import reconcile
from preanalyzer.reconciliation.profile_merge import merge
from preanalyzer.renderer.engine import TemplateRenderer
from preanalyzer.validator.pipeline import ValidationPipeline


def run_analysis(repo, output_dir, url, ref, clock, *, mode="workspace",
                 semantic_mode="disabled", semantic_decision_provider=None,
                 semantic_model=None, profile_path=None) -> ValidationReport:
    snap, inventory, evidence, rules = run_phase1_analysis(
        repo=repo, output_dir=output_dir, url=url, ref=ref, clock=clock, mode=mode,
        semantic_mode=semantic_mode, semantic_decision_provider=semantic_decision_provider,
        semantic_model=semantic_model)
    # re-derive accepted commands (same helper, deterministic)
    _, accepted = _build_semantic_analysis_audit(
        repository_root=resolve_repository_path(repo), evidence=evidence, rules=rules,
        semantic_mode=semantic_mode, decision_provider=semantic_decision_provider,
        semantic_model=semantic_model, semantic_task_max_tool_calls=None)
    result = reconcile(rules, evidence, accepted)
    intent, questions, ready = result.intent, result.questions, False
    if profile_path is not None:
        profile = DeploymentProfile.model_validate(yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")))
        merged = merge(result, profile)
        intent, questions, ready = merged.intent, merged.questions, merged.ready_for_level2

    render = TemplateRenderer(snap.commit_sha, RULES_VERSION).render(intent)
    manifest_dir = output_dir / "12-generated-manifests"
    for rel, text in render.files.items():
        target = manifest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    manifest_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(output_dir / "05-reconciliation-report.yaml", {"reconciliation_report": {
        "ready_for_level2": ready,
        "deferred": [d.__dict__ for d in render.deferred]}})
    _write_yaml(output_dir / "06-component-model.yaml", {"component_model": result.component_model.model_dump()})
    _write_yaml(output_dir / "07-runtime-model.yaml", {"runtime_model": result.runtime_model.model_dump()})
    _write_yaml(output_dir / "08-dependency-model.yaml", {"dependency_model": result.dependency_model.model_dump()})
    _write_yaml(output_dir / "09-kubernetes-intent.yaml", {"kubernetes_intent": intent.model_dump()})
    _write_yaml(output_dir / "10-unresolved-questions.yaml", {"unresolved_questions": questions.model_dump()})

    report = ValidationPipeline().run(manifest_dir, rendered_placeholders=render.achieved_level_cap == 0)
    _write_yaml(output_dir / "13-validation-report.yaml", {"validation_report": report.model_dump()})
    (output_dir / "14-deployment-readiness-checklist.md").write_text(
        "# Deployment Readiness\n\n" + "".join(f"- [ ] {q.id}: {q.question}\n" for q in questions.questions),
        encoding="utf-8")
    _write_yaml(output_dir / "15-smoke-test-plan.yaml", {"smoke_test_plan": {"checks": []}})
    return report
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_pipeline_full_outputs -v`
Expected: PASS (2 tests). If determinism fails, ensure every written list is sorted and no timestamp other than `clock` leaks.

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/pipeline.py tests/unit/test_pipeline_full_outputs.py
git commit -m "feat: orchestrator writes 05-15 (reconcile->render->validate)"
```

---

## Task 8: CLI

**목표:** `analyze` 서브커맨드로 저장소→05–15 산출을 커맨드라인에서 구동한다 (사용자 진입점).
**변경 범위:** `src/preanalyzer/cli.py` 생성 + `tests/unit/test_cli.py`.
**완료 조건:** analyze가 09 파일 생성+exit 0, 미지 커맨드 non-zero — 두 테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.unit.test_cli` (이 파일만).
**전체 테스트 필요:** 불필요.

**Files:**
- Create: `src/preanalyzer/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `python -m preanalyzer.cli analyze <repo> [--profile P] [--out DIR] [--semantic-mode {disabled,openai_compatible}] [--no-llm] [--ref REF]`. `main(argv: list[str]) -> int`. `--no-llm` forces `semantic_mode=disabled`. Uses real wall clock unless `--out` determinism needed (tests pass a repo + tmp out).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py
import unittest
from pathlib import Path
import tempfile
from preanalyzer.cli import main


class CliTests(unittest.TestCase):
    def test_analyze_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["analyze", "tests/fixtures/repos/node-express-like",
                         "--profile", "tests/fixtures/profiles/dev-profile.yaml",
                         "--no-llm", "--out", tmp])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "09-kubernetes-intent.yaml").is_file())

    def test_unknown_command_returns_nonzero(self):
        self.assertNotEqual(main(["frobnicate"]), 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_cli -v`
Expected: FAIL — `ModuleNotFoundError: preanalyzer.cli`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/preanalyzer/cli.py
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path

from preanalyzer.pipeline import run_analysis


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preanalyzer")
    sub = parser.add_subparsers(dest="command")
    a = sub.add_parser("analyze")
    a.add_argument("repo")
    a.add_argument("--profile")
    a.add_argument("--out", default="repo-analysis-output")
    a.add_argument("--ref")
    a.add_argument("--semantic-mode", choices=["disabled", "openai_compatible"], default="disabled")
    a.add_argument("--no-llm", action="store_true")
    args = parser.parse_args(argv)
    if args.command != "analyze":
        parser.print_usage()
        return 2
    semantic_mode = "disabled" if args.no_llm else args.semantic_mode
    report = run_analysis(
        repo=Path(args.repo), output_dir=Path(args.out), url=None, ref=args.ref, clock=_clock,
        semantic_mode=semantic_mode,
        profile_path=Path(args.profile) if args.profile else None)
    print(f"achieved_level={report.achieved_level} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_cli -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/preanalyzer/cli.py tests/unit/test_cli.py
git commit -m "feat: analyze CLI (argparse)"
```

---

## Task 9: fastapi-shell-entrypoint fixture (#3) + live-agent acceptance

**목표:** shell entrypoint 저장소에서 semantic agent가 resolve한 runtime command가 09 intent까지 흐르는 데모 성공 장면을 픽스처+수용테스트로 잠근다 (#3).
**변경 범위:** `tests/fixtures/repos/fastapi-shell-entrypoint/` 생성 + `tests/acceptance/test_demo_repos.py` (`test_shell_entrypoint_agent_resolves_command`). 제품 코드 변경 없음(Task 2/3/7이 이미 배선).
**완료 조건:** 09 backend command == uvicorn..., source == `llm_semantic_inference` — 수용테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.acceptance.test_demo_repos` (이 파일만).
**전체 테스트 필요:** 불필요 — 픽스처+테스트, 제품 코드 무변경.

**Files:**
- Create: `tests/fixtures/repos/fastapi-shell-entrypoint/` (Dockerfile, entrypoint.sh, pyproject.toml, compose)
- Test: `tests/acceptance/test_demo_repos.py` (`test_shell_entrypoint_agent_resolves_command`)

**Interfaces:**
- Consumes: `run_analysis` with a scripted `AgentDecisionProvider` (reuse the pattern from `tests/acceptance/test_semantic_pipeline_integration.py::ResolveFromContextProvider`).

- [ ] **Step 1: Create the fixture**

```dockerfile
# tests/fixtures/repos/fastapi-shell-entrypoint/backend/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```
```bash
# tests/fixtures/repos/fastapi-shell-entrypoint/backend/entrypoint.sh
exec uvicorn main:app --host 0.0.0.0 --port 8000
```
```toml
# tests/fixtures/repos/fastapi-shell-entrypoint/backend/pyproject.toml
[project]
name = "backend"
dependencies = ["fastapi", "uvicorn"]
```
```yaml
# tests/fixtures/repos/fastapi-shell-entrypoint/docker-compose.yml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/acceptance/test_demo_repos.py
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import yaml
from preanalyzer.pipeline import run_analysis
from preanalyzer.models.semantic import SemanticCandidate, SemanticResolution, SemanticResolutionStatus
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction

FIXED = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
def clock(): return FIXED
PROFILE = Path("tests/fixtures/profiles/dev-profile.yaml")


class _ResolveShellEntrypoint:
    def __init__(self): self.n = 0
    def decide(self, context):
        self.n += 1
        if self.n == 1:
            return ToolCallAction(tool_name="inspect_entrypoint_script",
                                  arguments={"path": "backend/entrypoint.sh"})
        ref = context.collected_evidence[0]["evidence_id"]
        return ResolutionAction(resolution=SemanticResolution(
            task_id=context.task_id, status=SemanticResolutionStatus.RESOLVED,
            candidates=[SemanticCandidate(candidate_id="SC-1", component_id=context.component_id,
                target_field=context.target_field, value={"command": "uvicorn main:app --host 0.0.0.0 --port 8000"},
                classification="llm_semantic_inference", confidence="medium", evidence_refs=[ref])],
            recommended_candidate_id="SC-1", tool_trace_refs=[ref]))


class ShellEntrypointTests(unittest.TestCase):
    def test_shell_entrypoint_agent_resolves_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run_analysis(Path("tests/fixtures/repos/fastapi-shell-entrypoint"), out, url=None, ref=None,
                         clock=clock, semantic_mode="fake",
                         semantic_decision_provider=_ResolveShellEntrypoint(), profile_path=PROFILE)
            intent = yaml.safe_load((out / "09-kubernetes-intent.yaml").read_text())
        backend = next(c for c in intent["kubernetes_intent"]["components"] if c["component_id"] == "backend")
        self.assertEqual(backend["workload"]["command"]["value"], "uvicorn main:app --host 0.0.0.0 --port 8000")
        self.assertEqual(backend["workload"]["command"]["source"], "llm_semantic_inference")
```

> If the scripted provider's exact tool name/argument keys differ from the live tool schema, align them with `tests/acceptance/test_semantic_pipeline_integration.py` (which uses `read_source_range` on `entrypoint.sh`). Use whichever tool the shell-entrypoint reason's allowlist grants (`inspect_entrypoint_script`).

- [ ] **Step 3: Run to verify it fails, then passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_demo_repos -v`
Expected first: FAIL (fixture/command mismatch or no accepted command). Adjust the scripted provider until the accepted command flows into `09`. No product code change should be needed (Tasks 3, 2, 7 already wire it); this task is fixture + test.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/repos/fastapi-shell-entrypoint tests/acceptance/test_demo_repos.py
git commit -m "test: shell-entrypoint fixture — agent-resolved command flows into intent (#3)"
```

---

## Task 10: port-conflict-node fixture (#5) + acceptance

**목표:** 포트 충돌 저장소에서 충돌이 추측 대신 질문으로 라우팅되고 runtime.port가 None임을 픽스처+수용테스트로 잠근다 (#5, P5).
**변경 범위:** `tests/fixtures/repos/port-conflict-node/` 생성 + `tests/acceptance/test_demo_repos.py` 확장. 필요 시 `rule_inference`에 compose 컨테이너-포트 후보 emission 1개 추가.
**완료 조건:** port 질문 1건+candidates `["8080","8081"]`, web.port None — 수용테스트 통과, 커밋.
**실행할 테스트 범위:** `tests.acceptance.test_demo_repos` (+ rule_inference 수정 시 `tests.unit.test_reconciliation`은 이미 충돌로직 커버).
**전체 테스트 필요:** 불필요.

**Files:**
- Create: `tests/fixtures/repos/port-conflict-node/` (Dockerfile, package.json, docker-compose.yml)
- Test: extend `tests/acceptance/test_demo_repos.py`

- [ ] **Step 1: Create the fixture**

```dockerfile
# tests/fixtures/repos/port-conflict-node/Dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json .
EXPOSE 8080
CMD ["node", "server.js"]
```
```json
{ "scripts": { "start": "node server.js" }, "dependencies": { "express": "^4.0.0" } }
```
```yaml
# tests/fixtures/repos/port-conflict-node/docker-compose.yml
services:
  web:
    build: .
    ports:
      - "8081:8081"
```

- [ ] **Step 2: Write the failing test** (append)

```python
class PortConflictTests(unittest.TestCase):
    def test_conflicting_ports_route_question_and_no_port_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run_analysis(Path("tests/fixtures/repos/port-conflict-node"), out, url=None, ref=None,
                         clock=clock, semantic_mode="disabled")
            questions = yaml.safe_load((out / "10-unresolved-questions.yaml").read_text())
            runtime = yaml.safe_load((out / "07-runtime-model.yaml").read_text())
        port_qs = [q for q in questions["unresolved_questions"]["questions"] if q["answer_type"] == "port"]
        self.assertEqual(len(port_qs), 1)
        self.assertEqual(sorted(port_qs[0]["candidates"]), ["8080", "8081"])
        web = next(r for r in runtime["runtime_model"]["runtimes"] if r["component_id"] == "web")
        self.assertIsNone(web["port"])  # no silent pick
```

> Verify the port mechanism first: run the pipeline on this fixture and confirm `03-rule-inference.yaml` contains two `runtime_port_candidates` for `web` (8080 from `dockerfile_expose`, 8081 from `compose_ports`). If `compose_ports` does not yield a `RuntimePortCandidate`, that is a real gap — check `rule_inference._runtime_port_candidates`; the conflict test depends on both candidates existing. If compose ports map host:container as `8081:8081`, the container port 8081 must surface as a candidate.

- [ ] **Step 3: Run to verify it fails, then passes**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_demo_repos -v`
Expected: adjust until the conflict question appears and `web.port is None`. If rule_inference does not emit a compose container-port candidate, add that emission in `rule_inference` (smallest change: emit `RuntimePortCandidate` from `compose_ports` container port) as part of this task, with its own unit assertion in `tests/unit/test_reconciliation.py` already covering the conflict logic.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/repos/port-conflict-node tests/acceptance/test_demo_repos.py src/preanalyzer/analyzer/rule_inference.py
git commit -m "test: port-conflict fixture — conflict routes to question, no guess (#5)"
```

---

## Task 11: Demo acceptance suite (5-repo roles + safety + determinism)

**목표:** 5종 저장소 스펙트럼 전반에서 role 처리·secret 비유출·전체 트리 결정론을 수용테스트로 잠그고, 기능 묶음 완료 게이트로 전체 회귀를 1회 돌린다.
**변경 범위:** `tests/acceptance/test_demo_repos.py` 확장.
**완료 조건:** 5-repo 스펙트럼 테스트 통과 + 전체 `discover` green + `validate_context_paths` green, 커밋.
**실행할 테스트 범위:** `tests.acceptance.test_demo_repos` → 이어서 전체 `discover`.
**전체 테스트 필요:** **필요** — 이유(전략 #3): 이 태스크가 전 기능 묶음(모델→리컨실→렌더→검증→CLI→데모)의 완료 지점이고, 결정론·secret 안전은 여러 모듈 상호작용에 걸쳐 회귀 위험이 넓기 때문. 커밋 전 1회 실행.

**Files:**
- Test: extend `tests/acceptance/test_demo_repos.py`

**Interfaces:** Consumes `run_analysis` on all five repos.

- [ ] **Step 1: Write the tests**

```python
class DemoSpectrumTests(unittest.TestCase):
    def _run(self, repo, **kw):
        tmp = tempfile.mkdtemp(); out = Path(tmp)
        run_analysis(Path(repo), out, url=None, ref=None, clock=clock, **kw)
        return out

    def test_node_express_completes_manifests(self):  # #1
        out = self._run("tests/fixtures/repos/node-express-like", semantic_mode="disabled", profile_path=PROFILE)
        manifests = list((out / "12-generated-manifests").rglob("*.yaml"))
        self.assertTrue(any(p.name == "deployment.yaml" for p in manifests))

    def test_fastapi_multi_component_db_is_dependency(self):  # #2
        out = self._run("tests/fixtures/repos/fastapi-fullstack-like", semantic_mode="disabled", profile_path=PROFILE)
        intent = yaml.safe_load((out / "09-kubernetes-intent.yaml").read_text())
        db = next(c for c in intent["kubernetes_intent"]["components"] if c["component_id"] == "db")
        self.assertIsNone(db["workload"])

    def test_jpetstore_no_dockerfile_defers_and_flags_build(self):  # #4
        out = self._run("tests/fixtures/repos/jpetstore-like", semantic_mode="disabled")
        rules = (out / "03-rule-inference.yaml").read_text()
        self.assertIn("dockerfile_needed", rules)
        # no image => deployment deferred (not present)
        self.assertFalse(any(p.name == "deployment.yaml" for p in (out / "12-generated-manifests").rglob("*.yaml")))

    def test_no_secret_value_leaks_anywhere(self):  # AC-0.4 across fastapi
        out = self._run("tests/fixtures/repos/fastapi-fullstack-like", semantic_mode="disabled", profile_path=PROFILE)
        for path in out.rglob("*"):
            if path.is_file():
                self.assertNotIn("changethis", path.read_text(encoding="utf-8", errors="ignore"), str(path))

    def test_determinism_full_tree(self):  # AC-0.6
        a, b = self._run("tests/fixtures/repos/node-express-like", semantic_mode="disabled", profile_path=PROFILE), \
               self._run("tests/fixtures/repos/node-express-like", semantic_mode="disabled", profile_path=PROFILE)
        names = [p.name for p in a.glob("0*.yaml")]
        for name in names:
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
```

- [ ] **Step 2: Run the suite**

Run: `PYTHONPATH=src .venv/bin/python3 -m unittest tests.acceptance.test_demo_repos -v`
Expected: All pass. Investigate and fix any failure at its root (do not weaken assertions). Common fixes: sort a newly added list; ensure `changethis` never enters ConfigMap data (secret classification must catch `POSTGRES_PASSWORD`).

- [ ] **Step 3: Full regression**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v`
Then: `python3 scripts/validate_context_paths.py .`
Expected: entire suite green.

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/test_demo_repos.py
git commit -m "test: 5-repo demo spectrum acceptance (roles + secret-safety + determinism)"
```

---

## Live LLM rehearsal (manual, not a unit test)

Not a code task — the demo-day path. Requires `kubeconform` on PATH and on-prem endpoint env.

```bash
export SEMANTIC_LLM_BASE_URL="https://<onprem>/v1"
export SEMANTIC_LLM_MODEL="solar-pro3"
export SEMANTIC_LLM_API_KEY="<key>"
PYTHONPATH=src .venv/bin/python3 -m preanalyzer.cli analyze \
  tests/fixtures/repos/fastapi-shell-entrypoint \
  --profile tests/fixtures/profiles/dev-profile.yaml \
  --semantic-mode openai_compatible --out /tmp/demo-live
# Expect: 04 shows inspect_entrypoint_script tool-call + accepted; 09 backend command == uvicorn...;
#         12 backend/deployment.yaml present; 13 achieved_level==1 (kubeconform installed).
# Backup: rerun with --no-llm to guarantee a green deterministic tree for the demo.
```

---

## Self-Review

**Spec coverage:** 5-repo spectrum → Tasks 9/10/11 (+ existing fixtures #1/#2/#4 exercised in 11). Manifest end-to-end → Tasks 1–8. Live LLM success (#3) → Tasks 3+9. Honest questions / no-Dockerfile (#4) → reconcile ops-questions (Task 2) + renderer defer (Task 5) + acceptance (Task 11). Conflict preservation (#5) → Task 2 logic + Task 10. Secret safety → renderer `__REPLACE_ME__` (Task 5) + acceptance leak scan (Task 11). Determinism → sorted outputs + Task 7/11 byte tests. Roadmap items (semantic role/boundary vertical, Dockerfile generation) explicitly excluded.

**Decomposition:** each task completes one user action / policy / technical result and carries its own test + minimal implementation in the same Red→Green→(Refactor) cycle. Pure data-model files are bundled into Task 1 (shared context + test file) rather than split per model, since a model with no consumer is not independently valuable. Every task header states 목표 / 변경 범위 / 완료 조건 / 실행할 테스트 범위 / 전체 테스트 필요. Full `discover` runs only in Task 11 (feature-bundle completion gate), with the reason stated there.

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — each task carries real test + implementation code. Two tasks (9 fixture-provider tool name, 10 compose-port emission) carry explicit "verify first, adjust if the codebase differs" notes rather than blind code, because they depend on existing behavior that must be confirmed against the live code — these are verification steps, not placeholders.

**Type consistency:** `Tracked(value/source/confidence/evidence_refs)` used identically everywhere; `reconcile(rules, evidence, accepted_commands)` signature matches Tasks 2/3/7; `AcceptedSemanticCommand(component_id, command, evidence_refs)` defined in engine.py and imported by pipeline.py; `TemplateRenderer(commit_sha, rules_version).render(intent, allow_placeholders=False) -> RenderResult(files, deferred, achieved_level_cap)` consistent Tasks 5/7; `ValidationPipeline().run(manifest_dir, rendered_placeholders) -> ValidationReport(target_level, achieved_level, stages)` consistent Tasks 6/7.

**Known verification-gated risks (confirm during execution, fix at root):**
1. Task 3 — exact attribute path on `SemanticAgentRunResult`/`SemanticResolution` for the accepted command value; align with `models/semantic.py`/`semantic_agent.py` (the `test_extracts_accepted_command_from_run` stub field names too).
2. Task 10 — whether `rule_inference` emits a `RuntimePortCandidate` from `compose_ports`; if not, add the emission (task includes it).
3. Task 5 — Jinja2 YAML indentation; iterate templates until `yaml.safe_load` structure matches assertions.
