from __future__ import annotations

import unittest
from pathlib import Path


class V1BetaDocumentationTests(unittest.TestCase):
    def test_release_note_describes_beta_scope_usage_outputs_and_limits(self) -> None:
        text = Path("docs/releases/v1.0.0-beta.1.md").read_text(encoding="utf-8")

        for expected in (
            "Repository Assessment Beta",
            "repository-agent assess",
            "discovery.json",
            "repository-understanding.yaml",
            "repository-assessment.json",
            "repository-assessment.md",
            "Kubernetes manifests are not generated in v1.",
            "Data safety",
            "Known limitations",
        ):
            self.assertIn(expected, text)
        for expected in (
            "Maven and Gradle project metadata",
            "Spring application configuration",
            ".NET project, launch settings, and appsettings metadata",
            "Existing Kubernetes manifests and Helm chart metadata as read-only evidence",
        ):
            self.assertIn(expected, text)

    def test_feedback_template_contains_beta_questions(self) -> None:
        text = Path("docs/feedback/v1-beta-feedback-template.md").read_text(encoding="utf-8")

        for expected in (
            "Did the report correctly explain how the app is built and run?",
            "Which confirmed finding was wrong?",
            "Which important finding was missing?",
            "Were Unknown and Conflict understandable?",
            "Was any internal detail unnecessary?",
            "Would you trust this report before Kubernetes migration?",
            "Which repository type should be tested next?",
        ):
            self.assertIn(expected, text)

    def test_example_readme_and_main_readme_label_beta_not_complete_migration(self) -> None:
        example = Path("examples/v1-beta/README.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("repository-agent assess", example)
        self.assertIn("Repository Assessment Beta", readme)
        self.assertIn("not a complete migration agent", readme)


if __name__ == "__main__":
    unittest.main()
