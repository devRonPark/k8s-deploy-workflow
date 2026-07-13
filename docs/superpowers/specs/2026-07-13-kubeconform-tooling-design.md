# Kubeconform Tooling Design

## Goal

Make Kubernetes schema validation reproducible for generated manifests by adding a project-managed `kubeconform` binary setup path and wiring the validator to use it before falling back to the host `PATH`.

The user-facing outcome is that sample repository pipeline runs can produce an actual `kubeconform: pass` or `kubeconform: fail` result instead of silently stopping at `skipped: tool_not_found` on machines that have not installed the tool globally.

## Scope

In scope:

- Add a project script that installs a pinned `kubeconform` release under `.tools/`.
- Support these platform targets:
  - Linux `x86_64` / `amd64`
  - Linux `aarch64` / `arm64`
  - Windows `x86_64` / `amd64`
- Verify downloaded archives with pinned SHA256 checksums before installing.
- Keep tool installation explicit: users, CI, or validation scripts run the setup script before analysis.
- Update `ValidationPipeline` so it resolves `kubeconform` in this order:
  1. an explicit constructor argument;
  2. the project-managed `.tools` binary for the current platform;
  3. `PATH`.
- Preserve the existing honest fallback: if no binary is available, record `kubeconform: skipped` with `tool_not_found`.
- Add focused tests for platform mapping, resolver precedence, subprocess arguments, checksum failure behavior, and missing-tool behavior.
- Update documentation so sample-repo validation includes the setup step before running the pipeline.
- Ensure `.tools/` is ignored by git.

Out of scope:

- Downloading `kubeconform` automatically from inside `ValidationPipeline.run(...)`.
- Installing or managing `kubectl`.
- Running server-side dry-run, policy engines, deployment checks, or smoke tests.
- Supporting macOS in this iteration.
- Changing manifest generation semantics to satisfy kubeconform findings.
- Marking skipped validation as pass.

## Current State

`ValidationPipeline` already runs three validation stages:

1. YAML syntax parsing.
2. `kubeconform -strict -summary -kubernetes-version <version> <manifest_dir>`.
3. `kubectl apply --dry-run=client -f <manifest_dir>` when kubeconform passes.

The current implementation looks up `kubeconform` with `shutil.which("kubeconform")`. If the binary is not installed globally, the pipeline records:

```text
kubeconform: skipped (tool_not_found)
dry_run: skipped (prior stage not pass)
achieved_level: 0
```

This is correct and honest, but it makes local and sample-repo validation environment-dependent.

## Design

### Managed Tool Layout

Install managed binaries under:

```text
.tools/kubeconform/<version>/linux-amd64/kubeconform
.tools/kubeconform/<version>/linux-arm64/kubeconform
.tools/kubeconform/<version>/windows-amd64/kubeconform.exe
```

The version is a single pinned constant, not a floating `latest` lookup. During implementation, inspect the upstream release once, choose one release version, and commit that exact version plus all supported artifact SHA256 checksums. Future upgrades happen by changing those constants in reviewable code.

The setup script and validator share the version, platform mapping, and managed-path construction through a small helper module so install and lookup behavior cannot drift.

`.tools/` remains local generated state and must not be committed.

### Platform Mapping

Create a small platform resolver with deterministic mappings:

| `platform.system()` | `platform.machine()` values | target |
|---|---|---|
| `Linux` | `x86_64`, `amd64` | `linux-amd64` |
| `Linux` | `aarch64`, `arm64` | `linux-arm64` |
| `Windows` | `AMD64`, `x86_64`, `amd64` | `windows-amd64` |

Unsupported operating systems or CPU architectures fail with a short explicit error such as:

```text
unsupported kubeconform platform: <system>/<machine>
```

The setup script fails for unsupported platforms. The validator does not fail only because the managed platform is unsupported; it still checks `PATH` so users with a manually installed compatible binary can continue.

### Setup Script

Add `scripts/ensure_kubeconform.py`.

Responsibilities:

