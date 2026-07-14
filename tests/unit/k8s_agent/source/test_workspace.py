from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.source.workspace import WorkspaceManager


class WorkspaceManagerTests(unittest.TestCase):
    def test_create_separates_source_and_generated_paths_and_cleanup_removes_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkspaceManager(Path(tmp))

            workspace = manager.create("run-001")
            (workspace.source_path / "README.md").write_text("source", encoding="utf-8")
            (workspace.generated_path / "manifest.yaml").write_text("generated", encoding="utf-8")

            self.assertTrue(workspace.source_path.is_dir())
            self.assertTrue(workspace.generated_path.is_dir())
            self.assertNotEqual(workspace.source_path, workspace.generated_path)

            manager.cleanup(workspace)

            self.assertFalse(workspace.root.exists())

    def test_rejects_run_id_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkspaceManager(Path(tmp))

            with self.assertRaisesRegex(AgentError, "RUN-001"):
                manager.create("../escape")


if __name__ == "__main__":
    unittest.main()
