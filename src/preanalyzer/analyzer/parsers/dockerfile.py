from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

from preanalyzer.models.fields import Confidence, Tracked


@dataclass(frozen=True)
class ParsedDockerfile:
    path: str
    expose_ports: list[Tracked[int]]
    cmd: Tracked[str] | None = None
    entrypoint: Tracked[str] | None = None
    base_image: Tracked[str] | None = None
    user: Tracked[str] | None = None


def parse(path: Path) -> ParsedDockerfile:
    expose_ports: list[Tracked[int]] = []
    cmd: Tracked[str] | None = None
    entrypoint: Tracked[str] | None = None
    base_image: Tracked[str] | None = None
    user: Tracked[str] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        rest = rest.strip()
        if keyword == "FROM":
            image = rest.split(" AS ", 1)[0].split(" as ", 1)[0].strip()
            base_image = Tracked(image, "dockerfile_from", Confidence.HIGH)
            expose_ports = []
            cmd = None
            entrypoint = None
            user = None
        elif keyword == "EXPOSE":
            expose_ports.extend(_parse_expose_ports(rest))
        elif keyword == "CMD":
            cmd = Tracked(rest, "dockerfile_cmd", Confidence.HIGH)
        elif keyword == "ENTRYPOINT":
            entrypoint = Tracked(rest, "dockerfile_entrypoint", Confidence.HIGH)
        elif keyword == "USER":
            user = Tracked(rest, "dockerfile_user", Confidence.HIGH)

    return ParsedDockerfile(
        path=path.as_posix(),
        expose_ports=expose_ports,
        cmd=cmd,
        entrypoint=entrypoint,
        base_image=base_image,
        user=user,
    )


def _parse_expose_ports(value: str) -> list[Tracked[int]]:
    ports: list[Tracked[int]] = []
    for token in shlex.split(value):
        port_text = token.split("/", 1)[0]
        try:
            ports.append(Tracked(int(port_text), "dockerfile_expose", Confidence.HIGH))
        except ValueError:
            continue
    return ports
