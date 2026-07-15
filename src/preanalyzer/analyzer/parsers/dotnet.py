from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_JSON,
    CODE_INVALID_XML,
    CODE_READ_ERROR,
    ParseWarning,
)


@dataclass(frozen=True)
class ParsedDotnetProject:
    path: str
    project_name: str
    sdk: str | None
    assembly_name: str | None
    root_namespace: str | None
    target_frameworks: list[str] = field(default_factory=list)
    package_references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DotnetSolutionProject:
    name: str
    path: str


@dataclass(frozen=True)
class ParsedDotnetSolution:
    path: str
    projects: list[DotnetSolutionProject] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDotnetBuildMetadata:
    path: str
    property_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DotnetLaunchPort:
    profile: str
    port: int
    scheme: str


@dataclass(frozen=True)
class DotnetLaunchProfile:
    name: str
    command_name: str | None
    ports: list[DotnetLaunchPort] = field(default_factory=list)
    environment_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDotnetLaunchSettings:
    path: str
    profiles: list[DotnetLaunchProfile] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDotnetAppSettings:
    path: str
    configuration_keys: list[str] = field(default_factory=list)
    connection_string_names: list[str] = field(default_factory=list)


def parse_project(path: Path) -> ParsedDotnetProject:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    return ParsedDotnetProject(
        path=path.as_posix(),
        project_name=path.stem,
        sdk=_string(root.attrib.get("Sdk")),
        assembly_name=_find_text(root, "PropertyGroup/AssemblyName"),
        root_namespace=_find_text(root, "PropertyGroup/RootNamespace"),
        target_frameworks=_target_frameworks(root),
        package_references=_package_references(root),
    )


def try_parse_project(path: Path) -> ParsedDotnetProject | ParseWarning:
    try:
        return parse_project(path)
    except ET.ParseError as exc:
        return ParseWarning(path=str(path), parser="dotnet_project", message=str(exc), code=CODE_INVALID_XML)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="dotnet_project", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="dotnet_project", message=exc.strerror or "read error", code=CODE_READ_ERROR)


def parse_solution(path: Path) -> ParsedDotnetSolution:
    projects: list[DotnetSolutionProject] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^Project\("[^"]+"\) = "([^"]+)", "([^"]+\.(?:cs|fs|vb)proj)", "[^"]+"', line)
        if match is None:
            continue
        name, project_path = match.groups()
        projects.append(DotnetSolutionProject(name=name, path=project_path.replace("\\", "/")))
    return ParsedDotnetSolution(path=path.as_posix(), projects=sorted(projects, key=lambda item: item.path))


def try_parse_solution(path: Path) -> ParsedDotnetSolution | ParseWarning:
    try:
        return parse_solution(path)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="dotnet_solution", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="dotnet_solution", message=exc.strerror or "read error", code=CODE_READ_ERROR)


def parse_build_metadata(path: Path) -> ParsedDotnetBuildMetadata:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    property_names = sorted(
        {
            _local_name(child.tag)
            for group in _find_all(root, "PropertyGroup")
            for child in list(group)
            if _local_name(child.tag)
        }
    )
    return ParsedDotnetBuildMetadata(path=path.as_posix(), property_names=property_names)


def try_parse_build_metadata(path: Path) -> ParsedDotnetBuildMetadata | ParseWarning:
    try:
        return parse_build_metadata(path)
    except ET.ParseError as exc:
        return ParseWarning(path=str(path), parser="dotnet_build_metadata", message=str(exc), code=CODE_INVALID_XML)
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path),
            parser="dotnet_build_metadata",
            message="invalid text encoding",
            code=CODE_INVALID_ENCODING,
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path),
            parser="dotnet_build_metadata",
            message=exc.strerror or "read error",
            code=CODE_READ_ERROR,
        )


def parse_launch_settings(path: Path) -> ParsedDotnetLaunchSettings:
    document = json.loads(path.read_text(encoding="utf-8"))
    profiles = document.get("profiles") if isinstance(document, dict) else {}
    parsed_profiles: list[DotnetLaunchProfile] = []
    for name, raw_profile in sorted((profiles or {}).items()):
        if not isinstance(raw_profile, dict):
            continue
        env = raw_profile.get("environmentVariables")
        environment_names = sorted(str(key) for key in env.keys()) if isinstance(env, dict) else []
        parsed_profiles.append(
            DotnetLaunchProfile(
                name=str(name),
                command_name=_string(raw_profile.get("commandName")),
                ports=[
                    DotnetLaunchPort(profile=str(name), port=port, scheme=scheme)
                    for scheme, port in _ports_from_application_url(raw_profile.get("applicationUrl"))
                ],
                environment_names=environment_names,
            )
        )
    return ParsedDotnetLaunchSettings(path=path.as_posix(), profiles=parsed_profiles)


