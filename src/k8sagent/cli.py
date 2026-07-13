from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from k8sagent.analysis import OUTPUT_DIR_NAME, run_agent_analysis
from k8sagent.changeset import Change, ChangeSet, apply_changeset
from k8sagent.components import apply_selection, extract_candidates
from k8sagent.config import load_config
from k8sagent.errors import AgentError
from k8sagent.gaps import find_unresolved
from k8sagent.models.intent import AgentKubernetesIntent, build_intent
from k8sagent.models.report import AgentValidationReport
from k8sagent.models.topology import ApplicationTopology, build_topology, write_topology
from k8sagent.questions import build_questions
from k8sagent.render import render_all, write_manifests
from k8sagent.repo import acquire_git, acquire_local, is_git_url
from k8sagent.session import AgentSession, SessionState, SessionStore, advance
from k8sagent.validate import run_validation, write_report


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        cfg = load_config(
            cli_overrides={
                "k8s_version": getattr(args, "k8s_version", None),
                "llm_enabled": False if getattr(args, "no_llm", False) else None,
            }
        )
        store = SessionStore(cfg.home)
        if args.command == "analyze":
            return _cmd_analyze(args, cfg, store)
        if args.command == "select":
            return _cmd_select(args, store)
        if args.command == "answer":
            return _cmd_answer(args, store)
        if args.command == "generate":
            return _cmd_generate(args, store)
        if args.command == "validate":
            return _cmd_validate(args, cfg, store)
        if args.command == "sessions":
            return _cmd_sessions(args, store)
        parser.print_usage()
        return 2
    except AgentError as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(str(exc))
        return 1


def build_manifest_plan(intent: AgentKubernetesIntent) -> str:
    lines: list[str] = []
    rendered = render_all(intent, commit_sha=None)
    for component in intent.components:
        if component.role != "application":
            continue
        resources = []
        prefix = f"{component.component_id}/"
        for name in ("deployment", "service", "configmap", "ingress", "pvc"):
            if f"{prefix}{name}.yaml" in rendered.files:
                resources.append(name.capitalize())
        if resources:
            lines.append(f"{component.component_id}: {', '.join(resources)}")
    lines.extend(f"deferred: {reason}" for reason in rendered.deferred)
    return "\n".join(lines) or "No manifests ready"


def _cmd_analyze(args, cfg, store: SessionStore) -> int:
    session = store.create(k8s_version=cfg.k8s_version, llm_enabled=cfg.llm_enabled)
    cache_root = cfg.home / "cache"
    if is_git_url(args.repository):
        acquired = acquire_git(
            args.repository,
            args.ref,
            cache_root=cache_root,
            token=os.environ.get(cfg.git_token_env),
        )
    else:
        acquired = acquire_local(args.repository, ref=args.ref, cache_root=cache_root)
    output_dir = acquired.repo_path / OUTPUT_DIR_NAME
    session = session.model_copy(
        update={
            "source": acquired.source,
            "repo_path": str(acquired.repo_path),
            "output_dir": str(output_dir),
        }
    )
    session = advance(session, SessionState.REPO_READY, store.clock)
    run_agent_analysis(
        acquired.repo_path,
        url=acquired.source.location,
        ref=acquired.source.ref,
        clock=store.clock,
    )
    session = advance(session, SessionState.ANALYZED, store.clock)
    store.save(session)
    print(f"session {session.session_id}")
    print(session.session_id)
    return 0


def _cmd_select(args, store: SessionStore) -> int:
    session = store.load(args.session_id)
    _require_state(session, SessionState.ANALYZED, "run analyze before select")
    bundle = _analysis_bundle(session, store)
    candidates = extract_candidates(bundle)
    selected = [candidate.component_id for candidate in candidates] if args.all else args.components.split(",")
    result = apply_selection(bundle, selected)
    topology = build_topology(bundle, result)
    intent = build_intent(topology, bundle.reconciliation.intent)
    output_dir = Path(session.output_dir)
    write_topology(topology, output_dir / "analysis")
    _write_model(output_dir / "intent" / "intent.yaml", intent)
    questions = build_questions(find_unresolved(intent), topology)
    _write_yaml(output_dir / "intent" / "questions.yaml", {"questions": [q.model_dump() for q in questions]})
    session = session.model_copy(
        update={
            "selected_components": result.selected,
            "excluded_components": result.excluded,
        }
    )
    session = advance(session, SessionState.COMPONENTS_SELECTED, store.clock)
    session = advance(session, SessionState.INTENT_DRAFTED, store.clock)
    store.save(session)
    for warning in result.warnings:
        print(warning)
    print("selected")
    return 0


