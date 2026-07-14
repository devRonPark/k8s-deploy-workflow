from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from k8s_agent.agent.planner import AgentPlanner, PlanningContext
from k8s_agent.agent.actions import SemanticActionExecutor, SemanticResolutionSet
from k8s_agent.analysis.intent_builder import IntentBuilder
from k8s_agent.analysis.phase1_adapter import PHASE1_ARTIFACTS, Phase1Adapter, Phase1Result
from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.errors import AgentError
from k8s_agent.models.decision import Decision
from k8s_agent.models.run import RunRecord, RunState, TERMINAL_STATES
from k8s_agent.models.source import RepositorySource
from k8s_agent.profile.builder import DeploymentProfileBuilder, ProfileInputs
from k8s_agent.questions.answers import AnswerLoader
from k8s_agent.questions.manager import QuestionManager
from k8s_agent.render.renderer import ManifestRenderer
from k8s_agent.repair.controller import RepairController, RepairResult
from k8s_agent.run.manager import RunManager
from k8s_agent.versions import RENDERER_VERSION, TEMPLATE_VERSION
from k8s_agent.validation.orchestrator import ValidationOrchestrator


TOOL_VERSIONS = {
    "phase1": "phase1-adapter/v1",
    "topology": "topology-builder/v1",
    "intent": "intent-builder/v1",
    "planner": "agent-planner/v1",
    "profile": "deployment-profile-builder/v1",
    "renderer": RENDERER_VERSION,
    "template": TEMPLATE_VERSION,
    "validator": "validation-orchestrator/v1",
    "repair": "repair-controller/v1",
}


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    run_root: Path
    target: str
    source_kind: str
    state: RunState
    exit_code: int
    message: str


@dataclass(frozen=True)
class OrchestrationResult:
    state: RunState
    exit_code: int
    message: str
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)


