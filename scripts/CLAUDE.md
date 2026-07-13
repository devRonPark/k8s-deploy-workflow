# scripts

## Purpose / Owns

Repo-maintenance scripts that keep agent context trustworthy. Currently:

```text
scripts/validate_context_paths.py   # fail if a context doc references a missing path
scripts/ensure_kubeconform.py       # install/check required kubeconform binary
```

Wired into [.husky/pre-push](../.husky/pre-push) and
[context-validate.yml](../.github/workflows/context-validate.yml).

## Common Patterns

- Every script here is stdlib-only and ships a `--selfcheck`:

```bash
python3 scripts/validate_context_paths.py --selfcheck
python3 scripts/ensure_kubeconform.py --check
```

- Add a script → register it in both the pre-push hook and the CI workflow above.

## Dependencies

- Depends on nothing outside the standard library.
- Consumed by the git pre-push hook and CI; it scans `CLAUDE.md` / `AGENTS.md` /
  `README.md` across the repo.

> Note: the validator flags any `dir/file.ext` string in a context doc as a path,
> even in prose. Wrap standalone file names in separate backticks (no directory
> prefix) so a sentence is not mistaken for a broken reference.
