from __future__ import annotations

import shutil
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.models.source import Workspace
from k8s_agent.run.ids import safe_run_path


class WorkspaceManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def create(self, run_id: str) -> Workspace:
        root = safe_run_path(self.base_dir, run_id) / "workspace"
        source_path = root / "source"
        generated_path = root / "generated"
        source_path.mkdir(parents=True, exist_ok=True)
        generated_path.mkdir(parents=True, exist_ok=True)
        return Workspace(run_id=run_id, root=root, source_path=source_path, generated_path=generated_path)

    def cleanup(self, workspace: Workspace) -> None:
        try:
            shutil.rmtree(workspace.root)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise AgentError(
                code="SOURCE-301",
                exit_code=8,
                message=f"failed to clean workspace for run '{workspace.run_id}'.",
                resolution="Remove the run workspace manually after checking no agent process is active.",
                context={"run_id": workspace.run_id, "workspace": str(workspace.root)},
            ) from exc