def try_parse_launch_settings(path: Path) -> ParsedDotnetLaunchSettings | ParseWarning:
    try:
        return parse_launch_settings(path)
    except json.JSONDecodeError as exc:
        return ParseWarning(path=str(path), parser="dotnet_launch_settings", message=str(exc), code=CODE_INVALID_JSON)
    except ValueError as exc:
        return ParseWarning(path=str(path), parser="dotnet_launch_settings", message=str(exc))
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path),
            parser="dotnet_launch_settings",
            message="invalid text encoding",
            code=CODE_INVALID_ENCODING,
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path),
            parser="dotnet_launch_settings",
            message=exc.strerror or "read error",
            code=CODE_READ_ERROR,
        )


def parse_appsettings(path: Path) -> ParsedDotnetAppSettings:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        document = {}
    connection_strings = document.get("ConnectionStrings")
    connection_string_names = (
        sorted(str(key) for key in connection_strings.keys()) if isinstance(connection_strings, dict) else []
    )
    return ParsedDotnetAppSettings(
        path=path.as_posix(),
        configuration_keys=_configuration_keys(document),
        connection_string_names=connection_string_names,
    )


def try_parse_appsettings(path: Path) -> ParsedDotnetAppSettings | ParseWarning:
    try:
        return parse_appsettings(path)
    except json.JSONDecodeError as exc:
        return ParseWarning(path=str(path), parser="dotnet_appsettings", message=str(exc), code=CODE_INVALID_JSON)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="dotnet_appsettings", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="dotnet_appsettings", message=exc.strerror or "read error", code=CODE_READ_ERROR)


def _target_frameworks(root: ET.Element) -> list[str]:
    frameworks: list[str] = []
    single = _find_text(root, "PropertyGroup/TargetFramework")
    if single:
        frameworks.append(single)
    many = _find_text(root, "PropertyGroup/TargetFrameworks")
    if many:
        frameworks.extend(item.strip() for item in many.split(";") if item.strip())
    return sorted(set(frameworks))


def _package_references(root: ET.Element) -> list[str]:
    packages: list[str] = []
    for item in _find_all(root, "ItemGroup/PackageReference"):
        package = item.attrib.get("Include") or item.attrib.get("Update")
        if package:
            packages.append(str(package))
    return sorted(set(packages))


def _find_text(root: ET.Element, path: str) -> str | None:
    node = _find(root, path)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _find(root: ET.Element, path: str) -> ET.Element | None:
    found = root.find(path)
    if found is not None:
        return found
    namespace = _namespace(root.tag)
    if not namespace:
        return None
    namespaced = "/".join(f"{{{namespace}}}{part}" for part in path.split("/"))
    return root.find(namespaced)


def _find_all(root: ET.Element, path: str) -> list[ET.Element]:
    found = root.findall(path)
    if found:
        return found
    namespace = _namespace(root.tag)
    if not namespace:
        return []
    namespaced = "/".join(f"{{{namespace}}}{part}" for part in path.split("/"))
    return root.findall(namespaced)


def _namespace(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _ports_from_application_url(value: object) -> list[tuple[str, int]]:
    if not isinstance(value, str):
        return []
    ports: list[tuple[str, int]] = []
    for raw_url in value.split(";"):
        parsed = urlparse(raw_url.strip())
        if parsed.scheme in {"http", "https"} and parsed.port is not None:
            ports.append((parsed.scheme, parsed.port))
    return sorted(set(ports), key=lambda item: (item[0] != "http", item[1]))


def _configuration_keys(document: dict[str, object]) -> list[str]:
    keys: list[str] = []

    def walk(prefix: str, value: object) -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                path = f"{prefix}:{key}" if prefix else str(key)
                keys.append(path)
                walk(path, child)

    walk("", document)
    return sorted(set(keys))


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
