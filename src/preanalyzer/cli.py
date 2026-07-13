from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from preanalyzer.pipeline import run_analysis


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preanalyzer")
    subcommands = parser.add_subparsers(dest="command")

    analyze = subcommands.add_parser("analyze")
    analyze.add_argument("repo")
    analyze.add_argument("--profile")
    analyze.add_argument("--out", default="repo-analysis-output")
    analyze.add_argument("--ref")
    analyze.add_argument("--semantic-mode", choices=["disabled", "openai_compatible"], default="disabled")
    analyze.add_argument("--no-llm", action="store_true")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command != "analyze":
        parser.print_usage()
        return 2

    semantic_mode = "disabled" if args.no_llm else args.semantic_mode
    report = run_analysis(
        repo=Path(args.repo),
        output_dir=Path(args.out),
        url=None,
        ref=args.ref,
        clock=_clock,
        semantic_mode=semantic_mode,
        profile_path=Path(args.profile) if args.profile else None,
    )
    hold_summary = ""
    if report.generation_holds:
        first_hold = report.generation_holds[0]
        path = first_hold.resource.intended_path or first_hold.resource.name or first_hold.resource.kind
        hold_summary = f" hold_status={first_hold.display_status} first_hold={path}"
    print(
        f"achieved_level={report.achieved_level} "
        f"generation_holds={len(report.generation_holds)} out={args.out}{hold_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
