from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.pipeline import run_phase1_analysis


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


class Phase1DeterministicOutputTests(unittest.TestCase):
    def test_sample_repositories_generate_00_to_03_without_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)

            for repo_name in ["jpetstore-like", "fastapi-fullstack-like", "node-express-like"]:
                out_dir = output_root / repo_name
                run_phase1_analysis(
                    repo=FIXTURES / repo_name,
                    output_dir=out_dir,
                    url=f"fixture://{repo_name}",
                    ref="fixture",
                    clock=fixed_clock,
                )

                for filename in [
                    "00-repository-snapshot.yaml",
                    "01-artifact-inventory.yaml",
                    "02-evidence-model.yaml",
                    "03-rule-inference.yaml",
                ]:
                    self.assertTrue((out_dir / filename).is_file(), f"{repo_name}: {filename}")

                evidence = yaml.safe_load((out_dir / "02-evidence-model.yaml").read_text(encoding="utf-8"))
                rules = yaml.safe_load((out_dir / "03-rule-inference.yaml").read_text(encoding="utf-8"))
                serialized_output = "\n".join(
                    (out_dir / filename).read_text(encoding="utf-8")
                    for filename in [
                        "00-repository-snapshot.yaml",
                        "01-artifact-inventory.yaml",
                        "02-evidence-model.yaml",
                        "03-rule-inference.yaml",
                    ]
                )

                self.assertIn("evidence_model", evidence)
                self.assertIn("rule_inference", rules)
                self.assertNotIn("changethis", serialized_output)

            fastapi_rules = yaml.safe_load(
                (output_root / "fastapi-fullstack-like" / "03-rule-inference.yaml").read_text(encoding="utf-8")
            )
            roles = fastapi_rules["rule_inference"]["role_candidates"]
            self.assertIn(
                {
                    "component_id": "db",
                    "role": "dependency",
                    "source": "infra_image_pattern",
                    "confidence": "high",
                    "evidence_refs": ["F0018"],
                },
                roles,
            )


if __name__ == "__main__":
    unittest.main()
