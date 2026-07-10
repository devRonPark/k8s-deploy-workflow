from __future__ import annotations

from pathlib import Path

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet
from preanalyzer.models.semantic import EvidenceReference, SemanticTask, SemanticTaskBudget, SemanticTaskType, TaskReason


def write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


def fact(evidence_id: str, artifact_ref: str = "backend/Dockerfile") -> EvidenceFact:
    return EvidenceFact(
        evidence_id=evidence_id,
        fact_type="dockerfile_cmd",
        artifact_ref=artifact_ref,
        source="dockerfile_cmd",
        classification="observed_fact",
        value='["./entrypoint.sh"]',
    )


def evidence_model(*evidence_ids: str) -> EvidenceModel:
    return EvidenceModel(facts=[fact(evidence_id) for evidence_id in evidence_ids])


def rules_for(component_id: str = "backend", root_path: str | None = "backend") -> RuleInferenceSet:
    return RuleInferenceSet(
        component_candidates=[
            ComponentCandidate(component_id=component_id, root_path=root_path, source="test", evidence_refs=["F001"]),
        ]
    )


def task(
    *,
    component_id: str = "backend",
    allowed_tools: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    max_source_lines: int = 40,
) -> SemanticTask:
    refs = evidence_refs or ["F001"]
    return SemanticTask(
        task_id="ST-TOOLS",
        task_type=SemanticTaskType.RESOLVE_RUNTIME_COMMAND,
        component_id=component_id,
        target_field="/components/backend/runtime/command",
        reason=TaskReason(
            code="shell_script_entrypoint",
            description="test task",
            evidence_refs=refs,
        ),
        evidence_refs=[EvidenceReference(evidence_id=ref, origin="phase1") for ref in refs],
        allowed_tools=allowed_tools or [
            "search_code",
            "read_source_range",
            "inspect_entrypoint_script",
            "find_command_target",
        ],
        budget=SemanticTaskBudget(max_source_lines=max_source_lines),
    )
