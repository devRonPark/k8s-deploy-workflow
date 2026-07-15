from __future__ import annotations

from .assessment import KUBERNETES_LIMITATION_MESSAGE, RepositoryAssessmentView


def render_markdown(view: RepositoryAssessmentView) -> str:
    lines = [
        "# Repository Assessment",
        "",
        f"- Components: {view.components_count}",
        f"- Execution: {view.execution.value}",
        f"- Structure: {view.structure.value}",
        f"- Build: {view.build.value}",
        f"- Container: {view.container.value}",
        f"- Confirmed: {view.confirmed_count}",
        f"- Unknown: {view.unknown_count}",
        f"- Conflicts: {view.conflict_count}",
        f"- Evidence: {view.evidence_count}",
        "",
        "## Unknowns",
        *[f"- {item}" for item in view.notable_unknowns],
        "",
        "## Conflicts",
        *[f"- {item}" for item in view.notable_conflicts],
        "",
        KUBERNETES_LIMITATION_MESSAGE,
        "",
    ]
    return "\n".join(lines)
