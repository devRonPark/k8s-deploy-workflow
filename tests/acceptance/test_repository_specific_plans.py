from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.agent.planner import AgentPlanner, PlanningContext
from k8s_agent.analysis.intent_builder import IntentBuilder
from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.store import RunStore


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 13, 6, 7, 8, tzinfo=timezone.utc)


def source_for(path: Path) -> RepositorySource:
    return RepositorySource(
        kind="local",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=False),
        fingerprint=SourceFingerprint(value="sha256:test", file_count=1),
    )


def plan_for(repo_name: str, target: str = "development"):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = RunStore(root / "runs")
        run_id = f"run-{repo_name}"
        store.run_path(run_id).mkdir(parents=True)
        phase1 = Phase1Adapter(store=store, clock=lambda: FIXED_TIME).run(source_for(FIXTURES / repo_name), run_id)
        topology = TopologyBuilder().build(phase1)
        intent = IntentBuilder().build(topology, target)
        return AgentPlanner().plan(PlanningContext(topology=topology, intent=intent))


class RepositorySpecificPlanTests(unittest.TestCase):
    def test_single_service_plan_generates_and_validates(self):
        plan = plan_for("node-express-like")

        self.assertIn("generate_manifests", [task.action for task in plan.tasks])
        self.assertIn("validate_manifests", [task.action for task in plan.tasks])

    def test_monorepo_dependency_plan_contains_secret_question_and_blocker(self):
        plan = plan_for("fastapi-fullstack-like")

        by_reason = [task.reason_code for task in plan.tasks]
        self.assertIn("secret_ref_requires_confirmation", by_reason)
        self.assertIn("stateful_requires_design_review", by_reason)

    def test_shell_entrypoint_plan_routes_runtime_command_to_semantic_action(self):
        plan = plan_for("fastapi-shell-entrypoint")

        semantic = [task for task in plan.tasks if task.action == "semantic_action"]
        self.assertEqual([task.tool for task in semantic], ["resolve_runtime_command"])

    def test_jpetstore_plan_asks_for_build_strategy(self):
        plan = plan_for("jpetstore-like")

        self.assertIn("ask_build_strategy", [task.reason_code for task in plan.tasks])

    def test_production_plan_omits_cluster_validation(self):
        plan = plan_for("node-express-like", target="production")

        self.assertNotIn("validate_manifests", [task.action for task in plan.tasks])


if __name__ == "__main__":
    unittest.main()
