#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python3}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

"$PYTHON_BIN" -m unittest discover -s tests/migration_agent -v

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

if command -v repository-agent >/dev/null 2>&1; then
  agent=(repository-agent)
else
  agent=("$PYTHON_BIN" -m migration_agent.cli.main)
fi

"${agent[@]}" assess tests/fixtures/migration_agent/node-docker \
  --output "$tmp_dir/node-docker"
"${agent[@]}" assess tests/fixtures/migration_agent/node-compose-conflict \
  --output "$tmp_dir/node-compose-conflict"
"${agent[@]}" assess tests/fixtures/migration_agent/node-no-dockerfile \
  --output "$tmp_dir/node-no-dockerfile"

for run in node-docker node-compose-conflict node-no-dockerfile; do
  test -f "$tmp_dir/$run/discovery.json"
  test -f "$tmp_dir/$run/repository-understanding.yaml"
  test -f "$tmp_dir/$run/repository-assessment.json"
  test -f "$tmp_dir/$run/repository-assessment.md"
done

if find "$tmp_dir" -type f \( \
  -name '*manifest*' -o \
  -name '*proposal*' -o \
  -name '*decision*' -o \
  -name '*validation*' \
\) | grep -q .; then
  echo "unexpected v2 artifact was generated" >&2
  exit 1
fi

echo "v1 beta verification passed"
