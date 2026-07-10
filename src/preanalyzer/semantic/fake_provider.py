from __future__ import annotations

from preanalyzer.models.semantic_agent import AgentAction, SemanticDecisionContext


class ScriptedFakeDecisionProvider:
    """Deterministic provider that returns one scripted action per decision."""

    def __init__(self, actions: list[AgentAction]):
        self._actions = list(actions)
        self._index = 0
        self.contexts: list[SemanticDecisionContext] = []

    @property
    def call_count(self) -> int:
        return self._index

    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        self.contexts.append(context)
        if self._index >= len(self._actions):
            raise RuntimeError("scripted decision provider exhausted")
        action = self._actions[self._index]
        self._index += 1
        return action
