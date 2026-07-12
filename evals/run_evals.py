#!/usr/bin/env python3
"""Agent-outcome eval harness: measure whether the deterministic preanalysis
pipeline still produces the expected artifacts for each sample repo.

Reuses the existing acceptance suite as the ground-truth signal (no new
assertions to drift). Writes a pass-rate scorecard to `agent-results.json`
so regressions in agent-facing behavior are quantified over time.

    python evals/run_evals.py           # run, update agent-results.json
    python evals/run_evals.py --selfcheck

ponytail: wraps the unittest suite instead of re-deriving expectations.
Add per-task LLM-quality scoring only once a real LLM executor lands.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "agent-results.json"
# Prefer the project venv — the suite needs pydantic/PyYAML that system python lacks.
VENV_PY = ROOT / ".venv" / "bin" / "python3"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
# Representative agent tasks, each backed by an acceptance test module.
TASKS = [
    {"id": "scan-sample-repos", "test": "tests/acceptance/test_sample_repos_scanner.py"},
    {"id": "phase1-deterministic", "test": "tests/acceptance/test_phase1_deterministic_outputs.py"},
]
RE_RAN = re.compile(r"Ran (\d+) test")


def run_task(test: str) -> tuple[bool, int]:
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [PY, "-m", "unittest", test.replace("/", ".")[:-3], "-v"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    out = proc.stderr + proc.stdout
    ran = int(m.group(1)) if (m := RE_RAN.search(out)) else 0
    return proc.returncode == 0, ran


def run() -> dict:
    results = []
    for t in TASKS:
        passed, ran = run_task(t["test"])
        results.append({"id": t["id"], "passed": passed, "tests_run": ran})
    pass_rate = sum(r["passed"] for r in results) / max(1, len(results))
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pass_rate": round(pass_rate, 3),
        "tasks": results,
    }


def selfcheck() -> None:
    scorecard = {"pass_rate": 1.0, "tasks": [{"id": "x", "passed": True}]}
    assert 0.0 <= scorecard["pass_rate"] <= 1.0
    m = RE_RAN.search("Ran 5 tests in 0.1s")
    assert m and m.group(1) == "5"
    print("selfcheck ok")


def main(argv: list[str]) -> int:
    if "--selfcheck" in argv:
        selfcheck()
        return 0
    scorecard = run()
    RESULTS.write_text(json.dumps(scorecard, indent=2) + "\n")
    print(f"pass_rate={scorecard['pass_rate']}  ({RESULTS})")
    return 0 if scorecard["pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