- detect the current platform target;
- choose the pinned release archive URL for that target;
- download the archive to a temporary file under `.tools/.downloads/`;
- verify the archive SHA256 against a pinned checksum;
- extract only the expected `kubeconform` executable;
- write it atomically into the target install directory;
- set executable permissions on POSIX platforms;
- print the installed executable path.

The script must not use shell pipelines, curl, tar, or PowerShell. It should use Python standard library modules such as `urllib.request`, `hashlib`, `tarfile`, `zipfile`, `tempfile`, `os`, and `pathlib`.

If the target binary already exists and matches the expected install path, the script exits successfully and prints the existing path. It does not re-download unless a `--force` flag is provided.

### Validator Resolution

Add a small resolver function, either in `src/preanalyzer/validator/pipeline.py` or a focused helper module:

```python
resolve_kubeconform(explicit_path: Path | None = None) -> Path | str | None
```

Resolution order:

1. explicit path, if supplied and executable;
2. managed `.tools` path for the current platform, if executable;
3. `shutil.which("kubeconform")`;
4. `None`.

`ValidationPipeline.__init__` accepts:

```python
def __init__(self, k8s_version: str = "1.29", kubeconform_path: Path | None = None) -> None:
    ...
```

`_kubeconform(...)` uses the resolved executable path instead of the hard-coded string `kubeconform`.

The subprocess command remains:

```text
<resolved-kubeconform> -strict -summary -kubernetes-version <k8s_version> <manifest_dir>
```

### Error Handling

Setup script errors:

- network failure: fail the setup script with a clear download error;
- checksum mismatch: delete the downloaded file and fail;
- archive missing expected executable: fail;
- unsupported setup platform: fail.

Validator errors:

- missing tool: record `skipped: tool_not_found`;
- kubeconform non-zero exit: record `fail` and include bounded stdout/stderr detail;
- YAML syntax failure: keep existing fail-fast behavior and skip kubeconform;
- skipped kubeconform: keep achieved level at 0.

The validator must never download during analysis and must never report an unexecuted kubeconform stage as pass.

### Data Flow

Developer or CI flow:

```text
python3 scripts/ensure_kubeconform.py
preanalyzer analyze <repo> --profile <profile> --out <out>
13-validation-report.yaml records kubeconform pass/fail/skipped
```

Sample repository validation flow:

```text
model smoke test
ensure kubeconform
run 5 sample repositories through run_analysis(...)
summarize 00-15 outputs, including 13-validation-report.yaml
```

### Tests

Use `unittest`; do not require a real network download in the default test suite.

Focused tests:

- platform resolver maps Linux amd64, Linux arm64, and Windows amd64 correctly;
- unsupported platform raises an explicit setup error;
- managed path construction produces the expected `.tools/kubeconform/<version>/<target>/...` path;
- checksum mismatch fails and does not install a binary;
- `ValidationPipeline(kubeconform_path=...)` uses the explicit executable path;
- managed path is preferred over `PATH`;
- missing managed path and missing `PATH` preserves `kubeconform: skipped`;
- subprocess command includes `-strict`, `-summary`, and the configured Kubernetes version.

Network-backed installation can be tested manually or in a dedicated integration job, but it is not required for the default unit suite.

## Success Criteria

- A supported Linux amd64, Linux arm64, or Windows amd64 machine can run one project script to install the pinned `kubeconform` binary under `.tools/`.
- The setup script verifies the downloaded artifact checksum before installing.
- `ValidationPipeline` uses the managed binary automatically when it exists.
- Existing behavior remains honest when the tool is absent: skipped, not pass.
- Sample repository pipeline runs can produce real kubeconform pass/fail results after the setup script is run.
- The implementation is covered by deterministic unit tests that do not require external network access.

## Verification

Implementation must follow test-first order:

1. Write a focused failing test for the next behavior.
2. Run the targeted test and confirm the expected failure.
3. Implement the smallest code needed.
4. Run the targeted test.
5. Repeat for resolver, setup script, and validator integration.
6. Run the full suite.

Required final verification:

```bash
git status --short
git diff --check
git diff --stat
python3 scripts/validate_context_paths.py .
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```
