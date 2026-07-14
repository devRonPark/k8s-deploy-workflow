# Domain Docs

## Before exploring

- Read the root `CONTEXT.md`.
- Read relevant ADRs under `docs/decisions/`.
- If either is absent, proceed without creating it preemptively.

## Layout

This is a single-context repository:

```text
/
|-- CONTEXT.md
|-- docs/
|   `-- decisions/
`-- src/
```

## Consumer rules

- Use the glossary vocabulary from `CONTEXT.md`.
- Treat missing terminology as a domain-modeling signal.
- Surface conflicts with an existing ADR instead of silently overriding it.
- Create glossary terms and ADRs lazily through the domain-modeling workflow.
