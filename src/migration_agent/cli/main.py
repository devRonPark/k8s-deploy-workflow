from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Sequence

from migration_agent.capabilities.repository_analysis import (
    InvalidRepositoryInput,
    analyze_repository,
)
from migration_agent.presentation.assessment import build_assessment_view
from migration_agent.presentation.console_view import render_console
from migration_agent.presentation.json_view import render_json
from migration_agent.presentation.markdown_view import render_markdown


EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_ENGINE_FAILURE = 5


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "assess":
        return _assess(args)
    parser.print_help(sys.stderr)
    return EXIT_INVALID_INPUT


def _assess(args: argparse.Namespace) -> int:
    repository_path = Path(args.repository_path)
    run_root = Path(args.output) if args.output else _default_run_root(repository_path)

    try:
        result = analyze_repository(repository_path=repository_path, run_root=run_root)
    except InvalidRepositoryInput as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID_INPUT

    if result.status != "analysis_complete" or result.understanding is None:
        for warning in result.warnings:
            print(warning, file=sys.stderr)
        return EXIT_ENGINE_FAILURE

    view = build_assessment_view(result.understanding)
    json_text = render_json(view)
    markdown_text = render_markdown(view)
    (run_root / "repository-assessment.json").write_text(json_text, encoding="utf-8")
    (run_root / "repository-assessment.md").write_text(markdown_text, encoding="utf-8")

    if args.format == "json":
        print(json_text, end="")
    elif args.format == "markdown":
        print(markdown_text, end="")
    else:
        print(render_console(view), end="")

    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    assess = subparsers.add_parser("assess", help="assess a local repository for v1 beta migration readiness")
    assess.add_argument("repository_path")
    assess.add_argument("--output")
    assess.add_argument(
        "--format",
        choices=("console", "json", "markdown", "all"),
        default="all",
    )
    return parser


def _default_run_root(repository_path: Path) -> Path:
    normalized = str(repository_path.expanduser().resolve(strict=False))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return Path(".repository-agent") / "runs" / f"run-{digest}"


if __name__ == "__main__":
    raise SystemExit(main())
