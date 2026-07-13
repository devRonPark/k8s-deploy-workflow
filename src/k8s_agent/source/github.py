from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from k8s_agent.errors import AgentError
from k8s_agent.models.source import AcquiredSource, GitMetadata, RepositorySource, ScanLimits, Workspace
from k8s_agent.source.fingerprint import build_source_fingerprint
from k8s_agent.source.git_runner import GitResult, GitRunner


SAFE_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_LFS_SKIP_SMUDGE": "1",
    "GIT_TERMINAL_PROMPT": "0",
}


class GitHubSourceResolver:
    def __init__(self, git: GitRunner | None = None, limits: ScanLimits | None = None) -> None:
        self.git = git or GitRunner()
        self.limits = limits or ScanLimits()

    def acquire(
        self,
        url: str,
        requested_ref: str | None,
        workspace: Workspace,
        acquired_at: datetime,
    ) -> AcquiredSource:
        sanitized_url = sanitize_github_url(url)
        ref = requested_ref or "HEAD"
        _check(self.git.run(workspace.source_path, ["init"], env=SAFE_GIT_ENV), "SOURCE-202", sanitized_url, ref)
        _check(
            self.git.run(workspace.source_path, ["remote", "add", "origin", sanitized_url], env=SAFE_GIT_ENV),
            "SOURCE-202",
            sanitized_url,
            ref,
        )
        fetch = self.git.run(workspace.source_path, ["fetch", "--depth", "1", "origin", ref], env=SAFE_GIT_ENV)
        if fetch.returncode != 0:
            code = "SOURCE-201" if _looks_like_missing_ref(fetch) else "SOURCE-202"
            raise _source_error(code, sanitized_url, ref)
        _check(
            self.git.run(workspace.source_path, ["checkout", "--detach", "FETCH_HEAD"], env=SAFE_GIT_ENV),
            "SOURCE-202",
            sanitized_url,
            ref,
        )
        resolved_commit = self.git.output(workspace.source_path, ["rev-parse", "HEAD"])
        if resolved_commit is None:
            raise _source_error("SOURCE-203", sanitized_url, ref)
        source = RepositorySource(
            kind="github",
            path=workspace.source_path,
            acquired_at=acquired_at,
            git=GitMetadata(
                is_repository=True,
                branch=None,
                head=resolved_commit,
                dirty=False,
                modified_files=[],
                untracked_files=[],
            ),
            fingerprint=build_source_fingerprint(workspace.source_path, self.limits),
        )
        return AcquiredSource(source=source, requested_ref=requested_ref, resolved_commit=resolved_commit)


def sanitize_github_url(url: str) -> str:
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url.removeprefix("git@github.com:")
    parts = urlsplit(url)
    if parts.scheme in {"http", "https"} and parts.hostname:
        netloc = parts.hostname
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return url


def _check(result: GitResult, code: str, url: str, ref: str) -> None:
    if result.returncode != 0:
        raise _source_error(code, url, ref)


def _looks_like_missing_ref(result: GitResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "remote ref" in text or "couldn't find" in text or "not found" in text


def _source_error(code: str, url: str, ref: str) -> AgentError:
    messages = {
        "SOURCE-201": f"remote ref '{ref}' could not be resolved.",
        "SOURCE-202": "github source acquisition failed.",
        "SOURCE-203": "github source checkout did not produce a commit SHA.",
    }
    return AgentError(
        code=code,
        exit_code=2,
        message=messages[code],
        resolution="Check the repository URL, ref, and access permissions, then retry.",
        context={"repo_url": url, "ref": ref},
    )
