from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from k8sagent.errors import ConfigError

_FILE_KEYS = {"k8s_version", "llm_enabled", "git_token_env", "kubeconform_path"}
_TRUTHY = {"1", "true", "yes"}


class AgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    home: Path
    k8s_version: str = "1.29"
    git_token_env: str = "K8S_AGENT_GIT_TOKEN"
    llm_enabled: bool = True
    kubeconform_path: Path | None = None


def load_config(
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    home_override: Path | None = None,
) -> AgentConfig:
    import os

    env = os.environ if env is None else env
    home = Path(home_override or env.get("K8S_AGENT_HOME") or Path.home() / ".k8s-agent")

    merged: dict[str, object] = {"home": home}
    config_file = home / "config.yaml"
    if config_file.is_file():
        try:
            raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid config file: {config_file}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"invalid config file: {config_file}")
        unknown = set(raw) - _FILE_KEYS
        if unknown:
            raise ConfigError(f"unknown config keys in {config_file}: {sorted(unknown)}")
        merged.update(raw)

    if env.get("K8S_AGENT_K8S_VERSION"):
        merged["k8s_version"] = env["K8S_AGENT_K8S_VERSION"]
    if env.get("K8S_AGENT_NO_LLM", "").lower() in _TRUTHY:
        merged["llm_enabled"] = False
    if env.get("K8S_AGENT_KUBECONFORM_PATH"):
        merged["kubeconform_path"] = env["K8S_AGENT_KUBECONFORM_PATH"]

    for key, value in (cli_overrides or {}).items():
        if value is not None:
            merged[key] = value

    try:
        return AgentConfig(**merged)
    except ValidationError as exc:
        raise ConfigError("invalid agent configuration") from exc
