# Repository analysis evaluation data

`repository-registry.yaml` fixes the two public repositories by URL and commit.
The two internal repositories use aliases and environment-variable names so no
private repository name, URL, revision, or expert truth is committed.

To run the four-repository evaluation, materialize a local
`repository-analysis-corpus/v1` file from the two public expert-truth files and
the two private truth files, then pass the four checked-out paths to
`run_repository_scorecard`. Lock that local corpus with
`initialize_repository_corpus_lock` before looking at Agent output. Later truth
changes must use `update_repository_corpus_lock`, which requires a new version,
reason, and affected case list. Internal revisions are pinned by a SHA-256
fingerprint so the commit can be verified without publishing the private commit
ID. Corpus locks also bind the scoring rules, and contract cases bind a
deterministic hash of every fixture file.

`contract-corpus.yaml` is the non-secret regression corpus. Its case-to-fixture
mapping is:

- `node-normal` → `repos/node-express-like`
- `node-secret-absence` → `repos/no-dockerfile-node`
- `runtime-port-conflict` → `repos/port-conflict-node`
- `gradle-coverage-gap` → `repos/gradle-spring-like`
- `maven-normal` → `repos/java-spring-like`
- `python-normal` → `repos/python-fastapi-like`
- `gradle-kotlin-coverage-gap` → `repos/gradle-kotlin-like`
- `kubernetes-kustomize-coverage-gap` → `repos/kubernetes-kustomize-like`

`human-baseline.template.yaml` alternates the manual and Agent-assisted roles
between two Platform Engineers. Fill both `total_seconds` and
`hands_on_seconds` only when a run is measured; pending runs contain neither.
