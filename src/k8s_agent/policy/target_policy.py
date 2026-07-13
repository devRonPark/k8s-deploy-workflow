from __future__ import annotations

from enum import StrEnum


POLICY_VERSION = "target-policy/v1"


class Target(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class PolicyDisposition(StrEnum):
    AUTO_CONFIRM = "auto_confirm"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    BLOCKED = "blocked"
