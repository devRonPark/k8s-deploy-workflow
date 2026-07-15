from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.dotnet import (
    parse_appsettings,
    parse_build_metadata,
    parse_launch_settings,
    parse_project,
    parse_solution,
    try_parse_appsettings,
    try_parse_launch_settings,
)
from preanalyzer.analyzer.parsers.result import ParseWarning
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.models.inventory import ArtifactInventory


class DotnetInputTests(unittest.TestCase):
    def test_dotnet_project_solution_launch_and_appsettings_become_evidence(self) -> None:
        root = Path("tests/fixtures/migration_agent/dotnet-web-config")

        evidence = build_evidence(
            inventory=ArtifactInventory(
                build_files=[
                    {"path": "Directory.Build.props", "type": "dotnet_build_metadata"},
                    {"path": "eShop.sln", "type": "dotnet_solution"},
                    {"path": "src/Catalog.Api/Catalog.Api.csproj", "type": "dotnet_project"},
                ],
                app_configs=[
                    {"path": "src/Catalog.Api/Properties/launchSettings.json", "type": "dotnet_launch_settings"},
                    {"path": "src/Catalog.Api/appsettings.json", "type": "dotnet_appsettings"},
                ],
            ),
            parsed_artifacts={
                "Directory.Build.props": parse_build_metadata(root / "Directory.Build.props"),
                "eShop.sln": parse_solution(root / "eShop.sln"),
                "src/Catalog.Api/Catalog.Api.csproj": parse_project(
                    root / "src/Catalog.Api/Catalog.Api.csproj"
                ),
                "src/Catalog.Api/Properties/launchSettings.json": parse_launch_settings(
                    root / "src/Catalog.Api/Properties/launchSettings.json"
                ),
                "src/Catalog.Api/appsettings.json": parse_appsettings(root / "src/Catalog.Api/appsettings.json"),
            },
        )

        facts = [_without_id(fact.model_dump()) for fact in evidence.facts]

        self.assertIn(
            {
                "fact_type": "dotnet_project_metadata",
                "artifact_ref": "src/Catalog.Api/Catalog.Api.csproj",
                "source": "dotnet_project",
                "classification": "observed_fact",
                "value": {
                    "project_name": "Catalog.Api",
                    "sdk": "Microsoft.NET.Sdk.Web",
                    "assembly_name": "Catalog.Api",
                    "root_namespace": None,
                    "target_frameworks": ["net8.0"],
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "dotnet_solution_project",
                "artifact_ref": "eShop.sln",
                "source": "dotnet_solution",
                "classification": "observed_fact",
                "value": {
                    "name": "Catalog.Api",
                    "path": "src/Catalog.Api/Catalog.Api.csproj",
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "dotnet_launch_port",
                "artifact_ref": "src/Catalog.Api/Properties/launchSettings.json",
                "source": "dotnet_launch_settings",
                "classification": "observed_fact",
                "value": {
                    "profile": "Catalog.Api",
                    "port": 5000,
                    "scheme": "http",
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "dotnet_connection_string_name",
                "artifact_ref": "src/Catalog.Api/appsettings.json",
                "source": "dotnet_appsettings",
                "classification": "observed_fact",
                "value": {"name": "CatalogDb"},
            },
            facts,
        )
        serialized = "\n".join(str(fact.value) for fact in evidence.facts)
        self.assertNotIn("Password=", serialized)
        self.assertNotIn("${DB_PASSWORD}", serialized)
        self.assertNotIn("${API_TOKEN}", serialized)

        rules = infer(evidence)
        self.assertEqual([candidate.component_id for candidate in rules.component_candidates], ["Catalog.Api"])
        self.assertEqual([candidate.port for candidate in rules.runtime_port_candidates], [5000])
        self.assertEqual([candidate.language for candidate in rules.runtime_candidates], ["dotnet"])

    def test_invalid_dotnet_json_becomes_parse_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "appsettings.json"
            settings.write_text("{", encoding="utf-8")

            result = try_parse_appsettings(settings)

        self.assertIsInstance(result, ParseWarning)

    def test_invalid_launch_settings_port_becomes_parse_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "launchSettings.json"
            settings.write_text(
                '{"profiles":{"api":{"applicationUrl":"http://localhost:not-a-port"}}}',
                encoding="utf-8",
            )

            result = try_parse_launch_settings(settings)

        self.assertIsInstance(result, ParseWarning)

    def test_solution_records_all_dotnet_sdk_project_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            solution = Path(tmp) / "Mixed.sln"
            solution.write_text(
                "\n".join(
                    [
                        'Project("{GUID}") = "Api", "src/Api/Api.csproj", "{GUID}"',
                        "EndProject",
                        'Project("{GUID}") = "Worker", "src/Worker/Worker.fsproj", "{GUID}"',
                        "EndProject",
                        'Project("{GUID}") = "Legacy", "src/Legacy/Legacy.vbproj", "{GUID}"',
                        "EndProject",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_solution(solution)

        self.assertEqual(
            [(project.name, project.path) for project in parsed.projects],
            [
                ("Api", "src/Api/Api.csproj"),
                ("Legacy", "src/Legacy/Legacy.vbproj"),
                ("Worker", "src/Worker/Worker.fsproj"),
            ],
        )


def _without_id(value):
    value = dict(value)
    value.pop("evidence_id")
    return value


if __name__ == "__main__":
    unittest.main()
