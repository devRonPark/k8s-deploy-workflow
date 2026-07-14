# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- Create, read, list, comment on, label, and close issues with `gh issue`.
- Infer the repository from `git remote -v`.
- Use structured JSON output when skills need to filter issue state or labels.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub issues are the request and triage surface. Pull requests are not included unless this flag is changed later.

## Skill operations

- When a skill says "publish to the issue tracker", create a GitHub issue.
- When a skill says "fetch the relevant ticket", run `gh issue view <number> --comments`.
- Wayfinder maps and child tickets use GitHub issues, sub-issues where available, native dependencies where available, and `wayfinder:*` labels.
- Claim work with `gh issue edit <number> --add-assignee @me`.
