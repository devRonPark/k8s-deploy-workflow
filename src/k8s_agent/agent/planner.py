from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.models.intent import KubernetesIntent
from k8s_agent.models.topology import ApplicationTopology, TopologyConflict


class TaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    task_id: str
    action: str
    component_id: str | None = None
    reason_code: str
    evidence_refs: list[str] = Field(default_factory=list)
    tool: str | None = None
    completion_condition: str
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agent-plan/v1"
    tasks: list[AgentTask] = Field(default_factory=list)


@dataclass(frozen=True)
class PlanningContext:
    topology: ApplicationTopology
    intent: KubernetesIntent
    completed_task_ids: set[str] = field(default_factory=set)


class AgentPlanner:
    def plan(self, context: PlanningContext) -> AgentPlan:
        tasks: list[AgentTask] = []
        tasks.extend(_semantic_tasks(context.topology))
        tasks.extend(_build_strategy_tasks(context.topology))
        tasks.extend(_policy_tasks(context.intent))
        tasks.extend(_generation_tasks(context.intent))
        planned = _dedupe_sorted(tasks)
        completed = set(context.completed_task_ids)
        return AgentPlan(
            tasks=[
                task.model_copy(update={"status": TaskStatus.COMPLETED if task.task_id in completed else TaskStatus.PENDING})
                for task in planned
            ]
        )

    def next_action(self, plan: AgentPlan) -> AgentTask | None:
        for task in plan.tasks:
            if task.status != TaskStatus.COMPLETED:
                return task
        return None


def _semantic_tasks(topology: ApplicationTopology) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    conflict_components: set[str] = set()
    for conflict in topology.conflicts:
        if conflict.reason != "conflicting_runtime_commands" or not conflict.field_path.endswith("/runtime/command"):
            continue
        component_id = _component_from_field_path(conflict.field_path)
        conflict_components.add(component_id)
        tasks.append(
            _task(
                action="semantic_action",
                component_id=component_id,
                reason_code="conflicting_runtime_commands",
                evidence_refs=conflict.evidence_refs,
                tool="resolve_runtime_command",
                completion_condition="verified semantic runtime command result exists",
            )
        )
    for component in topology.components:
        if component.component_id in conflict_components:
            continue
        if component.role == "application" and component.command is None:
            tasks.append(
                _task(
                    action="semantic_action",
                    component_id=component.component_id,
                    reason_code="missing_runtime_command",
                    evidence_refs=component.evidence_refs,
                    tool="resolve_runtime_command",
                    completion_condition="verified semantic runtime command result exists",
                )
            )
    return tasks


def _build_strategy_tasks(topology: ApplicationTopology) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    for component in topology.components:
        if component.role != "application":
            continue
        strategy = component.runtime.build_strategy if component.runtime is not None else None
        if strategy != "dockerfile":
            refs = list(component.evidence_refs)
            if component.runtime is not None:
                refs.extend(component.runtime.evidence_refs)
            tasks.append(
                _task(
                    action="ask_user",
                    component_id=component.component_id,
                    reason_code="ask_build_strategy",
                    evidence_refs=refs,
                    tool=None,
                    completion_condition="user selected deployable build strategy",
                )
            )
    return tasks


def _policy_tasks(intent: KubernetesIntent) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    for candidate in intent.candidates:
        if candidate.decision is None:
            continue
        if candidate.decision.disposition == "requires_confirmation":
            tasks.append(
                _task(
                    action="ask_user",
                    component_id=None if candidate.component_id == "__run__" else candidate.component_id,
                    reason_code=candidate.decision.reason_code,
                    evidence_refs=candidate.evidence_refs,
                    tool=None,
                    completion_condition=f"user decision recorded for {candidate.field_path}",
                )
            )
        elif candidate.decision.disposition == "blocked":
            tasks.append(
                _task(
                    action="blocker",
                    component_id=None if candidate.component_id == "__run__" else candidate.component_id,
                    reason_code=candidate.decision.reason_code,
                    evidence_refs=candidate.evidence_refs,
                    tool=None,
                    completion_condition=f"blocked policy candidate resolved for {candidate.field_path}",
                )
            )
    return tasks


def _generation_tasks(intent: KubernetesIntent) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    deployment_components = [
        candidate.component_id
        for candidate in intent.candidates
        if candidate.kind == "deployment" and candidate.decision is not None and candidate.decision.disposition == "auto_confirm"
    ]
    for component_id in sorted(set(deployment_components)):
        tasks.append(
            _task(
                action="generate_manifests",
                component_id=component_id,
                reason_code="auto_confirmed_deployment_intent",
                evidence_refs=[],
                tool="manifest_renderer",
                completion_condition="component manifests generated from deployment profile",
            )
        )
    if any(candidate.kind == "cluster_validation" and candidate.decision is not None and candidate.decision.disposition == "auto_confirm" for candidate in intent.candidates):
        tasks.append(
            _task(
                action="validate_manifests",
                component_id=None,
                reason_code="cluster_validation_allowed",
                evidence_refs=[],
                tool="kubeconform",
                completion_condition="generated manifests validated or findings recorded",
            )
        )
    return tasks


def _task(
    *,
    action: str,
    component_id: str | None,
    reason_code: str,
    evidence_refs: list[str],
    tool: str | None,
    completion_condition: str,
) -> AgentTask:
    refs = sorted(set(evidence_refs))
    payload = {
        "action": action,
        "component_id": component_id,
        "reason_code": reason_code,
        "evidence_refs": refs,
        "tool": tool,
        "completion_condition": completion_condition,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    return AgentTask(
        task_id=f"AT-{digest.upper()}",
        action=action,
        component_id=component_id,
        reason_code=reason_code,
        evidence_refs=refs,
        tool=tool,
        completion_condition=completion_condition,
    )


def _dedupe_sorted(tasks: list[AgentTask]) -> list[AgentTask]:
    by_id = {task.task_id: task for task in tasks}
    return [by_id[key] for key in sorted(by_id, key=lambda task_id: _task_sort_key(by_id[task_id]))]


def _task_sort_key(task: AgentTask) -> tuple[int, str, str, str]:
    order = {
        "blocker": 0,
        "semantic_action": 1,
        "ask_user": 2,
        "generate_manifests": 3,
        "validate_manifests": 4,
    }
    return (order.get(task.action, 99), task.component_id or "", task.reason_code, task.task_id)


def _component_from_field_path(field_path: str) -> str:
    parts = field_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "components":
        return parts[1].replace("~1", "/").replace("~0", "~")
    return "unknown"
