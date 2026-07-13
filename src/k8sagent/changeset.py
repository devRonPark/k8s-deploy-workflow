from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from k8sagent.errors import ChangeSetError
from k8sagent.models.intent import AgentKubernetesIntent, get_intent_path, set_intent_path


class Change(BaseModel):
    op: Literal["set", "unset"]
    path: str
    value: str | int | bool | None = None

    @model_validator(mode="after")
    def _validate_value_required(self) -> "Change":
        if self.op == "set" and self.value is None:
            raise ValueError("set changes require a value")
        return self


class ChangeSet(BaseModel):
    changes: list[Change] = Field(min_length=1, max_length=20)
    origin: Literal["wizard", "nl_request", "correction", "answers_file"]
    summary: str = ""


class FieldDiff(BaseModel):
    path: str
    before: object | None
    after: object | None


def validate_changeset(cs: ChangeSet, intent: AgentKubernetesIntent) -> None:
    current = intent
    for index, change in enumerate(cs.changes):
        try:
            current = _apply_change(change, current, source=cs.origin)
        except ChangeSetError as exc:
            raise ChangeSetError(f"change {index} {change.path}: {exc}") from exc


def diff_changeset(cs: ChangeSet, intent: AgentKubernetesIntent) -> list[FieldDiff]:
    validate_changeset(cs, intent)
    current = intent
    diffs: list[FieldDiff] = []
    for change in cs.changes:
        before = get_intent_path(current, change.path)
        current = _apply_change(change, current, source=cs.origin)
        after = get_intent_path(current, change.path)
        diffs.append(FieldDiff(path=change.path, before=before, after=after))
    return diffs


def apply_changeset(
    cs: ChangeSet,
    intent: AgentKubernetesIntent,
    *,
    source: str,
) -> AgentKubernetesIntent:
    validate_changeset(cs, intent)
    current = intent
    for change in cs.changes:
        current = _apply_change(change, current, source=source)
    return current


def render_diff_text(diffs: list[FieldDiff]) -> str:
    return "\n".join(f"{diff.path}: {diff.before} -> {diff.after}" for diff in diffs)


def _apply_change(
    change: Change,
    intent: AgentKubernetesIntent,
    *,
    source: str,
) -> AgentKubernetesIntent:
    value = None if change.op == "unset" else change.value
    return set_intent_path(intent, change.path, value, source=source)
