import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from preanalyzer.validator.kubeconform_tool import resolve_kubeconform
from preanalyzer.validator.pipeline import ValidationPipeline


def _write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def test_broken_yaml_fails_syntax_then_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "bad.yaml", "a: [1, 2\n")

            report = ValidationPipeline().run(directory)

        stages = {stage.stage: stage.status for stage in report.stages}
        self.assertEqual(stages["yaml_syntax"], "fail")
        self.assertEqual(stages["kubeconform"], "skipped")
        self.assertEqual(report.achieved_level, 0)

    def test_missing_kubeconform_is_skipped_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")

            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value=None):
                    report = ValidationPipeline(repo_root=directory).run(directory)

        stages = {stage.stage: stage.status for stage in report.stages}
        self.assertEqual(stages["yaml_syntax"], "pass")
        self.assertEqual(stages["kubeconform"], "skipped")
        self.assertEqual(report.achieved_level, 0)

    def test_placeholder_capped_at_level0(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")

            report = ValidationPipeline().run(directory, rendered_placeholders=True)

        self.assertEqual(report.achieved_level, 0)


class KubeconformResolverTests(unittest.TestCase):
    def test_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "kc"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            self.assertEqual(resolve_kubeconform(Path(tmp), explicit_path=exe), str(exe))

    def test_managed_path_wins_over_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            managed = repo / ".tools" / "kubeconform" / "v0.8.0" / "linux-amd64" / "kubeconform"
            managed.parent.mkdir(parents=True)
            managed.write_text("#!/bin/sh\n", encoding="utf-8")
            managed.chmod(0o755)
            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value="/usr/bin/kubeconform"):
                    self.assertEqual(resolve_kubeconform(repo), str(managed))

    def test_missing_managed_and_path_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value=None):
                    self.assertIsNone(resolve_kubeconform(Path(tmp)))


class ValidatorKubeconformCommandTests(unittest.TestCase):
    def test_pipeline_uses_explicit_kubeconform_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")
            exe = directory / "kc"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            completed = Mock(returncode=0, stdout="summary ok", stderr="")
            with patch("preanalyzer.validator.pipeline.subprocess.run", return_value=completed) as run:
                report = ValidationPipeline(k8s_version="1.30", kubeconform_path=exe, repo_root=directory).run(
                    directory
                )
        self.assertEqual(report.stages[1].stage, "kubeconform")
        self.assertEqual(report.stages[1].status, "pass")
        self.assertEqual(
            run.call_args_list[0].args[0],
            [str(exe), "-strict", "-summary", "-kubernetes-version", "1.30.0", str(directory)],
        )

    def test_pipeline_preserves_master_kubernetes_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")
            exe = directory / "kc"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            completed = Mock(returncode=0, stdout="summary ok", stderr="")
            with patch("preanalyzer.validator.pipeline.subprocess.run", return_value=completed) as run:
                ValidationPipeline(k8s_version="master", kubeconform_path=exe, repo_root=directory).run(directory)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [str(exe), "-strict", "-summary", "-kubernetes-version", "master", str(directory)],
        )


if __name__ == "__main__":
    unittest.main()