class AgentOrchestrator:
    def __init__(
        self,
        *,
        run_manager: RunManager,
        pipeline: Callable[[str], OrchestrationResult] | None = None,
        reuse_completed_analysis: bool = False,
        answers_file: Path | None = None,
        semantic_executor: SemanticActionExecutor | None = None,
    ) -> None:
        self.run_manager = run_manager
        self.store = run_manager.store
        self.pipeline = pipeline or self._run_default_pipeline
        self.reuse_completed_analysis = reuse_completed_analysis
        self.answers_file = answers_file
        self.semantic_executor = semantic_executor

    def run(self, run_id: str) -> RunOutcome:
        record = self.store.load(run_id)
        if record.state in TERMINAL_STATES:
            return _outcome(record, _terminal_exit_code(record.state), f"run is already {record.state.value}")

        try:
            if record.state == RunState.CREATED:
                record = self.run_manager.transition(run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
            if record.state in {RunState.ACQUIRING_SOURCE, RunState.WAITING_FOR_USER}:
                record = self.run_manager.transition(run_id, RunState.ANALYZING, "agent orchestration started")

            result = self.pipeline(run_id)
            for relative_path, payload in sorted(result.artifacts.items()):
                self.store.save_yaml(run_id, relative_path, payload)
            if result.state != record.state:
                record = self.run_manager.transition(run_id, result.state, result.message)
            else:
                record = self.store.load(run_id)
            return _outcome(record, result.exit_code, result.message)
        except KeyboardInterrupt:
            record = self.run_manager.transition(run_id, RunState.CANCELLED, "run cancelled by user")
            return _outcome(record, 130, "run cancelled by user")
        except AgentError as exc:
            record = self.run_manager.transition(run_id, RunState.FAILED, exc.message)
            return _outcome(record, exc.exit_code, f"[{exc.code}] {exc.message}")
        except Exception as exc:
            record = self.run_manager.transition(run_id, RunState.FAILED, "unexpected internal error")
            return _outcome(record, 8, f"unexpected internal error: {type(exc).__name__}")

    def _run_default_pipeline(self, run_id: str) -> OrchestrationResult:
        record = self.store.load(run_id)
        run_root = self.store.run_path(run_id)
        source = _load_source(run_root / "source.yaml")

        phase1 = self._phase1(source, run_id)
        topology = TopologyBuilder().build(phase1)
        intent = IntentBuilder(output_dir=phase1.analysis_dir).build(topology, record.target)
        plan = AgentPlanner().plan(PlanningContext(topology=topology, intent=intent))
        semantic_resolution: SemanticResolutionSet | None = None
        semantic_decisions: list[Decision] = []
        if self.semantic_executor is not None and any(task.action == "semantic_action" for task in plan.tasks):
            semantic_resolution = self.semantic_executor.resolve_runtime_commands(topology, phase1)
            semantic_decisions = _semantic_profile_decisions(semantic_resolution)
        question_manager = QuestionManager()
        questions = question_manager.build(intent, plan)
        decisions = list(semantic_decisions)
        if self.answers_file is not None:
            answers = AnswerLoader().load(self.answers_file, questions)
            decisions.extend(question_manager.to_decisions(answers))
        profile = DeploymentProfileBuilder().build(ProfileInputs(intent=intent, decisions=decisions))

        artifacts: dict[str, dict[str, Any]] = {
            "agent/runtime-metadata.yaml": {"tool_versions": TOOL_VERSIONS},
            "agent/plan.yaml": {"agent_plan": plan.model_dump(mode="json")},
            "agent/questions.yaml": {"question_set": questions.model_dump(mode="json")},
            "profile/deployment-profile.yaml": {"deployment_profile": profile.model_dump(mode="json")},
        }
        if semantic_resolution is not None:
            artifacts["agent/semantic-resolution.yaml"] = {"semantic_resolution": semantic_resolution.model_dump(mode="json")}

        if profile.blocked:
            return OrchestrationResult(
                state=RunState.BLOCKED,
                exit_code=4,
                message="policy blocked manifest generation",
                artifacts=artifacts,
            )
        if profile.unresolved:
            return OrchestrationResult(
                state=RunState.WAITING_FOR_USER,
                exit_code=0,
                message="deployment decisions are waiting for user input",
                artifacts=artifacts,
            )

        generated_dir = run_root / "generated"
        bundle = ManifestRenderer().render(profile, generated_dir)
        report = ValidationOrchestrator(run_external=True).validate(bundle, profile, generated_dir)
        artifacts.update(
            {
                "generated/manifest-bundle.yaml": {"manifest_bundle": bundle.model_dump(mode="json")},
                "validation/13-validation-report.yaml": {"validation_report": report.model_dump(mode="json")},
            }
        )

        repair: RepairResult | None = None
        if not report.manifest_ready:
            repair = RepairController(destination=generated_dir).repair(bundle, profile, report)
            artifacts["repair/14-repair-report.yaml"] = {"repair_report": repair.model_dump(mode="json")}
            report = ValidationOrchestrator(run_external=True).validate(bundle, profile, generated_dir)
            artifacts["validation/13-validation-report.yaml"] = {"validation_report": report.model_dump(mode="json")}

        if report.manifest_ready:
            message = "manifests are ready"
            if repair is not None and repair.repaired:
                message = "manifests are ready after repair"
            return OrchestrationResult(state=RunState.READY, exit_code=0, message=message, artifacts=artifacts)

        return OrchestrationResult(
            state=RunState.FAILED,
            exit_code=5,
            message="manifest validation failed",
            artifacts=artifacts,
        )

    def _phase1(self, source: RepositorySource, run_id: str) -> Phase1Result:
        if self.reuse_completed_analysis:
            reused = _existing_phase1(self.store.run_path(run_id), source)
            if reused is not None:
                self.run_manager.append_event(run_id, "phase1_reused", "completed phase1 artifacts reused")
                return reused
        return Phase1Adapter(store=self.store, clock=self.run_manager.clock).run(source, run_id)


def _load_source(path: Path) -> RepositorySource:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RepositorySource.model_validate(payload)


def _existing_phase1(run_root: Path, source: RepositorySource) -> Phase1Result | None:
    if _runtime_metadata(run_root).get("tool_versions") != TOOL_VERSIONS:
        return None
    analysis_dir = run_root / "analysis"
    checksums: dict[str, str] = {}
    for name in PHASE1_ARTIFACTS:
        path = analysis_dir / name
        if not path.is_file():
            return None
        checksums[name] = _sha256(path)
    return Phase1Result(
        run_id=run_root.name,
        analysis_dir=analysis_dir,
        repository_root=source.path,
        checksums=checksums,
        artifact_count=len(PHASE1_ARTIFACTS),
    )


def _runtime_metadata(run_root: Path) -> dict:
    path = run_root / "agent" / "runtime-metadata.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _semantic_profile_decisions(resolution: SemanticResolutionSet) -> list[Decision]:
    by_task = {
        item["task_id"]: item
        for item in resolution.task_decisions
        if isinstance(item.get("task_id"), str) and isinstance(item.get("target_field"), str)
    }
    decisions: list[Decision] = []
    for result in resolution.results:
        if result.verification_status != "accepted" or not result.accepted_commands:
            continue
        task = by_task.get(result.task_id)
        if task is None:
            continue
        target_field = _profile_command_field(task["target_field"])
        command = result.accepted_commands[0]
        decisions.append(
            Decision(
                decision_id=f"D-{result.task_id}",
                target_field=target_field,
                value=command,
                raw_value=command,
                normalized_value=command,
                classification="llm_semantic_inference",
                confidence="medium",
                evidence_refs=result.evidence_refs,
                actor="agent",
                alternatives=[],
                approval="automatic",
                affected_resources=[],
            )
        )
    return sorted(decisions, key=lambda item: item.decision_id)


def _profile_command_field(target_field: str) -> str:
    if target_field.endswith("/runtime/command"):
        return f"{target_field.removesuffix('/runtime/command')}/workload/command"
    return target_field


def _outcome(record: RunRecord, exit_code: int, message: str) -> RunOutcome:
    return RunOutcome(
        run_id=record.run_id,
        run_root=record.run_root,
        target=record.target,
        source_kind=record.source.kind,
        state=record.state,
        exit_code=exit_code,
        message=message,
    )


def _terminal_exit_code(state: RunState) -> int:
    if state == RunState.READY:
        return 0
    if state == RunState.BLOCKED:
        return 4
    if state == RunState.CANCELLED:
        return 130
    return 8
