from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet
from preanalyzer.models.semantic import SemanticTask
from preanalyzer.models.semantic_tools import (
    SemanticToolEvidence,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.path_safety import (
    is_excluded_rel_path,
    is_sensitive_rel_path,
    is_within as _is_relative_to,
)


MAX_FILE_BYTES = 1024 * 1024
MAX_READ_SOURCE_LINES = 120
MAX_SEARCH_MATCHES = 50
MAX_SEARCH_CONTEXT_LINES = 5
MAX_SCRIPT_CANDIDATES = 20
MAX_TARGET_RESULTS = 20

_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(?P<name>[A-Z0-9_.-]*(?:password|passwd|token|secret|api[_-]?key)[A-Z0-9_.-]*)\b"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>['\"]?[^'\"\s#]+['\"]?)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]+=*")
_API_KEY_RE = re.compile(r"\b(?:sk|pk|AKIA)[A-Za-z0-9_\-]{12,}\b")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


@dataclass(frozen=True)
class SemanticToolExecutionContext:
    repository_root: Path
    component_id: str
    component_root: Path
    target_field: str
    allowed_tools: tuple[str, ...]
    task_budget: object
    phase1_evidence_index: dict[str, EvidenceFact]


class SemanticToolContextBuildError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ToolBlockedError(ValueError):
    pass


class ToolUnsupportedError(ValueError):
    pass


def build_semantic_tool_context(
    repository_root: Path,
    task: SemanticTask,
    rules: RuleInferenceSet,
    evidence: EvidenceModel,
) -> SemanticToolExecutionContext:
    repo_root = Path(repository_root).resolve()
    components = [component for component in rules.component_candidates if component.component_id == task.component_id]
    if not components:
        raise SemanticToolContextBuildError("component_not_found", "component was not found")
    if len(components) > 1:
        raise SemanticToolContextBuildError("duplicate_component", "component id is not unique")

    component_root = _component_root(repo_root, components[0])
    if not _is_relative_to(component_root, repo_root):
        raise SemanticToolContextBuildError("component_root_outside_repository", "component root is outside repository")

    phase1_index = {fact.evidence_id: fact for fact in evidence.facts}
    referenced = _referenced_phase1_evidence(task)
    missing = sorted(ref for ref in referenced if ref not in phase1_index)
    if missing:
        raise SemanticToolContextBuildError("missing_phase1_evidence", "task references missing phase1 evidence")

    return SemanticToolExecutionContext(
        repository_root=repo_root,
        component_id=task.component_id,
        component_root=component_root,
        target_field=task.target_field,
        allowed_tools=tuple(task.allowed_tools),
        task_budget=task.budget,
        phase1_evidence_index=phase1_index,
    )


def ok_result(
    tool_name: SemanticToolName,
    *,
    evidence: list[SemanticToolEvidence] | None = None,
    observations: list[dict] | None = None,
    usage: SemanticToolUsage | None = None,
    message: str | None = None,
) -> SemanticToolResult:
    return SemanticToolResult(
        tool_name=tool_name,
        status=SemanticToolResultStatus.OK,
        evidence=evidence or [],
        observations=observations or [],
        usage=usage or SemanticToolUsage(),
        message=message,
    )


def result(
    tool_name: SemanticToolName,
    status: SemanticToolResultStatus,
    message: str,
    *,
    usage: SemanticToolUsage | None = None,
) -> SemanticToolResult:
    return SemanticToolResult(tool_name=tool_name, status=status, usage=usage or SemanticToolUsage(), message=message)


def resolve_existing_file(context: SemanticToolExecutionContext, user_path: str) -> Path:
    candidate = resolve_component_path(context, user_path)
    if not candidate.exists():
        raise FileNotFoundError
    if not candidate.is_file():
        raise ToolUnsupportedError("path is not a regular file")
    if candidate.is_symlink() and not _is_relative_to(candidate.resolve(), context.repository_root):
        raise ToolBlockedError("path is outside repository")
    return candidate.resolve()


