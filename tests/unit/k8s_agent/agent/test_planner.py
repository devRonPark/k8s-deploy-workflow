from __future__ import annotations

import unittest

from k8s_agent.agent.planner import AgentPlanner, PlanningContext, TaskStatus
from k8s_agent.analysis.intent_builder import IntentBuilder
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent, PolicyDecision
from k8s_agent.models.topology import ApplicationComponent, ApplicationTopology, RuntimeInfo, TopologyConflict
from k8s_agent.policy.target_policy import Target


def topology(*components: ApplicationComponent, conflicts: list[TopologyConflict] | None = None) -> ApplicationTopology:
    return ApplicationTopology(components=list(components), conflicts=conflicts or [])


def app(component_id="api", *, command=True, build_strategy="dockerfile") -> ApplicationComponent:
    return ApplicationComponent(
        component_id=component_id,
        root_path=".",
        role="application",
        evidence_refs=["F001"],
        runtime=RuntimeInfo(
            language="nodejs",
            framework="express",
            build_tool="npm",
            build_strategy=build_strategy,
            source="package.json",
            confidence="high",
            classification="rule_inference",
            evidence_refs=["F002"],
        ),
        command=None if not command else None,
    )


class PlannerTests(unittest.TestCase):
    def test_plan_has_stable_task_ids_and_next_action_skips_completed(self):
        topo = topology(app())
        intent = IntentBuilder().build(topo, Target.DEVELOPMENT)
        first = AgentPlanner().plan(PlanningContext(topology=topo, intent=intent))
        second = AgentPlanner().plan(PlanningContext(topology=topo, intent=intent))

        self.assertEqual([task.task_id for task in first.tasks], [task.task_id for task in second.tasks])
        completed = {first.tasks[0].task_id}
        replanned = AgentPlanner().plan(PlanningContext(topology=topo, intent=intent, completed_task_ids=completed))
        self.assertEqual(replanned.tasks[0].status, TaskStatus.COMPLETED)
        self.assertNotEqual(AgentPlanner().next_action(replanned).task_id, first.tasks[0].task_id)

    def test_intent_confirmation_and_blocked_candidates_become_user_and_blocker_tasks(self):
        intent = KubernetesIntent(
            target="staging",
            candidates=[
                candidate("api", "external_exposure", "requires_confirmation", ["F010"]),
                candidate("db", "stateful_workload", "blocked", ["F020"]),
            ],
        )

        plan = AgentPlanner().plan(PlanningContext(topology=topology(app("api")), intent=intent))

        actions = [(task.component_id, task.action, task.reason_code) for task in plan.tasks]
        self.assertIn(("api", "ask_user", "external_exposure_requires_confirmation"), actions)
        self.assertIn(("db", "blocker", "stateful_requires_design_review"), actions)

    def test_topology_runtime_command_conflict_creates_semantic_action(self):
        conflict = TopologyConflict(
            field_path="/components/api/runtime/command",
            reason="conflicting_runtime_commands",
            evidence_refs=["F001", "F002"],
        )
        intent = IntentBuilder().build(topology(app("api"), conflicts=[conflict]), Target.DEVELOPMENT)

        plan = AgentPlanner().plan(PlanningContext(topology=topology(app("api"), conflicts=[conflict]), intent=intent))

        semantic = [task for task in plan.tasks if task.action == "semantic_action"]
        self.assertEqual(len(semantic), 1)
        self.assertEqual(semantic[0].component_id, "api")
        self.assertEqual(semantic[0].tool, "resolve_runtime_command")
        self.assertEqual(semantic[0].evidence_refs, ["F001", "F002"])

    def test_missing_dockerfile_build_strategy_creates_build_strategy_question(self):
        topo = topology(app("api", build_strategy="source_only"))
        intent = IntentBuilder().build(topo, Target.DEVELOPMENT)

        plan = AgentPlanner().plan(PlanningContext(topology=topo, intent=intent))

        self.assertIn("ask_build_strategy", [task.reason_code for task in plan.tasks])


def candidate(component_id: str, kind: str, disposition: str, evidence_refs: list[str]) -> IntentCandidate:
    return IntentCandidate(
        candidate_id=f"{component_id}/{kind}",
        component_id=component_id,
        kind=kind,
        field_path=f"/components/{component_id}/{kind}",
        value=True,
        source="test",
        confidence="high",
        classification="rule_inference",
        evidence_refs=evidence_refs,
        decision=PolicyDecision(disposition=disposition, reason_code=f"{kind}_requires_confirmation" if disposition == "requires_confirmation" else "stateful_requires_design_review", policy_version="target-policy/v1"),
    )


if __name__ == "__main__":
    unittest.main()
