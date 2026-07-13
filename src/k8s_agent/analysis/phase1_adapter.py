from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunEvent
from k8s_agent.models.source import RepositorySource
from k8s_agent.run.events import EventLog
from k8s_agent.run.store import RunStore
from preanalyzer.pipeline import run_phase1_analysis


PHASE1_ARTIFACTS = [
    "00-repository-snapshot.yaml",
    "01-artifact-inventory.yaml",
    "02-evidence-model.yaml",
    "03-rule-inference.yaml",
]


@dataclass(frozen=True)
class Phase1Result:
    run_id: str
    analysis_dir: Path
    repository_root: Path
    checksums: dict[str, str]
    artifact_count: int


class Phase1Adapter:
    def __init__(self, store: RunStore, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, source: RepositorySource, run_id: str) -> Phase1Result:
        analysis_dir = self.store.run_path(run_id) / "analysis"
        try:
            run_phase1_analysis(
                repo=source.path,
                output_dir=analysis_dir,
                url=_source_url(source),
                ref=source.git.head,
                clock=self.clock,
                semantic_mode="disabled",
            )
        except Exception as exc:
            raise AgentError(
                code="ANALYSIS-101",
                exit_code=8,
                message="phase1 analysis failed.",
                resolution="Inspect the source repository and retry the run.",
                context={"run_id": run_id, "source_kind": source.kind},
            ) from exc
        checksums = {name: _sha256(analysis_dir / name) for name in PHASE1_ARTIFACTS}
        result = Phase1Result(
            run_id=run_id,
            analysis_dir=analysis_dir,
            repository_root=source.path,
            checksums=checksums,
            artifact_count=len(PHASE1_ARTIFACTS),
        )
        EventLog(self.store.event_file(run_id)).append(
            RunEvent(
                event_id=f"event-{uuid4().hex}",
                run_id=run_id,
                event_type="phase1_completed",
                created_at=self.clock(),
                summary="phase1 analysis completed",
                details={"artifact_count": str(result.artifact_count)},
            )
        )
        return result


def _source_url(source: RepositorySource) -> str | None:
    if source.kind == "github":
        return "github"
    return None


def _sha256(path) -> str:
    return f"sha256:{_sha256_bytes(path.read_bytes())}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
