from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
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
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
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

SCORING_RULES_VERSION = "2026-07-14.6"
CRITICAL_FIELD_SCENARIOS = frozenset(
    {"normal", "absence", "conflict", "coverage_gap"}
)
FieldState = Literal["resolved", "not_applicable", "conflict", "unresolved", "missing"]
ArtifactType = Literal[
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
CriticalFieldScenario = Literal["normal", "absence", "conflict", "coverage_gap"]

_SECRET_OPTION_RE = re.compile(
    r"(?i)(?P<prefix>(?:--(?:password|passwd|token|secret|api-key|api_key)|"
    r"(?:password|passwd|token|secret|api[_-]?key))"
    r"(?:=|\s+))"
    r"(?P<value>['\"]?[^'\"\s#]+['\"]?)"
)
_URI_USERINFO_RE = re.compile(
    r"\b(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
    r"(?P<userinfo>[^\s/@]+)@(?P<rest>[^\s'\"<>]+)"
)


class CorpusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    reason: str = Field(min_length=1)
    affected_cases: list[str] = Field(min_length=1)


class VersionedContractChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    reason: str = Field(min_length=1)
    affected_evaluations: list[str] = Field(min_length=1)


class ArtifactContractEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: ArtifactType
    field_id: str
    scenario: CriticalFieldScenario
    expected_state: Literal["resolved", "not_applicable", "conflict", "unresolved"]
    case_id: str | None = None
    not_applicable_reason: str | None = None

    @model_validator(mode="after")
    def validate_contract_target(self) -> "ArtifactContractEntry":
        if bool(self.case_id) == bool(self.not_applicable_reason):
            raise ValueError(
                "artifact contract entries require either case_id or not_applicable_reason"
            )
        return self


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
    scenario: CriticalFieldScenario | None = None
    artifact_types: list[ArtifactType] = Field(default_factory=list)
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
    artifact_contract: list[ArtifactContractEntry] = Field(default_factory=list)
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
        self._validate_artifact_contract()
        return self

    def _validate_artifact_contract(self) -> None:
        if not self.artifact_contract:
            return
        case_by_id = {case.case_id: case for case in self.cases}
        supported_artifacts = {
            artifact_type for case in self.cases for artifact_type in case.artifact_types
        }
        combinations = [
            (entry.case_id, entry.artifact_type, entry.field_id, entry.scenario)
            for entry in self.artifact_contract
        ]
        if len(combinations) != len(set(combinations)):
            raise ValueError("artifact contract matrix entries must be unique")
        for entry in self.artifact_contract:
            if entry.not_applicable_reason:
                continue
            assert entry.case_id is not None
            case = case_by_id.get(entry.case_id)
            if case is None:
                raise ValueError(
                    f"artifact contract references unknown case: {entry.case_id}"
                )
            if case.scenario != entry.scenario:
                raise ValueError(
                    "artifact contract scenario does not match referenced case"
                )
            if entry.artifact_type not in case.artifact_types:
                raise ValueError(
                    "artifact contract artifact_type does not match referenced case"
                )
            field = next(
                (item for item in case.fields if item.field_id == entry.field_id),
                None,
            )
            if field is None or field.expected_state != entry.expected_state:
                raise ValueError(
                    "artifact contract field/state does not match referenced case"
                )
        covered_fields = {
            (entry.case_id, entry.field_id, entry.scenario, entry.expected_state)
            for entry in self.artifact_contract
            if entry.case_id is not None
        }
        for case in self.cases:
            if case.scenario is None:
                continue
            for field in case.fields:
                key = (
                    case.case_id,
                    field.field_id,
                    case.scenario,
                    field.expected_state,
                )
                if key not in covered_fields:
                    raise ValueError(
                        "artifact contract missing applicable field/state combination"
                    )
        scenarios_by_artifact: dict[str, set[str]] = {
            artifact_type: set() for artifact_type in supported_artifacts
        }
        not_applicable_rows = 0
        for entry in self.artifact_contract:
            if entry.artifact_type in scenarios_by_artifact:
                scenarios_by_artifact[entry.artifact_type].add(entry.scenario)
            if entry.not_applicable_reason:
                not_applicable_rows += 1
                if entry.expected_state != "not_applicable":
                    raise ValueError(
                        "artifact contract not-applicable rows must use not_applicable state"
                    )
        if supported_artifacts and not not_applicable_rows:
            raise ValueError("artifact contract requires not_applicable_reason entries")
        for artifact_type, scenarios in scenarios_by_artifact.items():
            missing = sorted(CRITICAL_FIELD_SCENARIOS - scenarios)
            if missing:
                raise ValueError(
                    "artifact contract matrix missing scenarios for "
                    f"{artifact_type}: {', '.join(missing)}"
                )


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

    @model_validator(mode="before")
    @classmethod
    def redact_sensitive_values(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        sanitized = dict(data)
        for key in ("expected_value", "actual_value"):
            if key in sanitized:
                sanitized[key] = _redact_value(sanitized[key])
        return sanitized


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


class RepositoryRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    visibility: Literal["public", "internal"]
    stack: str
    repository_url: str | None = None
    revision: str | None = None
    expert_truth_path: str | None = None
    repository_url_env: str | None = None
    repository_path_env: str | None = None
    revision_env: str | None = None
    revision_sha256: str | None = None
    expert_truth_path_env: str | None = None

    @model_validator(mode="after")
    def validate_pin_shape(self) -> "RepositoryRegistryEntry":
        if self.visibility == "public":
            if not self.repository_url or not self.revision or not self.expert_truth_path:
                raise ValueError("public registry entries require URL, revision, and truth path")
            if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
                raise ValueError("public registry revisions must be immutable commits")
            forbidden = [
                self.repository_url_env,
                self.repository_path_env,
                self.revision_env,
                self.revision_sha256,
                self.expert_truth_path_env,
            ]
            if any(value is not None for value in forbidden):
                raise ValueError("public registry entries must not use internal env pins")
        else:
            required = [
                self.repository_url_env,
                self.repository_path_env,
                self.revision_env,
                self.revision_sha256,
                self.expert_truth_path_env,
            ]
            if any(value is None for value in required):
                raise ValueError("internal registry entries require environment pin names")
            if self.repository_url or self.revision or self.expert_truth_path:
                raise ValueError("internal registry entries must not commit private pins")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.revision_sha256 or ""):
                raise ValueError("internal registry revision_sha256 must be a sha256 digest")
        return self


class RepositoryRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-registry/v1"]
    registry_version: str
    corpus_version: str
    change_history: list[VersionedContractChange] = Field(min_length=1)
    repositories: list[RepositoryRegistryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry_history(self) -> "RepositoryRegistry":
        case_ids = [entry.case_id for entry in self.repositories]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("repository registry case_id values must be unique")
        latest = self.change_history[-1]
        if latest.version != self.registry_version:
            raise ValueError("latest change history version must match registry_version")
        versions = [change.version for change in self.change_history]
        if len(versions) != len(set(versions)):
            raise ValueError("registry change history versions must be unique")
        for change in self.change_history:
            unknown = sorted(set(change.affected_evaluations) - set(case_ids))
            if unknown:
                raise ValueError(
                    "registry change history references unknown evaluations: "
                    + ", ".join(unknown)
                )
        return self


class VersionedContractLockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    content_sha256: str
    reason: str
    affected_evaluations: list[str]


class VersionedContractLock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["repository-analysis-contract-lock/v1"] = (
        "repository-analysis-contract-lock/v1"
    )
    contract_kind: Literal["repository_registry", "human_baseline"]
    entries: list[VersionedContractLockEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_versions(self) -> "VersionedContractLock":
        versions = [entry.version for entry in self.entries]
        if len(versions) != len(set(versions)):
            raise ValueError("contract lock versions must be unique")
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
    baseline_version: str
    corpus_version: str
    change_history: list[VersionedContractChange] = Field(min_length=1)
    cases: list[HumanBaselineCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids_and_operator_rotation(self) -> "HumanBaseline":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("human baseline case_id values must be unique")
        latest = self.change_history[-1]
        if latest.version != self.baseline_version:
            raise ValueError("latest change history version must match baseline_version")
        versions = [change.version for change in self.change_history]
        if len(versions) != len(set(versions)):
            raise ValueError("human baseline change history versions must be unique")
        for change in self.change_history:
            unknown = sorted(set(change.affected_evaluations) - set(case_ids))
            if unknown:
                raise ValueError(
                    "human baseline change history references unknown evaluations: "
                    + ", ".join(unknown)
                )
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


def load_repository_registry(registry_path: Path) -> RepositoryRegistry:
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    return RepositoryRegistry.model_validate(payload)


def validate_repository_registry(
    registry: RepositoryRegistry,
    corpus: RepositoryCorpus,
) -> None:
    if registry.corpus_version != corpus.corpus_version:
        raise ValueError("repository registry corpus_version does not match corpus")
    entries = {entry.case_id: entry for entry in registry.repositories}
    registry_cases = set(entries)
    corpus_cases = {
        case.case_id for case in corpus.cases if case.visibility in {"public", "internal"}
    }
    if corpus_cases != registry_cases:
        raise ValueError("repository registry cases must exactly match real corpus cases")
    for case in corpus.cases:
        if case.visibility == "contract":
            continue
        entry = entries[case.case_id]
        if entry.visibility != case.visibility:
            raise ValueError("repository registry visibility does not match corpus")
        if case.visibility == "public":
            if entry.repository_url != case.repository_url:
                raise ValueError("repository registry URL does not match corpus")
            if entry.revision != case.revision:
                raise ValueError("repository registry revision does not match corpus")
        else:
            assert entry.revision_env is not None
            revision = os.environ.get(entry.revision_env)
            if not revision:
                raise ValueError(
                    f"internal repository revision env is required: {entry.revision_env}"
                )
            if _text_sha256(revision) != entry.revision_sha256:
                raise ValueError("internal repository revision fingerprint mismatch")
            if case.revision != revision:
                raise ValueError("internal repository revision does not match corpus")


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
    baseline = _load_human_baseline_payload(baseline_path)
    if baseline.corpus_version != corpus.corpus_version:
        raise ValueError("human baseline corpus_version does not match corpus")
    expected_cases = {case.case_id for case in corpus.cases}
    actual_cases = {case.case_id for case in baseline.cases}
    if actual_cases != expected_cases:
        raise ValueError("human baseline cases must exactly match repository corpus")
    return baseline


def initialize_repository_registry_lock(
    registry_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    registry = load_repository_registry(registry_path)
    return _initialize_versioned_contract_lock(
        path=registry_path,
        lock_path=lock_path or _default_contract_lock_path(registry_path),
        contract_kind="repository_registry",
        version=registry.registry_version,
        change_history=registry.change_history,
    )


def verify_repository_registry_lock(
    registry_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    registry = load_repository_registry(registry_path)
    return _verify_versioned_contract_lock(
        path=registry_path,
        lock_path=lock_path or _default_contract_lock_path(registry_path),
        contract_kind="repository_registry",
        version=registry.registry_version,
        change_history=registry.change_history,
    )


def update_repository_registry_lock(
    registry_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    registry = load_repository_registry(registry_path)
    return _update_versioned_contract_lock(
        path=registry_path,
        lock_path=lock_path or _default_contract_lock_path(registry_path),
        contract_kind="repository_registry",
        version=registry.registry_version,
        change_history=registry.change_history,
    )


def initialize_human_baseline_lock(
    baseline_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    baseline = _load_human_baseline_payload(baseline_path)
    return _initialize_versioned_contract_lock(
        path=baseline_path,
        lock_path=lock_path or _default_contract_lock_path(baseline_path),
        contract_kind="human_baseline",
        version=baseline.baseline_version,
        change_history=baseline.change_history,
    )


def verify_human_baseline_lock(
    baseline_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    baseline = _load_human_baseline_payload(baseline_path)
    return _verify_versioned_contract_lock(
        path=baseline_path,
        lock_path=lock_path or _default_contract_lock_path(baseline_path),
        contract_kind="human_baseline",
        version=baseline.baseline_version,
        change_history=baseline.change_history,
    )


def update_human_baseline_lock(
    baseline_path: Path, lock_path: Path | None = None
) -> VersionedContractLock:
    baseline = _load_human_baseline_payload(baseline_path)
    return _update_versioned_contract_lock(
        path=baseline_path,
        lock_path=lock_path or _default_contract_lock_path(baseline_path),
        contract_kind="human_baseline",
        version=baseline.baseline_version,
        change_history=baseline.change_history,
    )


def run_repository_scorecard(
    *,
    corpus_path: Path,
    lock_path: Path,
    repository_paths: Mapping[str, Path],
    output_dir: Path,
    clock: Callable[[], datetime],
    registry_path: Path | None = None,
    baseline_path: Path | None = None,
    registry_lock_path: Path | None = None,
    baseline_lock_path: Path | None = None,
) -> RepositoryScorecardReport:
    verify_repository_corpus_lock(corpus_path, lock_path)
    corpus = load_repository_corpus(corpus_path)
    has_real_cases = any(case.visibility in {"public", "internal"} for case in corpus.cases)
    if has_real_cases and registry_path is None:
        raise ValueError("repository registry is required for real repository scorecards")
    if has_real_cases and baseline_path is None:
        raise ValueError("human baseline is required for real repository scorecards")
    if registry_path is not None:
        verify_repository_registry_lock(registry_path, registry_lock_path)
        validate_repository_registry(load_repository_registry(registry_path), corpus)
    if baseline_path is not None:
        verify_human_baseline_lock(baseline_path, baseline_lock_path)
        load_human_baseline(baseline_path, corpus_path)
    snapshot_modes = _validate_repository_inputs(corpus, repository_paths)
    case_scores: list[CaseScore] = []
    with tempfile.TemporaryDirectory(prefix="repository-scorecard-") as tmp:
        run_root = Path(tmp)
        for case in corpus.cases:
            case_scores.append(
                _evaluate_case(
                    case,
                    Path(repository_paths[case.case_id]),
                    run_root / case.case_id,
                    clock,
                    snapshot_modes[case.case_id],
                )
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


def _validate_repository_inputs(
    corpus: RepositoryCorpus,
    repository_paths: Mapping[str, Path],
) -> dict[str, str]:
    snapshot_modes: dict[str, str] = {}
    for case in corpus.cases:
        try:
            repository_path = Path(repository_paths[case.case_id])
        except KeyError as exc:
            raise ValueError(f"repository path is required for case: {case.case_id}") from exc
        if case.content_sha256 is not None:
            actual_hash = repository_content_sha256(repository_path)
            if actual_hash != case.content_sha256:
                raise ValueError(
                    f"repository content hash mismatch for case {case.case_id}"
                )
        snapshot_modes[case.case_id] = _snapshot_mode(repository_path, case.revision)
    return snapshot_modes


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
    snapshot_mode: str,
) -> CaseScore:
    _, _, evidence, rules = run_phase1_analysis(
        repo=repository_path,
        output_dir=analysis_dir,
        url=case.repository_url or f"{case.visibility}://{case.case_id}",
        ref=case.revision,
        clock=clock,
        mode=snapshot_mode,
        semantic_mode="disabled",
    )
    topology = TopologyBuilder().build_from_models(evidence, rules)
    evidence_references = _evidence_reference_index(evidence)
    fields = [
        _score_field(expected, topology, evidence, evidence_references)
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
    evidence: EvidenceModel,
    evidence_references: Mapping[str, ActualEvidenceReference],
) -> FieldScore:
    actual = (
        _extract_actual_field(expected.field_id, topology, evidence)
        if expected.variant == "common"
        else _ActualField()
    )
    references = [
        evidence_references[ref]
        for ref in sorted(set(actual.evidence_refs))
        if ref in evidence_references
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
        evidence_correct = actual_locations == expected_locations
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
    evidence: EvidenceModel,
) -> _ActualField:
    parts = field_id.split(".")
    if len(parts) >= 3 and parts[0] == "package_dependencies":
        package_name = ".".join(parts[2:])
        fact = _find_package_dependency(evidence, package_name)
        if fact is None:
            return _ActualField()
        return _ActualField(
            state="resolved",
            value=True,
            evidence_refs=[fact.evidence_id],
            source=fact.source,
            confidence="high",
            classification=fact.classification,
        )
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
        return _ActualField(
            state="resolved",
            value=component.role,
            evidence_refs=component.evidence_refs,
            source=component.runtime.source if component.runtime is not None else "component_role",
            confidence=(
                component.runtime.confidence if component.runtime is not None else "medium"
            ),
            classification="rule_inference",
        )
    if field_name == "workload_role":
        workload_role = _workload_role(component)
        if workload_role is not None:
            return workload_role
    if field_name == "secret_classification":
        if not component.secrets:
            refs = component.evidence_refs
            if component.runtime is not None:
                refs = sorted(set(refs + component.runtime.evidence_refs))
            return _ActualField(
                state="not_applicable",
                evidence_refs=refs,
                source="secret_absence",
                confidence="high",
                classification="negative_finding",
            )
        return _ActualField(
            state="resolved",
            value="secret",
            evidence_refs=sorted(
                {ref for secret in component.secrets for ref in secret.evidence_refs}
            ),
            source="secret_classification",
            confidence="high",
            classification="rule_inference",
        )
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
    if field_name == "runtime_port" and len(component.ports) > 1:
        return _ActualField(
            state="conflict",
            value=[
                {
                    "value": port.value,
                    "source": port.source,
                    "confidence": port.confidence,
                    "classification": port.classification,
                    "evidence_refs": port.evidence_refs,
                }
                for port in component.ports
            ],
            evidence_refs=sorted({ref for port in component.ports for ref in port.evidence_refs}),
            source="multiple",
            confidence="conflict",
            classification="evidence_conflict",
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


def _workload_role(component: ApplicationComponent) -> _ActualField | None:
    runtime = component.runtime
    if runtime is None:
        return None
    if runtime.framework in {"express", "fastapi", "spring"}:
        return _ActualField(
            state="resolved",
            value="api",
            evidence_refs=runtime.evidence_refs,
            source=runtime.source,
            confidence=runtime.confidence,
            classification=runtime.classification,
        )
    return None


def _find_package_dependency(
    evidence: EvidenceModel, package_name: str
) -> EvidenceFact | None:
    for fact in evidence.facts_by_type("package_dependency"):
        if isinstance(fact.value, dict) and fact.value.get("package") == package_name:
            return fact
    return None


def _evidence_reference_index(
    evidence: EvidenceModel,
) -> dict[str, ActualEvidenceReference]:
    result: dict[str, ActualEvidenceReference] = {}
    fact_counts: dict[tuple[str, str], int] = {}
    service_counts: dict[tuple[str, str, str], int] = {}
    for fact in evidence.facts:
        key = (fact.artifact_ref, fact.fact_type)
        index = fact_counts.get(key, 0)
        fact_counts[key] = index + 1
        locator = _locator_for_fact(fact, index, service_counts)
        result[fact.evidence_id] = ActualEvidenceReference(
            evidence_id=fact.evidence_id,
            artifact=fact.artifact_ref,
            locator=locator,
        )
    return result


def _locator_for_fact(
    fact: EvidenceFact,
    index: int,
    service_counts: dict[tuple[str, str, str], int],
) -> str:
    value = fact.value
    if fact.fact_type == "artifact_presence":
        if isinstance(value, dict) and value.get("present") is False:
            return "inventory:absent"
        return "inventory:present"
    if fact.fact_type == "dockerfile_base_image":
        return "dockerfile:FROM"
    if fact.fact_type == "dockerfile_expose":
        return f"dockerfile:EXPOSE[{index}]"
    if fact.fact_type == "dockerfile_cmd":
        return "dockerfile:CMD"
    if fact.fact_type == "dockerfile_entrypoint":
        return "dockerfile:ENTRYPOINT"
    if fact.fact_type == "dockerfile_user":
        return "dockerfile:USER"
    if fact.fact_type == "maven_packaging":
        return "xpath:/project/packaging"
    if fact.fact_type == "maven_module":
        return f"xpath:/project/modules/module[{index}]"
    if fact.fact_type == "package_dependency" and isinstance(value, dict):
        package = str(value.get("package", ""))
        if fact.artifact_ref.endswith("package.json"):
            return f"jsonpath:$.dependencies.{package}"
        if fact.artifact_ref.endswith("requirements.txt"):
            return f"requirement:{package}"
        return f"package:{package}"
    if fact.fact_type == "package_script" and isinstance(value, dict):
        return f"jsonpath:$.scripts.{value.get('name', '')}"
    if fact.fact_type.startswith("compose_") and isinstance(value, dict):
        service = str(value.get("service", ""))
        if fact.fact_type == "compose_service":
            return f"yamlpath:$.services.{service}"
        compose_key = {
            "compose_image": "image",
            "compose_build_context": "build",
            "compose_depends_on": "depends_on",
            "compose_port": "ports",
            "compose_environment": "environment",
            "compose_volume": "volumes",
        }.get(fact.fact_type)
        if compose_key is not None:
            service_key = (fact.artifact_ref, service, compose_key)
            service_index = service_counts.get(service_key, 0)
            service_counts[service_key] = service_index + 1
            if compose_key in {"image", "build"}:
                return f"yamlpath:$.services.{service}.{compose_key}"
            return f"yamlpath:$.services.{service}.{compose_key}[{service_index}]"
    return fact.source


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
        for field in fields
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
    payload = (
        SCORING_RULES_VERSION
        + "\n"
        + json.dumps(DEFAULT_QUALITY_THRESHOLDS, sort_keys=True)
        + "\n"
        + "\n".join(
            inspect.getsource(function)
            for function in (
                _score_field,
                _extract_actual_field,
                _extract_component_field,
                _workload_role,
                _find_package_dependency,
                _evidence_reference_index,
                _locator_for_fact,
                _validate_repository_inputs,
                _calculate_metrics,
                _passes_quality_gate,
                _ratio,
            )
        )
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _contains_sensitive_value(value: Any) -> bool:
    if isinstance(value, str):
        return _redact_text(value) != value or contains_credentials(value)
    if isinstance(value, list):
        return any(_contains_sensitive_value(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_sensitive_key(str(key)) or _contains_sensitive_value(item)
            for key, item in value.items()
        )
    return False


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        if contains_credentials(value):
            return "[REDACTED_CREDENTIAL_URI]"
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _contains_sensitive_key(key_text):
                result["[REDACTED_KEY]"] = "[REDACTED]"
            else:
                result[key_text] = _redact_value(item)
        return result
    return value


def _redact_text(value: str) -> str:
    text = _URI_USERINFO_RE.sub(
        lambda match: f"{match.group('scheme')}[REDACTED]@{match.group('rest')}",
        value,
    )
    text = redacted(text)
    return _SECRET_OPTION_RE.sub(_redact_secret_option, text)


def _redact_secret_option(match: re.Match[str]) -> str:
    raw_value = match.group("value")
    if _is_env_reference(raw_value):
        return match.group(0)
    return f"{match.group('prefix')}[REDACTED]"


def _contains_sensitive_key(value: str) -> bool:
    return is_secret_name(value) or _redact_text(value) != value


def _is_env_reference(value: str) -> bool:
    stripped = value.strip().strip("'\"")
    return stripped.startswith("$") or stripped.startswith("${")


def _text_sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _write_corpus_lock(lock_path: Path, lock: RepositoryCorpusLock) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_human_baseline_payload(baseline_path: Path) -> HumanBaseline:
    payload = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
    return HumanBaseline.model_validate(payload)


def _initialize_versioned_contract_lock(
    *,
    path: Path,
    lock_path: Path,
    contract_kind: Literal["repository_registry", "human_baseline"],
    version: str,
    change_history: list[VersionedContractChange],
) -> VersionedContractLock:
    latest = change_history[-1]
    if latest.version != version:
        raise ValueError("latest change history version must match contract version")
    content_hash = _content_hash(path)
    lock = VersionedContractLock(
        contract_kind=contract_kind,
        entries=[
            VersionedContractLockEntry(
                version=history.version,
                content_sha256=content_hash,
                reason=history.reason,
                affected_evaluations=history.affected_evaluations,
            )
            for history in change_history
        ],
    )
    _write_versioned_contract_lock(lock_path, lock)
    return lock


def _verify_versioned_contract_lock(
    *,
    path: Path,
    lock_path: Path,
    contract_kind: Literal["repository_registry", "human_baseline"],
    version: str,
    change_history: list[VersionedContractChange],
) -> VersionedContractLock:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    lock = VersionedContractLock.model_validate(payload)
    _verify_versioned_contract_history(contract_kind, change_history, lock)
    latest = lock.entries[-1]
    if latest.version != version:
        raise ValueError("contract lock version does not match contract version")
    if latest.content_sha256 != _content_hash(path):
        raise ValueError("contract content hash does not match the lock")
    history = change_history[-1]
    if (
        latest.reason != history.reason
        or latest.affected_evaluations != history.affected_evaluations
    ):
        raise ValueError("contract lock change metadata does not match change_history")
    return lock


def _update_versioned_contract_lock(
    *,
    path: Path,
    lock_path: Path,
    contract_kind: Literal["repository_registry", "human_baseline"],
    version: str,
    change_history: list[VersionedContractChange],
) -> VersionedContractLock:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    lock = VersionedContractLock.model_validate(payload)
    if version in {entry.version for entry in lock.entries}:
        raise ValueError("changed contract requires a new version")
    if len(change_history) != len(lock.entries) + 1:
        raise ValueError("contract update requires exactly one new change history entry")
    _verify_versioned_contract_history(
        contract_kind, change_history[:-1], lock
    )
    latest = change_history[-1]
    updated = lock.model_copy(
        update={
            "entries": lock.entries
            + [
                VersionedContractLockEntry(
                    version=version,
                    content_sha256=_content_hash(path),
                    reason=latest.reason,
                    affected_evaluations=latest.affected_evaluations,
                )
            ]
        }
    )
    _write_versioned_contract_lock(lock_path, updated)
    return updated


def _verify_versioned_contract_history(
    contract_kind: Literal["repository_registry", "human_baseline"],
    change_history: list[VersionedContractChange],
    lock: VersionedContractLock,
) -> None:
    if lock.contract_kind != contract_kind:
        raise ValueError("contract lock kind does not match contract")
    if len(change_history) != len(lock.entries):
        raise ValueError("contract change history does not match lock history")
    for history, entry in zip(change_history, lock.entries, strict=True):
        if (
            history.version != entry.version
            or history.reason != entry.reason
            or history.affected_evaluations != entry.affected_evaluations
        ):
            raise ValueError("contract change history does not match lock history")


def _write_versioned_contract_lock(
    lock_path: Path, lock: VersionedContractLock
) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_contract_lock_path(path: Path) -> Path:
    if path.suffix in {".yaml", ".yml"}:
        return path.with_suffix(".lock.json")
    return path.with_name(f"{path.name}.lock.json")


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
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--registry-lock", type=Path)
    parser.add_argument("--human-baseline", type=Path)
    parser.add_argument("--human-baseline-lock", type=Path)
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
        registry_path=args.registry,
        baseline_path=args.human_baseline,
        registry_lock_path=args.registry_lock,
        baseline_lock_path=args.human_baseline_lock,
    )
    print(args.output_dir / "repository-analysis-scorecard.md")
    return 0 if report.quality_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
