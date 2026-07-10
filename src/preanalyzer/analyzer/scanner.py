from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
import fnmatch
import subprocess

import yaml

from preanalyzer import __version__
from preanalyzer.models.inventory import ArtifactInventory, ArtifactItem
from preanalyzer.models.snapshot import RepositorySnapshot
from preanalyzer.rules_version import RULES_VERSION


EXCLUDED_PATTERNS = [
    ".git/**",
    "**/.git/**",
    "node_modules/**",
    "**/node_modules/**",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
]

COMPOSE_NAMES = {
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "docker-compose.override.yaml",
    "docker-compose.override.yml",
}

BUILD_FILE_TYPES = {
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "package.json": "nodejs",
    "go.mod": "go",
    "requirements.txt": "python_requirements",
    "pyproject.toml": "python_pyproject",
}

APP_CONFIG_NAMES = {
    "application.properties": "java_properties",
    "application.yml": "application_yaml",
    "application.yaml": "application_yaml",
}


def snapshot(
    repo: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
) -> RepositorySnapshot:
    repo = Path(repo)
    warnings: list[str] = []
    commit_sha = _git_output(repo, ["rev-parse", "HEAD"])
    if commit_sha is None:
        warnings.append("not a git repository")

    default_branch = _default_branch(repo)
    analyzed_at = _format_utc(clock())

    return RepositorySnapshot(
        url=url,
        ref=ref,
        commit_sha=commit_sha,
        analyzed_at=analyzed_at,
        archived=False,
        default_branch=default_branch,
        analyzer_version=__version__,
        rules_version=RULES_VERSION,
        file_count=sum(1 for _ in _iter_files(repo)),
        excluded_patterns=list(EXCLUDED_PATTERNS),
        warnings=warnings,
    )


def build_inventory(repo: Path, snapshot: RepositorySnapshot) -> ArtifactInventory:
    del snapshot
    repo = Path(repo)
    build_files: list[ArtifactItem] = []
    container_files: list[ArtifactItem] = []
    compose_files: list[ArtifactItem] = []
    kubernetes_manifests: list[ArtifactItem] = []
    helm_charts: list[ArtifactItem] = []
    kustomize_dirs: list[ArtifactItem] = []
    ci_cd: list[ArtifactItem] = []
    app_configs: list[ArtifactItem] = []
    docs: list[ArtifactItem] = []

    for path in _iter_files(repo):
        rel = _rel(path, repo)
        name = path.name
        lower_name = name.lower()

        if _is_dockerfile(path):
            container_files.append({"path": rel, "type": "dockerfile", "present": True})

        if lower_name in COMPOSE_NAMES:
            compose_files.append({"path": rel, "type": "compose"})

        build_type = _build_file_type(path)
        if build_type is not None:
            build_files.append({"path": rel, "type": build_type})

        if _is_kubernetes_manifest(path):
            kubernetes_manifests.append({"path": rel, "type": "kubernetes_manifest"})

        if name == "Chart.yaml":
            helm_charts.append({"path": rel, "type": "helm_chart"})

        if lower_name in {"kustomization.yaml", "kustomization.yml"}:
            kustomize_dirs.append({"path": str(Path(rel).parent), "type": "kustomize"})

        ci_type = _ci_cd_type(path, rel)
        if ci_type is not None:
            ci_cd.append({"path": rel, "type": ci_type})

        app_config_type = _app_config_type(path)
        if app_config_type is not None:
            app_configs.append({"path": rel, "type": app_config_type})

        if name == "README.md" or lower_name.endswith(".md"):
            docs.append({"path": rel})

    if not container_files:
        container_files.append({"path": "Dockerfile", "type": "dockerfile", "present": False})

    return ArtifactInventory(
        build_files=_sorted_items(build_files),
        container_files=_sorted_items(container_files),
        compose_files=_sorted_items(compose_files),
        kubernetes_manifests=_sorted_items(kubernetes_manifests),
        helm_charts=_sorted_items(helm_charts),
        kustomize_dirs=_sorted_items(kustomize_dirs),
        ci_cd=_sorted_items(ci_cd),
        app_configs=_sorted_items(app_configs),
        docs=_sorted_items(docs),
    )


def _iter_files(repo: Path) -> Iterable[Path]:
    for path in sorted(repo.rglob("*"), key=lambda p: _rel(p, repo)):
        if not path.is_file():
            continue
        rel = _rel(path, repo)
        if _is_excluded(rel):
            continue
        yield path


def _is_excluded(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in EXCLUDED_PATTERNS)


def _rel(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def _sorted_items(items: list[ArtifactItem]) -> list[ArtifactItem]:
    return sorted(items, key=lambda item: str(item["path"]))


def _is_dockerfile(path: Path) -> bool:
    return path.name == "Dockerfile" or path.name.startswith("Dockerfile.")


def _build_file_type(path: Path) -> str | None:
    if path.name in BUILD_FILE_TYPES:
        return BUILD_FILE_TYPES[path.name]
    if path.suffix == ".csproj":
        return "dotnet_project"
    if path.suffix == ".sln":
        return "dotnet_solution"
    return None


def _app_config_type(path: Path) -> str | None:
    name = path.name
    lower_name = name.lower()
    if lower_name.startswith(".env"):
        return "env"
    if name in APP_CONFIG_NAMES:
        return APP_CONFIG_NAMES[name]
    if lower_name.startswith("application") and lower_name.endswith((".yml", ".yaml")):
        return "application_yaml"
    if lower_name.startswith("application") and lower_name.endswith(".properties"):
        return "java_properties"
    return None


def _ci_cd_type(path: Path, rel: str) -> str | None:
    if rel.startswith(".github/workflows/") and path.suffix.lower() in {".yml", ".yaml"}:
        return "github_actions"
    if path.name == ".gitlab-ci.yml":
        return "gitlab_ci"
    if path.name == "Jenkinsfile":
        return "jenkins"
    return None


def _is_kubernetes_manifest(path: Path) -> bool:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return False
    if path.name.lower() in COMPOSE_NAMES:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    try:
        documents = yaml.safe_load_all(text)
        return any(isinstance(doc, dict) and "apiVersion" in doc and "kind" in doc for doc in documents)
    except yaml.YAMLError:
        return False


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_output(repo: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _default_branch(repo: Path) -> str | None:
    remote_head = _git_output(repo, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if remote_head:
        return remote_head.removeprefix("origin/")
    return _git_output(repo, ["branch", "--show-current"])