def _cmd_answer(args, store: SessionStore) -> int:
    session = store.load(args.session_id)
    _require_state(session, SessionState.INTENT_DRAFTED, "run select before answer")
    intent = _load_intent(session)
    payload = yaml.safe_load(Path(args.answers_file).read_text(encoding="utf-8")) or {}
    answers = payload.get("answers", {})
    changes = [Change(op="set", path=path, value=value) for path, value in answers.items()]
    updated = apply_changeset(
        ChangeSet(origin="answers_file", changes=changes, summary="answers file"),
        intent,
        source="user_decision",
    )
    _write_model(Path(session.output_dir) / "intent" / "intent.yaml", updated)
    session = session.model_copy(update={"answers": dict(answers)})
    session = advance(session, SessionState.INTENT_RESOLVED, store.clock)
    store.save(session)
    print("answered")
    return 0


def _cmd_generate(args, store: SessionStore) -> int:
    session = store.load(args.session_id)
    if session.state not in {SessionState.INTENT_RESOLVED, SessionState.PLAN_APPROVED}:
        raise AgentError("run select and answer before generate")
    if not args.approve_plan:
        print("generation requires --approve-plan")
        return 1
    intent = _load_intent(session)
    plan = build_manifest_plan(intent)
    output_dir = Path(session.output_dir)
    (output_dir / "intent").mkdir(parents=True, exist_ok=True)
    (output_dir / "intent" / "plan.txt").write_text(plan + "\n", encoding="utf-8")
    commit_sha = session.source.commit_sha if session.source is not None else None
    write_manifests(render_all(intent, commit_sha), output_dir / "manifests")
    if session.state == SessionState.INTENT_RESOLVED:
        session = advance(session, SessionState.PLAN_APPROVED, store.clock)
    session = advance(session, SessionState.GENERATED, store.clock)
    store.save(session)
    print(plan)
    return 0


def _cmd_validate(args, cfg, store: SessionStore) -> int:
    session = store.load(args.session_id)
    _require_state(session, SessionState.GENERATED, "run generate before validate")
    intent = _load_intent(session)
    output_dir = Path(session.output_dir)
    report = run_validation(
        output_dir / "manifests",
        intent,
        k8s_version=args.k8s_version or session.k8s_version or cfg.k8s_version,
        kubeconform_path=cfg.kubeconform_path,
        project_root=Path.cwd(),
    )
    write_report(report, output_dir / "validation")
    session = advance(session, SessionState.VALIDATED, store.clock)
    store.save(session)
    print(report.aggregate)
    return {"PASS": 0, "FAIL": 3, "PARTIAL": 4}[report.aggregate]


def _cmd_sessions(args, store: SessionStore) -> int:
    if args.sessions_command == "list":
        for session in store.list_sessions():
            print(f"{session.session_id} {session.state.value}")
        return 0
    session = store.load(args.session_id)
    print(session.model_dump_json(indent=2))
    return 0


def _analysis_bundle(session: AgentSession, store: SessionStore):
    source = session.source
    return run_agent_analysis(
        Path(session.repo_path),
        url=source.location if source is not None else None,
        ref=source.ref if source is not None else None,
        clock=store.clock,
    )


def _load_intent(session: AgentSession) -> AgentKubernetesIntent:
    path = Path(session.output_dir) / "intent" / "intent.yaml"
    return AgentKubernetesIntent.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _write_model(path: Path, model) -> None:
    _write_yaml(path, model.model_dump(mode="json"))


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _require_state(session: AgentSession, expected: SessionState, message: str) -> None:
    if session.state != expected:
        raise AgentError(message)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="k8sagent")
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("repository")
    analyze.add_argument("--ref")
    analyze.add_argument("--no-llm", action="store_true")
    analyze.add_argument("--k8s-version")

    select = sub.add_parser("select")
    select.add_argument("session_id")
    group = select.add_mutually_exclusive_group(required=True)
    group.add_argument("--components")
    group.add_argument("--all", action="store_true")

    answer = sub.add_parser("answer")
    answer.add_argument("session_id")
    answer.add_argument("--answers-file", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("session_id")
    generate.add_argument("--approve-plan", action="store_true")

    validate = sub.add_parser("validate")
    validate.add_argument("session_id")
    validate.add_argument("--k8s-version")

    sessions = sub.add_parser("sessions")
    sessions_sub = sessions.add_subparsers(dest="sessions_command", required=True)
    sessions_sub.add_parser("list")
    show = sessions_sub.add_parser("show")
    show.add_argument("session_id")
    return parser
