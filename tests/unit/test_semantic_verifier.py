from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.semantic import (
    EvidenceReference,
    KnownCandidate,
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
    SemanticTask,
    SemanticTaskBudget,
    SemanticTaskType,
    TaskReason,
    VerificationStatus,
)
from preanalyzer.models.semantic_tools import (
    SemanticToolEvidence,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
)
from preanalyzer.semantic.tools.common import line_excerpt, make_evidence, redacted
from preanalyzer.semantic.verifier import verify_semantic_resolution


def phase1_fact(
    evidence_id: str = "F001",
    *,
    fact_type: str = "dockerfile_cmd",
    artifact_ref: str = "backend/Dockerfile",
    source: str = "dockerfile_cmd",
    value="uvicorn main:app --host 0.0.0.0",
) -> EvidenceFact:
    return EvidenceFact(
        evidence_id=evidence_id,
        fact_type=fact_type,
        artifact_ref=artifact_ref,
        source=source,
        classification="observed_fact",
        value=value,
    )


def evidence_model(*facts: EvidenceFact) -> EvidenceModel:
    return EvidenceModel(facts=list(facts or [phase1_fact()]))


def known_candidate(
    value: str = "python -m deterministic",
    *,
    confidence: str = "high",
    evidence_refs: list[str] | None = None,
) -> KnownCandidate:
    return KnownCandidate(
        value=value,
        source="deterministic_runtime_command_analysis",
        confidence=confidence,
        classification="deterministic_runtime_command_analysis",
        evidence_refs=evidence_refs or ["F001"],
    )


def task(
    *,
    task_id: str = "ST-001",
    component_id: str = "backend",
    target_field: str = "/components/backend/runtime/command",
    evidence_refs: list[EvidenceReference] | None = None,
    known_candidates: list[KnownCandidate] | None = None,
    allowed_tools: list[str] | None = None,
) -> SemanticTask:
    refs = evidence_refs or [EvidenceReference(evidence_id="F001", origin="phase1")]
    return SemanticTask(
        task_id=task_id,
        task_type=SemanticTaskType.RESOLVE_RUNTIME_COMMAND,
        component_id=component_id,
        target_field=target_field,
        reason=TaskReason(code="shell_script_entrypoint", description="test task", evidence_refs=["F001"]),
        known_candidates=known_candidates or [],
        evidence_refs=refs,
        allowed_tools=allowed_tools or ["inspect_entrypoint_script", "read_source_range", "search_code"],
        budget=SemanticTaskBudget(max_source_lines=40),
    )


def candidate(
    candidate_id: str = "SC-001",
    *,
    component_id: str = "backend",
    target_field: str = "/components/backend/runtime/command",
    command: str = "uvicorn main:app --host 0.0.0.0",
    evidence_refs: list[str] | None = None,
    confidence: str = "medium",
    supporting_observations: list[str] | None = None,
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        component_id=component_id,
        target_field=target_field,
        value={"command": command},
        classification="llm_semantic_inference",
        confidence=confidence,
        evidence_refs=evidence_refs or ["F001"],
        supporting_observations=supporting_observations or [],
        contradicting_observations=[],
    )


def resolution(
    *,
    task_id: str = "ST-001",
    status: SemanticResolutionStatus = SemanticResolutionStatus.RESOLVED,
    candidates: list[SemanticCandidate] | None = None,
    recommended_candidate_id: str | None = "SC-001",
    analysis_summary: str | None = "summary",
    tool_trace_refs: list[str] | None = None,
) -> SemanticResolution:
    return SemanticResolution(
        task_id=task_id,
        status=status,
        candidates=candidates if candidates is not None else [candidate()],
        recommended_candidate_id=recommended_candidate_id,
        analysis_summary=analysis_summary,
        tool_trace_refs=tool_trace_refs or [],
    )


def tool_result(
    evidence: list[SemanticToolEvidence],
    *,
    tool_name: SemanticToolName = SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT,
    status: SemanticToolResultStatus = SemanticToolResultStatus.OK,
    observations: list[dict] | None = None,
) -> SemanticToolResult:
    return SemanticToolResult(
        tool_name=tool_name,
        status=status,
        evidence=evidence,
        observations=observations or [],
    )


