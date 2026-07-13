from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from k8sagent.errors import ChangeSetError
from k8sagent.gaps import UnresolvedField
from k8sagent.models.intent import AgentKubernetesIntent, set_intent_path
from k8sagent.models.topology import ApplicationTopology

AnswerType = Literal[
    "string",
    "int",
    "bool",
    "port",
    "k8s_name",
    "host",
    "registry",
    "image_tag",
    "quantity",
    "mount_path",
    "secret_key",
    "choice",
]


class Question(BaseModel):
    id: str
    path: str
    text: str
    answer_type: AnswerType
    candidates: list[str] = Field(default_factory=list)
    default: str | None = None
    severity: str


def build_questions(
    unresolved: list[UnresolvedField],
    topology: ApplicationTopology,
) -> list[Question]:
    ports = {
        component.component_id: str(component.port.value)
        for component in topology.components
        if component.port is not None and component.port.value is not None
    }
    questions: list[Question] = []
    for gap in unresolved:
        cid = _component_id(gap.path)
        answer_type = _answer_type(gap.path)
        candidates = [ports[cid]] if cid in ports and answer_type == "port" else []
        questions.append(
            Question(
                id=f"Q-{gap.path}",
                path=gap.path,
                text=_question_text(gap.path, cid),
                answer_type=answer_type,
                candidates=candidates,
                default="latest" if gap.path.endswith(".workload.image.tag") else None,
                severity=gap.severity,
            )
        )
    return questions


def parse_answer(question: Question, raw: str) -> object:
    value = raw.strip()
    if question.answer_type == "bool":
        lowered = value.lower()
        if lowered in {"y", "yes", "true", "1"}:
            return True
        if lowered in {"n", "no", "false", "0"}:
            return False
        raise ChangeSetError("expected boolean answer")
    if question.answer_type in {"int", "port"}:
        try:
            number = int(value)
        except ValueError as exc:
            raise ChangeSetError("expected integer answer") from exc
        if question.answer_type == "port" and not (1 <= number <= 65535):
            raise ChangeSetError("port out of range")
        return number
    if not value or "\n" in value or "\x00" in value:
        raise ChangeSetError("expected non-empty single-line answer")
    if question.answer_type == "k8s_name" and not re.match(
        r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", value
    ):
        raise ChangeSetError("invalid Kubernetes name")
    if question.answer_type == "host" and not re.match(
        r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$",
        value,
    ):
        raise ChangeSetError("invalid host")
    if question.answer_type == "registry" and not re.match(
        r"^[a-z0-9.-]+(:[0-9]{1,5})?(/[a-z0-9._/-]+)?$", value
    ):
        raise ChangeSetError("invalid image registry")
    if question.answer_type == "image_tag" and not re.match(
        r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$", value
    ):
        raise ChangeSetError("invalid image tag")
    if question.answer_type == "quantity" and not re.match(r"^[1-9][0-9]*(Gi|Mi)$", value):
        raise ChangeSetError("invalid storage quantity")
    if question.answer_type == "mount_path" and not value.startswith("/"):
        raise ChangeSetError("mount path must be absolute")
    if question.answer_type == "secret_key" and not re.match(r"^[-._a-zA-Z0-9]+$", value):
        raise ChangeSetError("invalid secret key")
    if question.answer_type == "choice" and value not in question.candidates:
        raise ChangeSetError("answer is not one of the candidates")
    return value


def apply_answer(
    intent: AgentKubernetesIntent,
    question: Question,
    value: object,
) -> AgentKubernetesIntent:
    return set_intent_path(intent, question.path, value, source="user_decision")


def _answer_type(path: str) -> AnswerType:
    if path == "namespace":
        return "k8s_name"
    if path == "create_namespace":
        return "bool"
    if path.endswith(".workload.image.registry"):
        return "registry"
    if path.endswith(".workload.image.name"):
        return "k8s_name"
    if path.endswith(".workload.image.tag"):
        return "image_tag"
    if path.endswith(".workload.replicas"):
        return "int"
    if path.endswith(".workload.container_port") or path.endswith(".service.port"):
        return "port"
    if path.endswith(".ingress.host"):
        return "host"
    if path.endswith(".pvc.size"):
        return "quantity"
    if path.endswith(".pvc.mount_path"):
        return "mount_path"
    if path.endswith(".secret_key"):
        return "secret_key"
    return "string"


def _component_id(path: str) -> str | None:
    parts = path.split(".")
    if len(parts) > 1 and parts[0] == "components":
        return parts[1]
    return None


def _question_text(path: str, component_id: str | None) -> str:
    if path == "namespace":
        return "Which namespace should contain the generated resources?"
    if component_id is None:
        return f"Provide a value for {path}."
    return f"Provide a value for component '{component_id}' field {path}."
