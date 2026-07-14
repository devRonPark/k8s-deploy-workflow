from __future__ import annotations

import unittest

from k8s_agent.models.validation import ResourceRef, ValidationFinding
from k8s_agent.repair.strategies import strategy_for


class RepairStrategyTests(unittest.TestCase):
    def test_selector_and_target_port_are_repairable(self):
        for code in ["service_selector_mismatch", "service_target_port_mismatch"]:
            with self.subTest(code=code):
                self.assertIsNotNone(strategy_for(finding(code, repairable=True)))

    def test_approval_required_changes_are_not_repairable(self):
        for code in ["external_exposure_requires_confirmation", "pvc_size_requires_confirmation"]:
            with self.subTest(code=code):
                self.assertIsNone(strategy_for(finding(code, repairable=False)))


def finding(code: str, *, repairable: bool) -> ValidationFinding:
    return ValidationFinding(
        finding_id=f"VF-{code}",
        validator="internal",
        severity="error",
        resource_ref=ResourceRef(kind="Service", name="api-svc", path="base/api-service.yaml"),
        field_path="/spec",
        code=code,
        message=code,
        repairable=repairable,
    )


if __name__ == "__main__":
    unittest.main()