class DummyContext:
    def __init__(self, repo: Path):
        self.repository_root = repo.resolve()


class SemanticVerifierTests(unittest.TestCase):
    def verify(self, repo: Path, task_obj: SemanticTask, resolution_obj: SemanticResolution, *, facts=None, tool_results=None):
        return verify_semantic_resolution(
            repository_root=repo,
            task=task_obj,
            resolution=resolution_obj,
            phase1_evidence=evidence_model(*(facts or [phase1_fact()])),
            tool_results=tool_results or [],
        )

    def assert_candidate_rejected(self, result, candidate_id: str, reason: str):
        by_id = {item.candidate_id: item for item in result.candidate_results}
        self.assertFalse(by_id[candidate_id].accepted)
        self.assertIn(reason, by_id[candidate_id].reason_codes)

    def test_resolved_candidate_grounded_by_phase1_command_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task(), resolution())

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)
        self.assertEqual(result.accepted_candidate_ids, ["SC-001"])
        self.assertEqual(result.candidate_results[0].verified_evidence_refs, ["F001"])

    def test_task_id_mismatch_rejects_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task(), resolution(task_id="ST-OTHER"))

        self.assertEqual(result.status, VerificationStatus.REJECTED)
        self.assertIn("task_id_mismatch", result.reasons)
        self.assertEqual(result.accepted_candidate_ids, [])

    def test_component_and_target_field_mismatch_reject_candidate(self):
        candidates = [
            candidate("SC-COMP", component_id="worker"),
            candidate("SC-FIELD", target_field="/components/backend/runtime/port"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(
                Path(tmp),
                task(),
                resolution(candidates=candidates, recommended_candidate_id="SC-COMP"),
            )

        self.assertEqual(result.status, VerificationStatus.REJECTED)
        self.assert_candidate_rejected(result, "SC-COMP", "component_mismatch")
        self.assert_candidate_rejected(result, "SC-FIELD", "target_field_mismatch")

    def test_schema_rejects_wrong_classification_and_high_confidence(self):
        with self.assertRaises(ValidationError):
            SemanticCandidate(
                candidate_id="SC-BAD",
                component_id="backend",
                target_field="/components/backend/runtime/command",
                value={"command": "uvicorn main:app"},
                classification="rule_inference",
                confidence="medium",
            )
        with self.assertRaises(ValidationError):
            candidate(confidence="high")

    def test_recommended_candidate_failure_rejects_resolved_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(
                Path(tmp),
                task(),
                resolution(candidates=[candidate(command="gunicorn missing:app")]),
            )

        self.assertEqual(result.status, VerificationStatus.REJECTED)
        self.assertEqual(result.accepted_candidate_ids, [])
        self.assert_candidate_rejected(result, "SC-001", "candidate_not_grounded")

    def test_phase1_reference_must_exist_and_be_in_task_scope(self):
        scoped = task(evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1")])
        outside = resolution(candidates=[candidate(evidence_refs=["F002"])])
        missing = resolution(candidates=[candidate(evidence_refs=["F999"])])
        with tempfile.TemporaryDirectory() as tmp:
            outside_result = self.verify(Path(tmp), scoped, outside, facts=[phase1_fact("F001"), phase1_fact("F002")])
            missing_result = self.verify(Path(tmp), scoped, missing, facts=[phase1_fact("F001")])

        self.assert_candidate_rejected(outside_result, "SC-001", "evidence_outside_task_scope")
        self.assert_candidate_rejected(missing_result, "SC-001", "unknown_evidence_reference")

    def test_known_candidate_evidence_reference_is_in_scope(self):
        task_obj = task(known_candidates=[known_candidate(value="uvicorn main:app --host 0.0.0.0", evidence_refs=["F010"])])
        resolution_obj = resolution(candidates=[candidate(evidence_refs=["F010"])])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task_obj, resolution_obj, facts=[phase1_fact("F001"), phase1_fact("F010")])

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)
        self.assertEqual(result.accepted_candidate_ids, ["SC-001"])

    def test_phase1_line_metadata_is_not_invented(self):
        task_obj = task(evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1")])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task_obj, resolution())

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)

    def test_unrelated_phase1_fact_type_does_not_ground_command(self):
        fact = phase1_fact(fact_type="framework", source="package_json", value={"framework": "fastapi"})
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task(), resolution(), facts=[fact])

        self.assert_candidate_rejected(result, "SC-001", "candidate_not_grounded")

    def test_semantic_tool_evidence_is_revalidated_against_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "backend" / "entrypoint.sh"
            path.parent.mkdir()
            path.write_text("exec uvicorn main:app --host 0.0.0.0\n", encoding="utf-8")
            evidence = make_evidence(
                SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT,
                DummyContext(repo),
                path,
                1,
                1,
                line_excerpt(path.read_text(encoding="utf-8").splitlines(), 1, 1),
            )
            task_obj = task(
                evidence_refs=[
                    EvidenceReference(evidence_id="F001", origin="phase1"),
                    EvidenceReference(
                        evidence_id=evidence.evidence_id,
                        origin="semantic_tool",
                        path=evidence.path,
                        start_line=1,
                        end_line=1,
                    ),
                ]
            )
            resolution_obj = resolution(
                candidates=[candidate(evidence_refs=[evidence.evidence_id])],
                tool_trace_refs=[evidence.evidence_id],
            )
            result = self.verify(
                repo,
                task_obj,
                resolution_obj,
                tool_results=[
                    tool_result(
                        [evidence],
                        observations=[{"command_text": "exec uvicorn main:app --host 0.0.0.0", "evidence_ref": evidence.evidence_id}],
                    )
                ],
            )

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)
        self.assertEqual(result.accepted_candidate_ids, ["SC-001"])

    def test_semantic_tool_evidence_rejects_missing_unallowed_and_bad_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            fake = SemanticToolEvidence(
                evidence_id="SE-FAKE",
                tool_name=SemanticToolName.SEARCH_CODE,
                path="backend/app.py",
                start_line=1,
                end_line=1,
                excerpt="1: uvicorn main:app",
                excerpt_hash="bad",
            )
            base_task = task(
                allowed_tools=["inspect_entrypoint_script"],
                evidence_refs=[
                    EvidenceReference(evidence_id="F001", origin="phase1"),
                    EvidenceReference(evidence_id="SE-FAKE", origin="semantic_tool", path="backend/app.py", start_line=1, end_line=1),
                ],
            )
            resolution_obj = resolution(candidates=[candidate(evidence_refs=["SE-FAKE"])], tool_trace_refs=["SE-FAKE"])
            missing = self.verify(repo, base_task, resolution_obj)
            unallowed = self.verify(repo, base_task, resolution_obj, tool_results=[tool_result([fake], tool_name=SemanticToolName.SEARCH_CODE)])
            bad_status = self.verify(
                repo,
                task(allowed_tools=["search_code"], evidence_refs=base_task.evidence_refs),
                resolution_obj,
                tool_results=[tool_result([fake], tool_name=SemanticToolName.SEARCH_CODE, status=SemanticToolResultStatus.NO_MATCH)],
            )

        self.assert_candidate_rejected(missing, "SC-001", "unknown_evidence_reference")
        self.assert_candidate_rejected(unallowed, "SC-001", "tool_not_allowed")
        self.assert_candidate_rejected(bad_status, "SC-001", "invalid_tool_trace_reference")

    def test_semantic_tool_evidence_rejects_path_and_hash_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = repo / "backend"
            backend.mkdir()
            (backend / "entrypoint.sh").write_text("exec uvicorn main:app\n", encoding="utf-8")
            bad_path = SemanticToolEvidence(
                evidence_id="SE-PATH",
                tool_name=SemanticToolName.READ_SOURCE_RANGE,
                path="../outside.sh",
                start_line=1,
                end_line=1,
                excerpt="1: exec uvicorn main:app",
                excerpt_hash="bad",
            )
            bad_hash = SemanticToolEvidence(
                evidence_id="SE-HASH",
                tool_name=SemanticToolName.READ_SOURCE_RANGE,
                path="backend/entrypoint.sh",
                start_line=1,
                end_line=1,
                excerpt="1: exec uvicorn main:app",
                excerpt_hash="bad",
            )
            refs = [
                EvidenceReference(evidence_id="F001", origin="phase1"),
                EvidenceReference(evidence_id="SE-PATH", origin="semantic_tool", path="../outside.sh", start_line=1, end_line=1),
                EvidenceReference(evidence_id="SE-HASH", origin="semantic_tool", path="backend/entrypoint.sh", start_line=1, end_line=1),
            ]
            path_result = self.verify(
                repo,
                task(evidence_refs=refs),
                resolution(candidates=[candidate(evidence_refs=["SE-PATH"])], tool_trace_refs=["SE-PATH"]),
                tool_results=[tool_result([bad_path], tool_name=SemanticToolName.READ_SOURCE_RANGE)],
            )
            hash_result = self.verify(
                repo,
                task(evidence_refs=refs),
                resolution(candidates=[candidate(evidence_refs=["SE-HASH"])], tool_trace_refs=["SE-HASH"]),
                tool_results=[tool_result([bad_hash], tool_name=SemanticToolName.READ_SOURCE_RANGE)],
            )

        self.assert_candidate_rejected(path_result, "SC-001", "tool_evidence_path_invalid")
        self.assert_candidate_rejected(hash_result, "SC-001", "tool_evidence_hash_mismatch")

    def test_semantic_tool_evidence_rejects_line_range_missing_file_and_content_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "backend" / "entrypoint.sh"
            path.parent.mkdir()
            path.write_text("exec uvicorn main:app\n", encoding="utf-8")
            valid_excerpt = line_excerpt(path.read_text(encoding="utf-8").splitlines(), 1, 1)
            changed = make_evidence(SemanticToolName.READ_SOURCE_RANGE, DummyContext(repo), path, 1, 1, valid_excerpt)
            path.write_text("exec gunicorn app:app\n", encoding="utf-8")
            bad_range = SemanticToolEvidence(
                evidence_id="SE-RANGE",
                tool_name=SemanticToolName.READ_SOURCE_RANGE,
                path="backend/entrypoint.sh",
                start_line=99,
                end_line=99,
                excerpt="99: no",
                excerpt_hash="bad",
            )
            missing = SemanticToolEvidence(
                evidence_id="SE-MISSING",
                tool_name=SemanticToolName.READ_SOURCE_RANGE,
                path="backend/missing.sh",
                start_line=1,
                end_line=1,
                excerpt="1: exec uvicorn main:app",
                excerpt_hash="bad",
            )
            refs = [
                EvidenceReference(evidence_id="F001", origin="phase1"),
                EvidenceReference(evidence_id=changed.evidence_id, origin="semantic_tool", path=changed.path, start_line=1, end_line=1),
                EvidenceReference(evidence_id="SE-RANGE", origin="semantic_tool", path="backend/entrypoint.sh", start_line=99, end_line=99),
                EvidenceReference(evidence_id="SE-MISSING", origin="semantic_tool", path="backend/missing.sh", start_line=1, end_line=1),
            ]
            changed_result = self.verify(repo, task(evidence_refs=refs), resolution(candidates=[candidate(evidence_refs=[changed.evidence_id])], tool_trace_refs=[changed.evidence_id]), tool_results=[tool_result([changed], tool_name=SemanticToolName.READ_SOURCE_RANGE)])
            range_result = self.verify(repo, task(evidence_refs=refs), resolution(candidates=[candidate(evidence_refs=["SE-RANGE"])], tool_trace_refs=["SE-RANGE"]), tool_results=[tool_result([bad_range], tool_name=SemanticToolName.READ_SOURCE_RANGE)])
            missing_result = self.verify(repo, task(evidence_refs=refs), resolution(candidates=[candidate(evidence_refs=["SE-MISSING"])], tool_trace_refs=["SE-MISSING"]), tool_results=[tool_result([missing], tool_name=SemanticToolName.READ_SOURCE_RANGE)])

        self.assert_candidate_rejected(changed_result, "SC-001", "tool_evidence_hash_mismatch")
        self.assert_candidate_rejected(range_result, "SC-001", "tool_evidence_range_invalid")
        self.assert_candidate_rejected(missing_result, "SC-001", "tool_evidence_path_invalid")

    def test_redaction_is_reapplied_before_hashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "backend" / "entrypoint.sh"
            path.parent.mkdir()
            path.write_text("PASSWORD=supersecret\nexec uvicorn main:app\n", encoding="utf-8")
            excerpt = line_excerpt(path.read_text(encoding="utf-8").splitlines(), 1, 2)
            self.assertIn("[REDACTED]", excerpt)
            evidence = make_evidence(SemanticToolName.READ_SOURCE_RANGE, DummyContext(repo), path, 1, 2, excerpt)
            task_obj = task(evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1"), EvidenceReference(evidence_id=evidence.evidence_id, origin="semantic_tool", path=evidence.path, start_line=1, end_line=2)])
            result = self.verify(repo, task_obj, resolution(candidates=[candidate(command="uvicorn main:app", evidence_refs=[evidence.evidence_id])], tool_trace_refs=[evidence.evidence_id]), tool_results=[tool_result([evidence], tool_name=SemanticToolName.READ_SOURCE_RANGE)])

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)

    def test_grounding_accepts_structured_observation_normalization_phase1_and_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "backend" / "entrypoint.sh"
            path.parent.mkdir()
            path.write_text("exec   'uvicorn'   main:app\n", encoding="utf-8")
            excerpt = line_excerpt(path.read_text(encoding="utf-8").splitlines(), 1, 1)
            evidence = make_evidence(SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT, DummyContext(repo), path, 1, 1, excerpt)
            task_obj = task(evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1"), EvidenceReference(evidence_id=evidence.evidence_id, origin="semantic_tool", path=evidence.path, start_line=1, end_line=1)])
            result = self.verify(
                repo,
                task_obj,
                resolution(candidates=[candidate(command="uvicorn main:app", evidence_refs=[evidence.evidence_id])], tool_trace_refs=[evidence.evidence_id]),
                tool_results=[tool_result([evidence], observations=[{"command_text": "exec   'uvicorn'   main:app", "evidence_ref": evidence.evidence_id}])],
            )

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)

    def test_keyword_partial_match_synthesis_and_free_text_are_not_grounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            keyword = phase1_fact(value="documentation mentions gunicorn")
            partial = self.verify(Path(tmp), task(), resolution(candidates=[candidate(command="gunicorn app:server")]), facts=[keyword])
            free_text = self.verify(
                Path(tmp),
                task(),
                resolution(candidates=[candidate(command="gunicorn app:server", supporting_observations=["I saw gunicorn app:server in code"])]),
                facts=[phase1_fact(value="unrelated")],
            )

        self.assert_candidate_rejected(partial, "SC-001", "candidate_not_grounded")
        self.assert_candidate_rejected(free_text, "SC-001", "candidate_not_grounded")

    def test_secret_detection_rejects_literals_but_allows_env_var_references(self):
        allowed = candidate(command='uvicorn main:app --password "$DB_PASSWORD"')
        literal_password = candidate(command="uvicorn main:app --password supersecret")
        bearer = candidate(command="curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456'")
        private = candidate(command="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            allowed_result = self.verify(repo, task(), resolution(candidates=[allowed]), facts=[phase1_fact(value='uvicorn main:app --password "$DB_PASSWORD"')])
            password_result = self.verify(repo, task(), resolution(candidates=[literal_password]), facts=[phase1_fact(value="uvicorn main:app --password supersecret")])
            bearer_result = self.verify(repo, task(), resolution(candidates=[bearer]), facts=[phase1_fact(value="curl")])
            private_result = self.verify(repo, task(), resolution(candidates=[private]), facts=[phase1_fact(value="private")])

        self.assertEqual(allowed_result.status, VerificationStatus.ACCEPTED)
        self.assert_candidate_rejected(password_result, "SC-001", "secret_value_detected")
        self.assert_candidate_rejected(bearer_result, "SC-001", "secret_value_detected")
        self.assert_candidate_rejected(private_result, "SC-001", "secret_value_detected")
        self.assertNotIn("supersecret", str(password_result.model_dump()))

    def test_secret_in_summary_rejects_entire_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task(), resolution(analysis_summary="Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"))

        self.assertEqual(result.status, VerificationStatus.REJECTED)
        self.assertIn("secret_value_detected", result.reasons)

    def test_deterministic_conflict_warns_without_mutating_or_escalating(self):
        kc = known_candidate(value="python -m deterministic", confidence="high")
        task_obj = task(known_candidates=[kc])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.verify(Path(tmp), task_obj, resolution(), facts=[phase1_fact(value="uvicorn main:app --host 0.0.0.0")])

        self.assertEqual(result.status, VerificationStatus.ACCEPTED)
        self.assertIn("deterministic_candidate_conflict", result.candidate_results[0].warnings)
        self.assertEqual(task_obj.known_candidates[0], kc)
        self.assertEqual(resolution().candidates[0].confidence, "medium")

    def test_ambiguous_and_unresolved_status_mapping(self):
        candidates = [candidate("SC-001"), candidate("SC-002", command="python worker.py")]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            ambiguous = self.verify(repo, task(), resolution(status=SemanticResolutionStatus.AMBIGUOUS, candidates=candidates, recommended_candidate_id=None), facts=[phase1_fact(value="uvicorn main:app --host 0.0.0.0"), phase1_fact("F002", value="python worker.py")])
            insufficient = self.verify(repo, task(), SemanticResolution(task_id="ST-001", status=SemanticResolutionStatus.INSUFFICIENT_EVIDENCE))
            exhausted = self.verify(repo, task(), SemanticResolution(task_id="ST-001", status=SemanticResolutionStatus.BUDGET_EXHAUSTED))
            tool_error = self.verify(repo, task(), SemanticResolution(task_id="ST-001", status=SemanticResolutionStatus.TOOL_ERROR))

        self.assertEqual(ambiguous.status, VerificationStatus.AMBIGUOUS)
        self.assertEqual(insufficient.status, VerificationStatus.INSUFFICIENT_EVIDENCE)
        self.assertEqual(exhausted.status, VerificationStatus.BUDGET_EXHAUSTED)
        self.assertEqual(tool_error.status, VerificationStatus.TOOL_ERROR)
        self.assertEqual(insufficient.accepted_candidate_ids, [])

    def test_ambiguous_with_one_valid_candidate_stays_ambiguous_and_zero_valid_rejects(self):
        candidates = [candidate("SC-001"), candidate("SC-002", command="missing command")]
        with tempfile.TemporaryDirectory() as tmp:
            one_valid = self.verify(Path(tmp), task(), resolution(status=SemanticResolutionStatus.AMBIGUOUS, candidates=candidates, recommended_candidate_id=None))
            zero_valid = self.verify(Path(tmp), task(), resolution(status=SemanticResolutionStatus.AMBIGUOUS, candidates=[candidate("SC-001", command="nope"), candidate("SC-002", command="missing")], recommended_candidate_id=None))

        self.assertEqual(one_valid.status, VerificationStatus.AMBIGUOUS)
        self.assertEqual(one_valid.accepted_candidate_ids, ["SC-001"])
        self.assertEqual(zero_valid.status, VerificationStatus.REJECTED)

    def test_tool_trace_refs_must_be_existing_task_scoped_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            missing = self.verify(repo, task(), resolution(tool_trace_refs=["SE-MISSING"]))
            unrelated = self.verify(repo, task(), resolution(tool_trace_refs=["F001"]))

        self.assertEqual(missing.status, VerificationStatus.REJECTED)
        self.assertIn("invalid_tool_trace_reference", missing.reasons)
        self.assertIn("invalid_tool_trace_reference", unrelated.reasons)

    def test_result_invariants_serialization_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            first = self.verify(repo, task(), resolution())
            second = self.verify(repo, task(), resolution())
            dumped = first.model_dump()

        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(first.accepted_candidate_ids, [item.candidate_id for item in first.candidate_results if item.accepted])
        self.assertEqual(dumped["status"], "accepted")
        self.assertEqual(first.__class__.model_validate(dumped).model_dump(), dumped)


if __name__ == "__main__":
    unittest.main()
