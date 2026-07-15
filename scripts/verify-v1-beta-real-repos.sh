#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python3}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

work_root="${1:-/tmp/repository-agent-v1-beta-real-repos}"
rm -rf "$work_root"
mkdir -p "$work_root/repos" "$work_root/runs"

if command -v repository-agent >/dev/null 2>&1; then
  agent=(repository-agent)
else
  agent=("$PYTHON_BIN" -m migration_agent.cli.main)
fi

probe() {
  local name="$1"
  local sha="$2"
  local role="$3"
  local repo_dir="$work_root/repos/${name//\//__}"
  local run_dir="$work_root/runs/${name//\//__}"

  git clone --filter=blob:none --no-checkout "https://github.com/${name}.git" "$repo_dir"
  git -C "$repo_dir" checkout --detach "$sha"
  "${agent[@]}" assess "$repo_dir" --output "$run_dir" >/dev/null

  test -f "$run_dir/discovery.json"
  test -f "$run_dir/repository-understanding.yaml"
  test -f "$run_dir/repository-assessment.json"
  test -f "$run_dir/repository-assessment.md"

  if find "$run_dir" -type f \( \
    -name '*manifest*' -o \
    -name '*proposal*' -o \
    -name '*decision*' -o \
    -name '*validation*' \
  \) | grep -q .; then
    echo "unexpected v2 artifact was generated for $name" >&2
    exit 1
  fi

  echo "$name $sha $role passed"
}

probe "mybatis/jpetstore-6" "5a7cc780505b88a60779b3e3c0a50b0e404cfb2d" "single-application"
probe "fastapi/full-stack-fastapi-template" "4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8" "compose-monorepo"
probe "GoogleCloudPlatform/microservices-demo" "9a4616e77f0f9cbcbecaf27d711c38890dda1404" "msa-experimental"
probe "spring-petclinic/spring-petclinic-microservices" "305a1f13e4f961001d4e6cb50a9db51dc3fc5967" "msa-experimental"
probe "dotnet/eShop" "9b4f9434f46fdc5c1a6e9e936af2868340cdbc48" "polyrepo-unsupported-scope"

echo "v1 beta real repository probes passed"
