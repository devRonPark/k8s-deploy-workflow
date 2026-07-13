#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preanalyzer.validator.kubeconform_tool import (  # noqa: E402
    KubeconformToolError,
    install_kubeconform,
    preflight_kubeconform,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and verify the pinned kubeconform binary.")
    parser.add_argument("--check", action="store_true", help="install if needed and verify the executable")
    parser.add_argument("--force", action="store_true", help="re-download and replace an existing managed binary")
    args = parser.parse_args(argv)

    try:
        path = (
            preflight_kubeconform(REPO_ROOT, force=args.force)
            if args.check
            else install_kubeconform(REPO_ROOT, force=args.force)
        )
    except KubeconformToolError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
