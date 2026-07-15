# migration_agent

Repository Assessment Beta code lives in this package.

The package may consume deterministic `preanalyzer` scanner, parser, evidence,
and rule-inference assets only through `migration_agent.adapters`.

It must not import `k8s_agent`, call legacy orchestration, or generate
Kubernetes manifests.
