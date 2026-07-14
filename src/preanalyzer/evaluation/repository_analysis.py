from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.models.topology import ApplicationComponent, ApplicationTopology
from preanalyzer.analyzer.env_safety import contains_credentials, is_secret_name
from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.semantic.tools.common import redacted


DEFAULT_QUALITY_THRESHOLDS = {
    "core_field_accountability_rate": 1.0,
    "core_resolution_rate": 0.9,
    "extended_resolution_rate": 0.8,
    "auto_confirmed_accuracy": 0.9,
    "evidence_reference_accuracy": 1.0,
    "max_ungrounded_auto_confirmed_count": 0.0,
}

FieldState = Literal["resolved", "not_applicable", "conflict", "unresolved", "missing"]


class CorpusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    reason: str = Field(min_length=1)
    affected_cases: list[str] = Field(min_length=1)


class ExpectedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    group: Literal["core", "extended"]
    variant: str = "common"
    expected_state: Literal["resolved", "not_applicable", "conflict", "unresolved"]
    expected_value: Any | None = None
    expected_evidence: list["ExpectedEvidenceReference"] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_secret_values(self) -> "ExpectedField":
        if not self.expected_evidence:
            raise ValueError("expert truth fields require precise expected_evidence")
        if self.expected_state == "resolved" and is_secret_name(self.field_id):
            if not self.field_id.endswith("classification"):
                raise ValueError("secret truth may record classification metadata only")
            if self.expected_value not in {"secret", "non_secret"}:
                raise ValueError("secret classification must not contain a secret value")
        if _contains_sensitive_value(self.expected_value):
            raise ValueError("expert truth must not contain secret values")
        return self


class ExpectedEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class RepositoryCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    visibility: Literal["public", "internal", "contract"]
    revision: str
    repository_url: str | None = None
    content_sha256: str | None = None
    scenario: Literal["normal", "absence", "conflict", "coverage_gap"] | None = None
    artifact_types: list[
        Literal[
            "dockerfile",
            "docker_compose",
            "maven",
            "gradle_groovy",
            "gradle_kotlin",
            "node_package",
            "python_package",
            "application_config",
            "kubernetes_manifest",
            "kustomize",
        ]
    ] = Field(default_factory=list)
    fields: list[ExpectedField] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fixed_source(self) -> "RepositoryCase":
        if self.visibility in {"public", "internal"} and not re.fullmatch(
            r"[0-9a-f]{40}", self.revision
        ):
            raise ValueError("real repository cases require an immutable commit revision")
        if self.visibility == "public" and not self.repository_url:
            raise ValueError("public repository cases require repository_url")
        return self


class RepositoryCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-corpus/v1"]
    corpus_version: str
    change_history: list[CorpusChange] = Field(min_length=1)
    cases: list[RepositoryCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_change_history(self) -> "RepositoryCorpus":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("repository corpus case_id values must be unique")
        latest = self.change_history[-1]
        if latest.version != self.corpus_version:
            raise ValueError("latest change history version must match corpus_version")
        versions = [change.version for change in self.change_history]
        if len(versions) != len(set(versions)):
            raise ValueError("change history versions must be unique")
        for change in self.change_history:
            unknown = sorted(set(change.affected_cases) - set(case_ids))
            if unknown:
                raise ValueError(
                    f"change history references unknown cases: {', '.join(unknown)}"
                )
        return self


class FieldScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    group: Literal["core", "extended"]
    variant: str
    expected_state: FieldState
    expected_value: Any | None = None
    actual_state: FieldState
    actual_value: Any | None = None
    source: str | None = None
    confidence: str | None = None
    classification: str | None = None
    correct: bool
    evidence_references: list["ActualEvidenceReference"] = Field(default_factory=list)
    evidence_correct: bool | None = None


class ActualEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    artifact: str
    locator: str | None = None


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    visibility: str
    revision: str
    fields: list[FieldScore]


class ScorecardMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_field_accountability_rate: float
    core_resolution_rate: float
    extended_resolution_rate: float
    auto_confirmed_accuracy: float
    evidence_reference_accuracy: float
    ungrounded_auto_confirmed_count: int


class RepositoryScorecardReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-scorecard/v1"] = "repository-analysis-scorecard/v1"
    corpus_version: str
    generated_at: datetime
    case_count: int
    thresholds: dict[str, float]
    metrics: ScorecardMetrics
    quality_gate_passed: bool
    cases: list[CaseScore]


class _ActualField(BaseModel):
    state: FieldState = "missing"
    value: Any | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: str | None = None
    classification: str | None = None


class CorpusLockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    content_sha256: str
    scoring_rules_sha256: str
    reason: str
    affected_cases: list[str]


class RepositoryCorpusLock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-corpus-lock/v1"] = (
        "repository-analysis-corpus-lock/v1"
    )
    entries: list[CorpusLockEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_versions(self) -> "RepositoryCorpusLock":
        versions = [entry.version for entry in self.entries]
        if len(versions) != len(set(versions)):
            raise ValueError("corpus lock versions must be unique")
        return self


class HumanBaselineMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["manual", "agent"]
    operator_id: str
    status: Literal["pending", "measured"]
    total_seconds: float | None = Field(default=None, ge=0)
    hands_on_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_timing(self) -> "HumanBaselineMeasurement":
        if self.status == "measured":
            if self.total_seconds is None or self.hands_on_seconds is None:
                raise ValueError("measured runs require total_seconds and hands_on_seconds")
            if self.hands_on_seconds > self.total_seconds:
                raise ValueError("hands_on_seconds cannot exceed total_seconds")
        elif self.total_seconds is not None or self.hands_on_seconds is not None:
            raise ValueError("pending runs cannot contain timing values")
        return self


class HumanBaselineCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    measurements: list[HumanBaselineMeasurement]

    @model_validator(mode="after")
    def validate_cross_over(self) -> "HumanBaselineCase":
        if len(self.measurements) != 2:
            raise ValueError("each case requires exactly two measurements")
        methods = {measurement.method for measurement in self.measurements}
        if methods != {"manual", "agent"}:
            raise ValueError("each case requires manual and agent measurements")
        manual_operators = {
            item.operator_id for item in self.measurements if item.method == "manual"
        }
        agent_operators = {
            item.operator_id for item in self.measurements if item.method == "agent"
        }
        if manual_operators & agent_operators:
            raise ValueError("manual and agent measurements require different operators")
        return self


class HumanBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-human-baseline/v1"]
    corpus_version: str
    cases: list[HumanBaselineCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids_and_operator_rotation(self) -> "HumanBaseline":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("human baseline case_id values must be unique")
        if len(self.cases) > 1:
            methods_by_operator: dict[str, set[str]] = {}
            for case in self.cases:
                for measurement in case.measurements:
                    methods_by_operator.setdefault(measurement.operator_id, set()).add(
                        measurement.method
                    )
            if any(methods != {"manual", "agent"} for methods in methods_by_operator.values()):
                raise ValueError("each operator must rotate through manual and agent methods")
        return self


def load_repository_corpus(corpus_path: Path) -> RepositoryCorpus:
    payload = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    return RepositoryCorpus.model_validate(payload)


def initialize_repository_corpus_lock(corpus_path: Path, lock_path: Path) -> RepositoryCorpusLock:
    corpus = load_repository_corpus(corpus_path)
    if len(corpus.change_history) != 1:
        raise ValueError("initial corpus lock requires exactly one change history entry")
    latest = corpus.change_history[-1]
    lock = RepositoryCorpusLock(
        entries=[
            CorpusLockEntry(
                version=corpus.corpus_version,
                content_sha256=_content_hash(corpus_path),
                scoring_rules_sha256=_scoring_rules_hash(),
                reason=latest.reason,
                affected_cases=latest.affected_cases,
            )
        ]
    )
    _write_corpus_lock(lock_path, lock)
    return lock


def verify_repository_corpus_lock(corpus_path: Path, lock_path: Path) -> RepositoryCorpusLock:
    corpus = load_repository_corpus(corpus_path)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    lock = RepositoryCorpusLock.model_validate(payload)
    _verify_lock_history(corpus, lock)
    latest = lock.entries[-1]
    if latest.version != corpus.corpus_version:
        raise ValueError("corpus lock version does not match corpus_version")
    if latest.content_sha256 != _content_hash(corpus_path):
        raise ValueError("corpus content hash does not match the locked truth")
    if latest.scoring_rules_sha256 != _scoring_rules_hash():
        raise ValueError("scoring rules hash does not match the lock")
    history = corpus.change_history[-1]
    if latest.reason != history.reason or latest.affected_cases != history.affected_cases:
        raise ValueError("corpus lock change metadata does not match change_history")
    return lock


def update_repository_corpus_lock(corpus_path: Path, lock_path: Path) -> RepositoryCorpusLock:
    corpus = load_repository_corpus(corpus_path)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    lock = RepositoryCorpusLock.model_validate(payload)
    if corpus.corpus_version in {entry.version for entry in lock.entries}:
        raise ValueError("changed truth requires a new corpus version")
    if len(corpus.change_history) != len(lock.entries) + 1:
        raise ValueError("corpus update requires exactly one new change history entry")
    for history, entry in zip(corpus.change_history[:-1], lock.entries, strict=True):
        if (
            history.version != entry.version
            or history.reason != entry.reason
            or history.affected_cases != entry.affected_cases
        ):
            raise ValueError("existing corpus change history does not match the lock")
    latest = corpus.change_history[-1]
    updated = lock.model_copy(
        update={
            "entries": lock.entries
            + [
                CorpusLockEntry(
                    version=corpus.corpus_version,
                    content_sha256=_content_hash(corpus_path),
                    scoring_rules_sha256=_scoring_rules_hash(),
                    reason=latest.reason,
                    affected_cases=latest.affected_cases,
                )
            ]
        }
    )
    _write_corpus_lock(lock_path, updated)
    return updated


def load_human_baseline(baseline_path: Path, corpus_path: Path) -> HumanBaseline:
    corpus = load_repository_corpus(corpus_path)
    payload = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
    baseline = HumanBaseline.model_validate(payload)
    if baseline.corpus_version != corpus.corpus_version:
        raise ValueError("human baseline corpus_version does not match corpus")
    expected_cases = {case.case_id for case in corpus.cases}
    actual_cases = {case.case_id for case in baseline.cases}
    if actual_cases != expected_cases:
        raise ValueError("human baseline cases must exactly match repository corpus")
    return baseline


def run_repository_scorecard(
    *,
    corpus_path: Path,
    lock_path: Path,
    repository_paths: Mapping[str, Path],
    output_dir: Path,
    clock: Callable[[], datetime],
) -> RepositoryScorecardReport:
    verify_repository_corpus_lock(corpus_path, lock_path)
    corpus = load_repository_corpus(corpus_path)
    case_scores: list[CaseScore] = []
    with tempfile.TemporaryDirectory(prefix="repository-scorecard-") as tmp:
        run_root = Path(tmp)
        for case in corpus.cases:
            try:
                repository_path = Path(repository_paths[case.case_id])
            except KeyError as exc:
                raise ValueError(f"repository path is required for case: {case.case_id}") from exc
            case_scores.append(
                _evaluate_case(case, repository_path, run_root / case.case_id, clock)
            )

    metrics = _calculate_metrics(case_scores)
    quality_gate_passed = _passes_quality_gate(metrics)
    report = RepositoryScorecardReport(
        corpus_version=corpus.corpus_version,
        generated_at=clock(),
        case_count=len(case_scores),
        thresholds=DEFAULT_QUALITY_THRESHOLDS,
        metrics=metrics,
        quality_gate_passed=quality_gate_passed,
        cases=case_scores,
    )
    _write_report(report, output_dir)
    return report


def _passes_quality_gate(metrics: ScorecardMetrics) -> bool:
    return all(
        getattr(metrics, metric) >= threshold
        for metric, threshold in DEFAULT_QUALITY_THRESHOLDS.items()
        if metric != "max_ungrounded_auto_confirmed_count"
    ) and metrics.ungrounded_auto_confirmed_count <= DEFAULT_QUALITY_THRESHOLDS[
        "max_ungrounded_auto_confirmed_count"
    ]


def _evaluate_case(
    case: RepositoryCase,
    repository_path: Path,
    analysis_dir: Path,
    clock: Callable[[], datetime],
) -> CaseScore:
    if case.content_sha256 is not None:
        actual_hash = repository_content_sha256(repository_path)
        if actual_hash != case.content_sha256:
            raise ValueError(
                f"repository content hash mismatch for case {case.case_id}"
            )
    _, _, evidence, rules = run_phase1_analysis(
        repo=repository_path,
        output_dir=analysis_dir,
        url=case.repository_url or f"{case.visibility}://{case.case_id}",
        ref=case.revision,
        clock=clock,
        mode=_snapshot_mode(repository_path, case.revision),
        semantic_mode="disabled",
    )
    topology = TopologyBuilder().build_from_models(evidence, rules)
    evidence_artifacts = {fact.evidence_id: fact.artifact_ref for fact in evidence.facts}
    fields = [
        _score_field(expected, topology, evidence_artifacts)
        for expected in case.fields
    ]
    return CaseScore(
        case_id=case.case_id,
        visibility=case.visibility,
        revision=case.revision,
        fields=fields,
    )


def _score_field(
    expected: ExpectedField,
    topology: ApplicationTopology,
    evidence_artifacts: Mapping[str, str],
) -> FieldScore:
    actual = (
        _extract_actual_field(expected.field_id, topology)
        if expected.variant == "common"
        else _ActualField()
    )
    references = [
        ActualEvidenceReference(
            evidence_id=ref,
            artifact=evidence_artifacts[ref],
            locator=None,
        )
        for ref in sorted(set(actual.evidence_refs))
        if ref in evidence_artifacts
    ]
    correct = actual.state == expected.expected_state and (
        expected.expected_state != "resolved" or actual.value == expected.expected_value
    )
    evidence_correct: bool | None = None
    if actual.state in {"resolved", "not_applicable"}:
        actual_locations = {(ref.artifact, ref.locator) for ref in references}
        expected_locations = {
            (ref.artifact, ref.locator) for ref in expected.expected_evidence
        }
        evidence_correct = expected_locations.issubset(actual_locations)
    return FieldScore(
        field_id=expected.field_id,
        group=expected.group,
        variant=expected.variant,
        expected_state=expected.expected_state,
        expected_value=expected.expected_value,
        actual_state=actual.state,
        actual_value=_redact_value(actual.value),
        source=actual.source,
        confidence=actual.confidence,
        classification=actual.classification,
        correct=correct,
        evidence_references=references,
        evidence_correct=evidence_correct,
    )


def _extract_actual_field(
    field_id: str,
    topology: ApplicationTopology,
) -> _ActualField:
    parts = field_id.split(".")
    if len(parts) >= 4 and parts[0] == "runtime_dependencies":
        component = next(
            (item for item in topology.components if item.component_id == parts[1]),
            None,
        )
        if component is None:
            return _ActualField()
        dependency = next(
            (item for item in component.dependencies if item.target == parts[2]), None
        )
        if dependency is not None and ".".join(parts[3:]) == "present":
            return _ActualField(
                state="resolved",
                value=True,
                evidence_refs=dependency.evidence_refs,
                source=dependency.source,
                confidence=dependency.confidence,
                classification=dependency.classification,
            )
        return _ActualField()
    if len(parts) < 3 or parts[0] != "components":
        return _ActualField()
    component_id = parts[1]
    component = next(
        (item for item in topology.components if item.component_id == component_id),
        None,
    )
    field_name = ".".join(parts[2:])
    if field_name == "present":
        if component is None:
            return _ActualField()
        return _ActualField(
            state="resolved", value=True, evidence_refs=component.evidence_refs
        )
    if component is None:
        return _ActualField()
    return _extract_component_field(field_name, component, topology)


def _extract_component_field(
    field_name: str,
    component: ApplicationComponent,
    topology: ApplicationTopology,
) -> _ActualField:
    if field_name == "deployment_role":
        return _ActualField()
    if field_name == "effective_runtime_command":
        conflict = next(
            (
                item
                for item in topology.conflicts
                if item.field_path == f"/components/{component.component_id}/runtime/command"
            ),
            None,
        )
        if conflict is not None:
            return _ActualField(state="conflict", evidence_refs=conflict.evidence_refs)
        if component.command is not None:
            return _ActualField(
                state="resolved",
                value=component.command.value,
                evidence_refs=component.command.evidence_refs,
                source=component.command.source,
                confidence=component.command.confidence,
                classification=component.command.classification,
            )
    if field_name == "runtime_port" and len(component.ports) == 1:
        port = component.ports[0]
        return _ActualField(
            state="resolved",
            value=port.value,
            evidence_refs=port.evidence_refs,
            source=port.source,
            confidence=port.confidence,
            classification=port.classification,
        )
    if field_name == "build_strategy" and component.runtime is not None:
        return _ActualField(
            state="resolved",
            value=component.runtime.build_strategy,
            evidence_refs=component.runtime.evidence_refs,
            source=component.runtime.source,
            confidence=component.runtime.confidence,
            classification=component.runtime.classification,
        )
    if field_name == "runtime_language" and component.runtime is not None:
        return _ActualField(
            state="resolved",
            value=component.runtime.language,
            evidence_refs=component.runtime.evidence_refs,
            source=component.runtime.source,
            confidence=component.runtime.confidence,
            classification=component.runtime.classification,
        )
    if field_name == "runtime_framework" and component.runtime is not None:
        return _ActualField(
            state="resolved",
            value=component.runtime.framework,
            evidence_refs=component.runtime.evidence_refs,
            source=component.runtime.source,
            confidence=component.runtime.confidence,
            classification=component.runtime.classification,
        )
    if field_name == "root_path" and component.root_path is not None:
        return _ActualField(
            state="resolved", value=component.root_path, evidence_refs=component.evidence_refs
        )
    if field_name.startswith("secret.") and field_name.endswith(".classification"):
        secret_name = field_name.removeprefix("secret.").removesuffix(
            ".classification"
        )
        secret = next(
            (item for item in component.secrets if item.name == secret_name), None
        )
        if secret is not None:
            return _ActualField(
                state="resolved",
                value="secret",
                evidence_refs=secret.evidence_refs,
                source=secret.source,
                classification=secret.classification,
            )
    return _ActualField()


def _calculate_metrics(cases: list[CaseScore]) -> ScorecardMetrics:
    fields = [field for case in cases for field in case.fields]
    core = [field for field in fields if field.group == "core"]
    extended = [field for field in fields if field.group == "extended"]
    accountable_states = {"resolved", "unresolved", "conflict", "not_applicable"}
    accountable_core = sum(field.actual_state in accountable_states for field in core)
    clear_states = {"resolved", "not_applicable"}
    clear_core = [field for field in core if field.expected_state in clear_states]
    clear_extended = [
        field for field in extended if field.expected_state in clear_states
    ]
    auto_confirmed = [
        field
        for field in extended
        if field.actual_state in clear_states
    ]
    evidence_scored = [field for field in auto_confirmed if field.evidence_correct is not None]
    all_auto_confirmed = [field for field in fields if field.actual_state in clear_states]
    ungrounded = sum(
        not field.evidence_references
        or any(reference.locator is None for reference in field.evidence_references)
        or field.source is None
        or field.classification is None
        for field in all_auto_confirmed
    )
    return ScorecardMetrics(
        core_field_accountability_rate=_ratio(accountable_core, len(core)),
        core_resolution_rate=_ratio(
            sum(field.correct for field in clear_core), len(clear_core)
        ),
        extended_resolution_rate=_ratio(
            sum(field.correct for field in clear_extended), len(clear_extended)
        ),
        auto_confirmed_accuracy=_ratio(
            sum(field.correct for field in auto_confirmed), len(auto_confirmed)
        ),
        evidence_reference_accuracy=_ratio(
            sum(bool(field.evidence_correct) for field in evidence_scored),
            len(evidence_scored),
        ),
        ungrounded_auto_confirmed_count=ungrounded,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _write_report(report: RepositoryScorecardReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json", exclude_none=True)
    (output_dir / "repository-analysis-scorecard.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Repository Analysis Scorecard",
        "",
        f"- corpus_version: {report.corpus_version}",
        f"- quality_gate_passed: {str(report.quality_gate_passed).lower()}",
        "",
        "## Metrics",
        "",
    ]
    for name, value in report.metrics.model_dump().items():
        lines.append(f"- {name}: {value:.4f}")
    lines.extend(["", "## Cases", ""])
    for case in report.cases:
        lines.append(f"### {case.case_id}")
        lines.append("")
        for field in case.fields:
            lines.append(
                f"- {field.field_id}: expected={field.expected_state}, "
                f"actual={field.actual_state}, correct={str(field.correct).lower()}"
            )
        lines.append("")
    (output_dir / "repository-analysis-scorecard.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _content_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def repository_content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _scoring_rules_hash() -> str:
    payload = json.dumps(DEFAULT_QUALITY_THRESHOLDS, sort_keys=True) + "\n" + "\n".join(
        inspect.getsource(function)
        for function in (
            _score_field,
            _extract_actual_field,
            _extract_component_field,
            _calculate_metrics,
            _passes_quality_gate,
            _ratio,
        )
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _contains_sensitive_value(value: Any) -> bool:
    if isinstance(value, str):
        return redacted(value) != value or contains_credentials(value)
    if isinstance(value, list):
        return any(_contains_sensitive_value(item) for item in value)
    if isinstance(value, dict):
        return any(
            is_secret_name(str(key)) or _contains_sensitive_value(item)
            for key, item in value.items()
        )
    return False


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        if contains_credentials(value):
            return "[REDACTED_CREDENTIAL_URI]"
        return redacted(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _write_corpus_lock(lock_path: Path, lock: RepositoryCorpusLock) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_lock_history(
    corpus: RepositoryCorpus, lock: RepositoryCorpusLock
) -> None:
    if len(corpus.change_history) != len(lock.entries):
        raise ValueError("corpus change history does not match lock history")
    for history, entry in zip(corpus.change_history, lock.entries, strict=True):
        if (
            history.version != entry.version
            or history.reason != entry.reason
            or history.affected_cases != entry.affected_cases
        ):
            raise ValueError("corpus change history does not match lock history")


def _snapshot_mode(repository_path: Path, revision: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return "workspace"
    completed = subprocess.run(
        ["git", "-C", str(repository_path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or head != revision:
        raise ValueError(
            f"repository revision mismatch for {repository_path}: "
            f"expected {revision}, actual {head or 'not-a-git-repository'}"
        )
    return "commit"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the locked Repository analysis scorecard."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument(
        "--repository",
        action="append",
        default=[],
        metavar="CASE_ID=PATH",
        help="Repeat once for each corpus case.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    repository_paths: dict[str, Path] = {}
    for value in args.repository:
        case_id, separator, path = value.partition("=")
        if not separator or not case_id or not path:
            parser.error("--repository must use CASE_ID=PATH")
        repository_paths[case_id] = Path(path)
    report = run_repository_scorecard(
        corpus_path=args.corpus,
        lock_path=args.lock,
        repository_paths=repository_paths,
        output_dir=args.output_dir,
        clock=lambda: datetime.now(timezone.utc),
    )
    print(args.output_dir / "repository-analysis-scorecard.md")
    return 0 if report.quality_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
