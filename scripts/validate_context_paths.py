#!/usr/bin/env python3
"""Validate that every file path referenced in agent context docs actually exists.

Scans CLAUDE.md / AGENTS.md / README.md (repo-wide) for `dir/file.ext` style
references and fails if any point at a missing file. Stale references are worse
than missing ones — an agent that follows a hallucinated path wastes a whole turn.

Used by both `.husky/pre-push` and `.github/workflows/context-validate.yml`.

    python scripts/validate_context_paths.py            # validate, exit 1 on break
    python scripts/validate_context_paths.py --selfcheck # run built-in assert demo

ponytail: one regex + os.walk, no deps. Upgrade to a real markdown parser only if
prose false-positives become noisy.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CONTEXT_NAMES = {"CLAUDE.md", "AGENTS.md", "README.md"}
IGNORE = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
# A slash/dot-prefixed path ending in a known ext. Trailing (?![A-Za-z0-9]) stops
# `.js` matching inside `.json`; `\.{1,2}/` supports `./` and `../` relative links.
RE_PATH = re.compile(
    r"(?<![A-Za-z0-9_/])"
    r"((?:\.{1,2}/|[A-Za-z0-9_]+/)[A-Za-z0-9_./-]+"
    r"\.(?:py|ts|tsx|js|jsx|md|sql|json|yaml|yml|toml|html|css|sh|go|rs|java|kt|rb|php)(?![A-Za-z0-9]))"
)


def context_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for r, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith(".")]
        for f in files:
            if f in CONTEXT_NAMES:
                out.append(Path(r) / f)
    return out


def broken_refs(repo: Path) -> list[tuple[Path, str]]:
    bad: list[tuple[Path, str]] = []
    for p in context_files(repo):
        text = p.read_text(errors="ignore")
        for ref in sorted(set(RE_PATH.findall(text))):
            if not ((repo / ref).exists() or (p.parent / ref).exists()):
                bad.append((p, ref))
    return bad


def selfcheck() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "real.py").write_text("x = 1\n")
        (repo / "data.json").write_text("{}\n")
        sub = repo / "docs"
        sub.mkdir()
        (sub / "README.md").write_text(
            "see `src/real.py`\n"       # repo has real.py at root, not src/ -> broken
            "and `data.json` here\n"    # .json must not be truncated to .js
            "and [up](../data.json)\n"  # ../ relative link must resolve
        )
        bad = broken_refs(repo)
        refs = {r for _, r in bad}
        assert "src/real.py" in refs, f"expected src/real.py flagged, got {refs}"
        assert not any(r.endswith(".js") for r in refs), f".json truncated to .js: {refs}"
        assert not any("data.json" in r for r in refs), f"existing json flagged: {refs}"
    print("selfcheck ok")


def main(argv: list[str]) -> int:
    if "--selfcheck" in argv:
        selfcheck()
        return 0
    repo = Path(argv[1]) if len(argv) > 1 else Path(".")
    bad = broken_refs(repo.resolve())
    if bad:
        print("Broken context path references:", file=sys.stderr)
        for p, ref in bad:
            print(f"  {p}: {ref}", file=sys.stderr)
        return 1
    print("context paths ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
