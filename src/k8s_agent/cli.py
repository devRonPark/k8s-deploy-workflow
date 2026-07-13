from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from k8s_agent.errors import AgentError, format_agent_error


TARGETS = {"development", "staging", "production"}


@dataclass(frozen=True)
class PrepareRequest:
    repo_url: str | None
    local_path: Path | None
    ref: str | None
    target: str
    non_interactive: bool
    answers_file: Path | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="k8s-agent")
    parser.add_argument("--debug", action="store_true", dest="global_debug")
    subcommands = parser.add_subparsers(dest="command")

    prepare = subcommands.add_parser("prepare")
    _add_source_arguments(prepare)
    prepare.add_argument("--target", required=True)
    prepare.add_argument("--non-interactive", action="store_true")
    prepare.add_argument("--answers-file")
    prepare.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    resume = subcommands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    status = subcommands.add_parser("status")
    status.add_argument("run_id")
    status.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    explain = subcommands.add_parser("explain")
    explain.add_argument("run_id")
    explain.add_argument("subject", nargs="?")
    explain.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    export = subcommands.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("--output", required=True)
    export.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    analyze = subcommands.add_parser("analyze")
    _add_source_arguments(analyze)
    analyze.add_argument("--target", required=True)
    analyze.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    plan = subcommands.add_parser("plan")
    plan.add_argument("run_id")
    plan.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    generate = subcommands.add_parser("generate")
    generate.add_argument("run_id")
    generate.add_argument("--profile-revision", type=int)
    generate.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    validate = subcommands.add_parser("validate")
    validate.add_argument("run_id")
    validate.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    return parser


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-url")
    parser.add_argument("--local-path")
    parser.add_argument("--ref")


def _validate_prepare(args: argparse.Namespace) -> PrepareRequest:
    repo_url = args.repo_url
    local_path = Path(args.local_path) if args.local_path else None
    has_repo_url = bool(repo_url)
    has_local_path = local_path is not None
    example = "k8s-agent prepare --local-path ./app --target development"

    if has_repo_url == has_local_path:
        if has_repo_url:
            raise AgentError(
                code="CLI-102",
                exit_code=2,
                message="prepare accepts exactly one source, but both --repo-url and --local-path were provided.",
                resolution="Choose one source option. Example: k8s-agent prepare --repo-url https://github.com/org/app.git --target staging",
                context={"command": "prepare"},
            )
        raise AgentError(
            code="CLI-101",
            exit_code=2,
            message="prepare requires an explicit source.",
            resolution="Pass either --repo-url or --local-path. Example: " + example,
            context={"command": "prepare"},
        )

    if local_path is not None and args.ref:
        raise AgentError(
            code="CLI-103",
            exit_code=2,
            message="--ref can only be used with --repo-url.",
            resolution="Remove --ref for local sources. Example: " + example,
            context={"command": "prepare"},
        )

    if args.target not in TARGETS:
        raise AgentError(
            code="CLI-104",
            exit_code=2,
            message=f"unsupported target '{args.target}'.",
            resolution="Use one of development, staging, or production. Example: " + example,
            context={"command": "prepare", "target": args.target},
        )

    answers_file = Path(args.answers_file) if args.answers_file else None
    if args.non_interactive and answers_file is None:
        raise AgentError(
            code="CLI-105",
            exit_code=2,
            message="--non-interactive requires --answers-file.",
            resolution="Provide explicit answers or run interactively. Example: k8s-agent prepare --local-path ./app --target development --non-interactive --answers-file answers.yaml",
            context={"command": "prepare"},
        )

    return PrepareRequest(
        repo_url=repo_url,
        local_path=local_path,
        ref=args.ref,
        target=args.target,
        non_interactive=bool(args.non_interactive),
        answers_file=answers_file,
    )


def _run_prepare(args: argparse.Namespace) -> int:
    request = _validate_prepare(args)
    from k8s_agent.application import AgentApplication

    outcome = AgentApplication().prepare(request)
    print(
        f"prepare created run_id={outcome.run_id} "
        f"target={outcome.target} source={outcome.source_kind} run_root={outcome.run_root}"
    )
    return 0


def _run_skeleton(command: str) -> int:
    print(f"{command} accepted")
    return 0


def _main_impl(argv: Sequence[str] | None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command is None:
        raise AgentError(
            code="CLI-100",
            exit_code=2,
            message="a command is required.",
            resolution="Run k8s-agent prepare --local-path ./app --target development.",
            context={"command": "missing"},
        )

    if args.command == "prepare":
        return _run_prepare(args)
    return _run_skeleton(args.command)


def main(argv: list[str] | None = None) -> int:
    debug = "--debug" in argv if argv is not None else "--debug" in sys.argv[1:]
    try:
        return _main_impl(argv)
    except AgentError as exc:
        if debug:
            traceback.print_exc()
        print(format_agent_error(exc), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        error = AgentError(
            code="CLI-999",
            exit_code=8,
            message="unexpected internal error.",
            resolution="Retry with --debug and report the command output.",
            context={"error_type": type(exc).__name__},
        )
        if debug:
            traceback.print_exc()
        print(format_agent_error(error), file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
