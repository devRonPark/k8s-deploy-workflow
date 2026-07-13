from __future__ import annotations

from pathlib import Path

import yaml

from k8s_agent.models.profile import DeploymentProfile
from k8s_agent.models.validation import ValidationReport, ValidationStage
from k8s_agent.render.renderer import ManifestBundle
from k8s_agent.validation.internal import InternalManifestValidator, _finding
from k8s_agent.validation.kubeconform import KubeconformValidator
from k8s_agent.validation.kustomize import KustomizeValidator


class ValidationOrchestrator:
    def __init__(self, *, run_external: bool = False) -> None:
        self.run_external = run_external

    def validate(self, bundle: ManifestBundle, profile: DeploymentProfile, destination: Path) -> ValidationReport:
        del profile
        paths = [destination / file.path for file in bundle.files if file.path.endswith(".yaml")]
        stages: list[ValidationStage] = []
        findings = []

        syntax_findings = _syntax_findings(paths)
        stages.append(ValidationStage(stage="yaml-syntax", status="fail" if syntax_findings else "pass"))
        findings.extend(syntax_findings)

        internal_findings = InternalManifestValidator().validate_paths(paths)
        stages.append(ValidationStage(stage="internal", status="fail" if internal_findings else "pass"))
        findings.extend(internal_findings)

        if self.run_external:
            kustomize = KustomizeValidator(binary=Path("kustomize")).validate(paths)
            kubeconform = KubeconformValidator(binary=Path("kubeconform")).validate(paths)
        else:
            kustomize = KustomizeValidator(binary=None).validate(paths)
            kubeconform = ValidationReport(status="not-run", manifest_ready=False, stages=[ValidationStage(stage="kubeconform", status="not-run")])
        stages.extend(kustomize.stages)
        stages.extend(kubeconform.stages)
        findings.extend(kustomize.findings)
        findings.extend(kubeconform.findings)
        ready = not findings
        return ValidationReport(status="pass" if ready else "fail", manifest_ready=ready, stages=stages, findings=findings)


def _syntax_findings(paths: list[Path]):
    findings = []
    for path in paths:
        try:
            list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            findings.append(_finding("yaml-syntax", "error", None, "/", "yaml_syntax", str(exc)))
    return findings
