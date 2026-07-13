from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunRecord


class RunStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def run_path(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def run_file(self, run_id: str) -> Path:
        return self.run_path(run_id) / "run.yaml"

    def event_file(self, run_id: str) -> Path:
        return self.run_path(run_id) / "events.jsonl"

    def save(self, record: RunRecord) -> RunRecord:
        run_root = self.run_path(record.run_id)
        run_root.mkdir(parents=True, exist_ok=True)
        normalized = record.model_copy(update={"run_root": run_root})
        payload = normalized.model_dump(mode="json")
        tmp_path = self.run_file(record.run_id).with_suffix(".yaml.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=True, allow_unicode=False)
        os.replace(tmp_path, self.run_file(record.run_id))
        return normalized

    def load(self, run_id: str) -> RunRecord:
        path = self.run_file(run_id)
        if not path.is_file():
            raise AgentError(
                code="RUN-101",
                exit_code=2,
                message=f"run '{run_id}' does not exist.",
                resolution="Check the run id with k8s-agent status <run-id>.",
                context={"run_id": run_id},
            )
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return RunRecord.model_validate(payload)

    @contextmanager
    def acquire_lock(self, run_id: str) -> Iterator[None]:
        run_root = self.run_path(run_id)
        run_root.mkdir(parents=True, exist_ok=True)
        lock_path = run_root / "run.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise AgentError(
                code="RUN-202",
                exit_code=8,
                message=f"run '{run_id}' is already locked.",
                resolution="Wait for the current agent process to finish, then retry.",
                context={"run_id": run_id},
            ) from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