def resolve_component_path(context: SemanticToolExecutionContext, user_path: str) -> Path:
    raw = PurePosixPath(user_path)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        raise ToolBlockedError("path is outside component scope")
    if not str(user_path).strip():
        raise ToolBlockedError("path is outside component scope")
    joined = (context.component_root / Path(*raw.parts)).resolve()
    if not _is_relative_to(joined, context.repository_root) or not _is_relative_to(joined, context.component_root):
        raise ToolBlockedError("path is outside component scope")
    rel = relative_repo_path(context, joined)
    if is_excluded_rel_path(rel):
        raise ToolBlockedError("path is excluded")
    if is_sensitive_rel_path(rel):
        raise ToolBlockedError("path is sensitive")
    return joined


def read_text_file(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ToolUnsupportedError("file exceeds size limit")
    data = path.read_bytes()
    if b"\x00" in data:
        raise ToolUnsupportedError("binary files are not supported")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolUnsupportedError("file is not valid utf-8") from exc


def iter_component_files(context: SemanticToolExecutionContext, root: Path | None = None) -> Iterable[Path]:
    base = root or context.component_root
    for path in sorted(base.rglob("*"), key=lambda candidate: relative_repo_path(context, candidate)):
        if not path.is_file():
            continue
        try:
            rel = relative_repo_path(context, path.resolve())
        except ValueError:
            continue
        if not _is_relative_to(path.resolve(), context.component_root):
            continue
        if is_excluded_rel_path(rel) or is_sensitive_rel_path(rel):
            continue
        yield path


def relative_repo_path(context: SemanticToolExecutionContext, path: Path) -> str:
    return path.resolve().relative_to(context.repository_root).as_posix()


def redacted(text: str) -> str:
    text = _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    text = _ASSIGNMENT_SECRET_RE.sub(lambda match: f"{match.group('name')}{match.group('sep')}[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    return _API_KEY_RE.sub("[REDACTED_API_KEY]", text)


def make_evidence(
    tool_name: SemanticToolName,
    context: SemanticToolExecutionContext,
    path: Path,
    start_line: int,
    end_line: int,
    excerpt: str,
) -> SemanticToolEvidence:
    rel = relative_repo_path(context, path)
    excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    payload = json.dumps(
        {
            "tool_name": tool_name.value,
            "path": rel,
            "start_line": start_line,
            "end_line": end_line,
            "excerpt_hash": excerpt_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()
    return SemanticToolEvidence(
        evidence_id=f"SE-{digest}",
        tool_name=tool_name,
        path=rel,
        start_line=start_line,
        end_line=end_line,
        excerpt=excerpt,
        excerpt_hash=excerpt_hash,
    )


def line_excerpt(lines: list[str], start_line: int, end_line: int) -> str:
    selected = lines[start_line - 1:end_line]
    return redacted("\n".join(f"{line_no}: {line}" for line_no, line in zip(range(start_line, end_line + 1), selected)))


def source_line_budget(context: SemanticToolExecutionContext) -> int:
    return int(getattr(context.task_budget, "max_source_lines", 0))


def _component_root(repo_root: Path, component: ComponentCandidate) -> Path:
    root_path = component.root_path
    if root_path in {None, "."}:
        return repo_root
    raw = PurePosixPath(str(root_path))
    if raw.is_absolute():
        return Path(str(root_path)).resolve()
    if any(part == ".." for part in raw.parts):
        return (repo_root / Path(*raw.parts)).resolve()
    return (repo_root / Path(*raw.parts)).resolve()


def _referenced_phase1_evidence(task: SemanticTask) -> set[str]:
    refs = {ref.evidence_id for ref in task.evidence_refs if ref.origin == "phase1"}
    refs.update(task.reason.evidence_refs)
    for candidate in task.known_candidates:
        refs.update(candidate.evidence_refs)
    return {ref for ref in refs if ref}
