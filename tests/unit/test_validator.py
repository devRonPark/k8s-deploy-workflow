import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

            with patch("preanalyzer.validator.pipeline.shutil.which", return_value=None):
                report = ValidationPipeline().run(directory)

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


if __name__ == "__main__":
    unittest.main()
