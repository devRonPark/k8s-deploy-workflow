from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.parsers.maven import ParseWarning as MavenWarning, try_parse as try_parse_maven
from preanalyzer.analyzer.parsers.nodejs import ParseWarning as NodeWarning, try_parse as try_parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import ParseWarning as PythonWarning, try_parse_pyproject


class ParserWarningTests(unittest.TestCase):
    def test_malformed_maven_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pom.xml"
            path.write_text("<project>", encoding="utf-8")
            result = try_parse_maven(path)

        self.assertIsInstance(result, MavenWarning)
        self.assertEqual(result.path, str(path))
        self.assertEqual(result.parser, "maven")

    def test_malformed_package_json_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            path.write_text("{", encoding="utf-8")
            result = try_parse_nodejs(path)

        self.assertIsInstance(result, NodeWarning)
        self.assertEqual(result.parser, "nodejs")

    def test_malformed_pyproject_returns_parse_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text("[project", encoding="utf-8")
            result = try_parse_pyproject(path)

        self.assertIsInstance(result, PythonWarning)
        self.assertEqual(result.parser, "python_pyproject")


if __name__ == "__main__":
    unittest.main()
