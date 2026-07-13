from __future__ import annotations


class AgentError(Exception):
    code: str = "agent_error"


class ConfigError(AgentError):
    code = "config_error"


class RepoAcquisitionError(AgentError):
    code = "repo_acquisition_error"


class SessionError(AgentError):
    code = "session_error"


class AnalysisError(AgentError):
    code = "analysis_error"


class ChangeSetError(AgentError):
    code = "changeset_error"


class RenderError(AgentError):
    code = "render_error"


class ValidationRunError(AgentError):
    code = "validation_run_error"


class LLMUnavailableError(AgentError):
    code = "llm_unavailable"
