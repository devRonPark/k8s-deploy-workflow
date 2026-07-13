from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO

from k8sagent.analysis import OUTPUT_DIR_NAME, run_agent_analysis
from k8sagent.changeset import Change, ChangeSet, apply_changeset, diff_changeset, render_diff_text
from k8sagent.components import apply_selection, extract_candidates
from k8sagent.config import AgentConfig
from k8sagent.gaps import find_unresolved
from k8sagent.llm import LLMProtocol
from k8sagent.models.intent import AgentKubernetesIntent, build_intent
from k8sagent.models.topology import build_topology, write_topology
from k8sagent.questions import apply_answer, build_questions, parse_answer
from k8sagent.render import render_all, write_manifests
from k8sagent.repo import acquire_local
from k8sagent.session import SessionState, SessionStore, advance
from k8sagent.validate import run_validation, write_report


@dataclass
class Console:
    input_fn: Callable[[str], str] = input
    out: TextIO = sys.stdout

    def ask(self, prompt: str) -> str:
        return self.input_fn(prompt)

    def say(self, text: str) -> None:
        print(text, file=self.out)

    def confirm(self, prompt: str) -> bool:
        return self.ask(prompt).strip().lower() in {"y", "yes"}


class Wizard:
    def __init__(
        self,
        *,
        config: AgentConfig,
        store: SessionStore,
        console,
        llm: LLMProtocol | None,
        runner=None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.console = console
        self.llm = llm
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, resume_session_id: str | None = None) -> int:
        if resume_session_id is not None:
            self.console.say("resume is not implemented for this MVP path")
            return 1
        repo_path = self.console.ask("Repository path: ")
        acquired = acquire_local(repo_path)
        session = self.store.create(
            k8s_version=self.config.k8s_version,
            llm_enabled=self.llm is not None,
        )
        output_dir = acquired.repo_path / OUTPUT_DIR_NAME
        session = session.model_copy(
            update={
                "source": acquired.source,
                "repo_path": str(acquired.repo_path),
                "output_dir": str(output_dir),
            }
        )
        session = advance(session, SessionState.REPO_READY, self.store.clock)
        bundle = run_agent_analysis(acquired.repo_path, url=None, ref=None, clock=self.store.clock)
        session = advance(session, SessionState.ANALYZED, self.store.clock)

        candidates = extract_candidates(bundle)
        selection = apply_selection(bundle, [candidate.component_id for candidate in candidates])
        topology = build_topology(bundle, selection)
        intent = build_intent(topology, bundle.reconciliation.intent)
        write_topology(topology, output_dir / "analysis")
        session = session.model_copy(
            update={
                "selected_components": selection.selected,
                "excluded_components": selection.excluded,
            }
        )
        session = advance(session, SessionState.COMPONENTS_SELECTED, self.store.clock)
        session = advance(session, SessionState.INTENT_DRAFTED, self.store.clock)

        for question in build_questions(find_unresolved(intent), topology):
            text = self.llm.phrase_question(question) if self.llm is not None else None
            prompt = text or question.text
            if question.default is not None:
                prompt = f"{prompt} [{question.default}]"
            raw = self.console.ask(prompt + ": ")
            if not raw and question.default is not None:
                raw = question.default
            try:
                intent = apply_answer(intent, question, parse_answer(question, raw))
            except Exception as exc:
                self.console.say(f"skipped: {exc}")

        session = advance(session, SessionState.INTENT_RESOLVED, self.store.clock)
        self.store.save(session)

        while True:
            self.console.say(_plan(intent))
            command = self.console.ask("approve, nl <request>, set <path> <value>, quit: ")
            if command == "quit":
                return 0
            if command == "approve":
                return self._approve(session, intent)
            if command.startswith("nl ") and self.llm is not None:
                cs = self.llm.nl_to_changeset(command[3:], intent, _allowed_paths(intent))
                if cs is None:
                    self.console.say("could not structure request")
                    continue
                self.console.say(render_diff_text(diff_changeset(cs, intent)))
                if self.console.confirm("apply? "):
                    intent = apply_changeset(cs, intent, source="user_decision")
                    self.console.say("applied")
                else:
                    self.console.say("discarded")
                continue
            if command.startswith("set "):
                _cmd, path, value = command.split(" ", 2)
                cs = ChangeSet(origin="wizard", changes=[Change(op="set", path=path, value=value)])
                intent = apply_changeset(cs, intent, source="user_decision")

    def _approve(self, session, intent: AgentKubernetesIntent) -> int:
        output_dir = Path(session.output_dir)
        commit_sha = session.source.commit_sha if session.source is not None else None
        write_manifests(render_all(intent, commit_sha), output_dir / "manifests")
        report = run_validation(
            output_dir / "manifests",
            intent,
            k8s_version=self.config.k8s_version,
            kubeconform_path=self.config.kubeconform_path,
            project_root=Path.cwd(),
        )
        write_report(report, output_dir / "validation")
        self.console.say(report.aggregate)
        return 0


def run_start(args, config: AgentConfig) -> int:
    store = SessionStore(config.home)
    return Wizard(config=config, store=store, console=Console(), llm=None).run(
        getattr(args, "session", None)
    )


def _plan(intent: AgentKubernetesIntent) -> str:
    return "\n".join(
        f"{component.component_id}: ready"
        for component in intent.components
        if component.role == "application"
    )


def _allowed_paths(intent: AgentKubernetesIntent) -> list[str]:
    paths = ["namespace"]
    for component in intent.components:
        paths.extend(
            [
                f"components.{component.component_id}.workload.image.registry",
                f"components.{component.component_id}.workload.image.tag",
                f"components.{component.component_id}.service.port",
                f"components.{component.component_id}.workload.container_port",
            ]
        )
    return paths
