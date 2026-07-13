status: DONE

files changed:
- README.md
- src/preanalyzer/pipeline.py
- tests/acceptance/test_demo_repos.py

tests run:
- RED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.acceptance.test_demo_repos.PortConflictTests tests.acceptance.test_demo_repos.DemoSpectrumTests -v` -> failed on missing hold resolution metadata.
- GREEN: same focused acceptance command -> 7 tests passed.
- `python3 scripts/ensure_kubeconform.py --check` -> passed.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.acceptance.test_demo_repos -v` -> 8 tests passed.
- Five fixture `run_analysis(...)` loop -> sandbox run had kubeconform schema download failures; escalated rerun had kubeconform pass for all 5 fixtures, with holds on `jpetstore-like` and `port-conflict-node`.
- Final bundle verification: `git status --short`, `git diff --check`, `python3 scripts/ensure_kubeconform.py --check`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest discover -s tests -v`, `python3 scripts/validate_context_paths.py .` -> full suite 376 tests passed, 1 skipped.

commits made:
- 6237796 test: cover generation holds in sample repos

self-review notes:
- Acceptance now covers generation holds and invalid port marker absence for both target fixtures.
- Pipeline enrichment is limited to renderer holds with `unresolved_service_port`; no renderer, validator, or profile merge refactor was made.
- README now briefly explains `generation_holds` and `생성 보류`.

concerns:
- The isolated worktree does not have `.venv/bin/python3`; verification used the base checkout virtualenv at `/home/daolts/k8s-deploy-workflow/.venv/bin/python3`.

---

## Review Fix: Keep Port Conflict Manifest Scan Inside TemporaryDirectory

status: DONE

files changed:
- tests/acceptance/test_demo_repos.py

review finding addressed:
- Moved the `port-conflict-node` invalid manifest marker assertion into the `TemporaryDirectory` lifetime so generated YAML files are actually scanned before cleanup.

tests run:
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest tests.acceptance.test_demo_repos.PortConflictTests -v` -> 1 test passed.
- `git status --short` -> showed the expected modified test file and untracked `.superpowers/` report directory before staging.
- `git diff --check` -> passed with no whitespace errors.
- `python3 scripts/ensure_kubeconform.py --check` -> passed, kubeconform found at `.tools/kubeconform/v0.8.0/linux-amd64/kubeconform`.
- `python3 scripts/validate_context_paths.py .` -> passed (`context paths ok`).
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/daolts/k8s-deploy-workflow/.venv/bin/python3 -m unittest discover -s tests -v` -> 376 tests passed, 1 skipped.

concerns:
- The isolated worktree still does not have `.venv/bin/python3`; focused verification used the base checkout virtualenv at `/home/daolts/k8s-deploy-workflow/.venv/bin/python3`.
