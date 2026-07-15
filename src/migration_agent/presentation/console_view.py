from __future__ import annotations

from .assessment import KUBERNETES_LIMITATION_MESSAGE, RepositoryAssessmentView


def render_console(view: RepositoryAssessmentView) -> str:
    lines = [
        "Repository Assessment",
        "",
        f"Components   {view.components_count}",
        f"Execution    {view.execution.value}",
        f"Structure    {view.structure.value}",
        f"Build        {view.build.value}",
        f"Container    {view.container.value}",
        "",
        f"Confirmed    {view.confirmed_count}",
        f"Unknown      {view.unknown_count}",
        f"Conflicts    {view.conflict_count}",
        f"Evidence     {view.evidence_count}",
        "",
        "Coverage",
        f"Parsed       {view.coverage.parsed_count}",
        f"Partial      {view.coverage.partial_count}",
        f"Unsupported  {view.coverage.unsupported_count}",
        f"Ignored      {view.coverage.ignored_count}",
    ]
    if view.coverage.limitations:
        lines.extend(f"- {item}" for item in view.coverage.limitations)
    if view.notable_unknowns:
        lines.extend(["", "Unknowns", *[f"- {item}" for item in view.notable_unknowns]])
    if view.notable_conflicts:
        lines.extend(["", "Conflicts", *[f"- {item}" for item in view.notable_conflicts]])
    lines.extend(["", KUBERNETES_LIMITATION_MESSAGE, ""])
    return "\n".join(lines)
