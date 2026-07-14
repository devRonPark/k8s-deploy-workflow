from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.models.profile import DeploymentProfile, ProfileValue
from k8s_agent.render.renderer import ManifestRenderer


class ManifestRendererAcceptanceTests(unittest.TestCase):
    def test_single_service_bundle_uses_profile_only_and_omits_unapproved_ingress(self):
        profile = profile_for(external="private")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = ManifestRenderer().render(profile, Path(tmp))
            deployment = yaml.safe_load((Path(tmp) / "base" / "api-deployment.yaml").read_text(encoding="utf-8"))
            service = yaml.safe_load((Path(tmp) / "base" / "api-service.yaml").read_text(encoding="utf-8"))

            self.assertFalse((Path(tmp) / "base" / "api-ingress.yaml").exists())
            self.assertEqual(service["spec"]["selector"], deployment["spec"]["template"]["metadata"]["labels"])
            self.assertEqual(bundle.resource_refs[0].kind, "Deployment")
            self.assertNotIn("changethis", "".join(path.read_text(encoding="utf-8") for path in Path(tmp).rglob("*.yaml")))

    def test_public_exposure_writes_ingress(self):
        profile = profile_for(external="public", host="api.example.com")
        with tempfile.TemporaryDirectory() as tmp:
            ManifestRenderer().render(profile, Path(tmp))

            self.assertTrue((Path(tmp) / "base" / "api-ingress.yaml").is_file())


def profile_for(*, external: str, host: str | None = None) -> DeploymentProfile:
    values = {
        "/components/api/image": value("api:latest"),
        "/components/api/replicas": value(2),
        "/components/api/service": value({"port": 8000}),
        "/components/api/runtime_command": value("uvicorn main:app"),
        "/components/api/external_exposure": value(external, actor="user"),
        "/components/api/secret_ref": value({"name": "api-secret"}),
    }
    if host:
        values["/components/api/hostname"] = value(host, actor="user")
    return DeploymentProfile(revision=1, values=values)


def value(v, *, actor="policy") -> ProfileValue:
    return ProfileValue(value=v, decision_id=f"D-{v}", classification="policy_default", confidence="high", actor=actor, approval="explicit")


if __name__ == "__main__":
    unittest.main()
