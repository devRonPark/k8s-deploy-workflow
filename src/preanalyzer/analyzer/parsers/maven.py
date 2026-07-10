from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from preanalyzer.models.fields import Confidence, Tracked


@dataclass(frozen=True)
class ParsedMaven:
    path: str
    packaging: Tracked[str]
    modules: list[str]

    @property
    def is_multi_module(self) -> bool:
        return bool(self.modules)


@dataclass(frozen=True)
class ParseWarning:
    path: str
    parser: str
    message: str


def parse(path: Path) -> ParsedMaven:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    packaging = _find_text(root, "packaging") or "jar"
    modules = [module.text.strip() for module in _find_all(root, "modules/module") if module.text]
    return ParsedMaven(
        path=path.as_posix(),
        packaging=Tracked(packaging, "pom.xml", Confidence.HIGH),
        modules=modules,
    )


def try_parse(path: Path) -> ParsedMaven | ParseWarning:
    try:
        return parse(path)
    except Exception as exc:
        return ParseWarning(path=str(path), parser="maven", message=str(exc))


def _find_text(root: ET.Element, path: str) -> str | None:
    node = _find(root, path)
    if node is None or node.text is None:
        return None
    return node.text.strip()


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
