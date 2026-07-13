from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from k8s_agent.agent.planner import AgentPlanner, PlanningContext
from k8s_agent.analysis.intent_builder import IntentBuilder
from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunRecord, RunState, TERMINAL_STATES
from k8s_agent.models.source import RepositorySource
from k8s_agent.profile.builder import DeploymentProfileBuilder, ProfileInputs
from k8s_agent.questions.manager import QuestionManager
from k8s_agent.render.renderer import ManifestRenderer
from k8s_agent.repair.controller import RepairController, RepairResult
from k8s_agent.run.manager import RunManager
from k8s_agent.validation.orchestrator import ValidationOrchestrator


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
    ) -> None:
        self.run_manager = run_manager
        self.store = run_manager.store
        self.pipeline = pipeline or self._run_default_pipeline

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
            return _outcome(record, exc.exit_code, exc.message)
        except Exception as exc:
            record = self.run_manager.transition(run_id, RunState.FAILED, "unexpected internal error")
            return _outcome(record, 8, f"unexpected internal error: {type(exc).__name__}")

    def _run_default_pipeline(self, run_id: str) -> OrchestrationResult:
        record = self.store.load(run_id)
        run_root = self.store.run_path(run_id)
        source = _load_source(run_root / "source.yaml")

        phase1 = Phase1Adapter(store=self.store, clock=self.run_manager.clock).run(source, run_id)
        topology = TopologyBuilder().build(phase1)
        intent = IntentBuilder(output_dir=phase1.analysis_dir).build(topology, record.target)
        plan = AgentPlanner().plan(PlanningContext(topology=topology, intent=intent))
        questions = QuestionManager().build(intent, plan)
        profile = DeploymentProfileBuilder().build(ProfileInputs(intent=intent, decisions=[]))

        artifacts: dict[str, dict[str, Any]] = {
            "agent/plan.yaml": {"agent_plan": plan.model_dump(mode="json")},
            "agent/questions.yaml": {"question_set": questions.model_dump(mode="json")},
            "profile/deployment-profile.yaml": {"deployment_profile": profile.model_dump(mode="json")},
        }

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
        report = ValidationOrchestrator(run_external=False).validate(bundle, profile, generated_dir)
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
            report = repair.validation_result
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


def _load_source(path: Path) -> RepositorySource:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RepositorySource.model_validate(payload)


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
