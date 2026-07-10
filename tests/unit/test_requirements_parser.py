from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.parsers.python_pkg import parse_requirements


def _parse(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "requirements.txt"
        path.write_text(text, encoding="utf-8")
        return parse_requirements(path)


class RequirementsParserTests(unittest.TestCase):
    def test_plain_requirements(self):
        parsed = _parse("fastapi==0.111.0\nuvicorn\n")
        self.assertEqual(parsed.dependencies, ["fastapi", "uvicorn"])

    def test_include_and_constraint_not_treated_as_packages(self):
        parsed = _parse("-r base.txt\n--requirement dev.txt\n-c constraints.txt\nflask\n")
        self.assertEqual(parsed.dependencies, ["flask"])
        self.assertEqual(
            [(i.kind, i.path) for i in parsed.includes],
            [("requirements", "base.txt"), ("requirements", "dev.txt"), ("constraints", "constraints.txt")],
        )

    def test_index_and_option_lines_ignored(self):
        parsed = _parse(
            "--index-url https://packages.example.com/simple\n"
            "--extra-index-url https://other.example.com\n"
            "--pre\n"
            "requests\n"
        )
        self.assertEqual(parsed.dependencies, ["requests"])

    def test_editable_and_vcs_are_direct_references(self):
        parsed = _parse(
            "-e git+https://example.com/repo.git#egg=myapp\n"
            "git+https://example.com/other.git#egg=otherpkg\n"
            "celery\n"
        )
        self.assertEqual(parsed.dependencies, ["celery"])
        self.assertEqual(
            [(d.kind, d.name) for d in parsed.direct_references],
            [("editable", "myapp"), ("vcs", "otherpkg")],
        )

    def test_credentials_in_vcs_url_are_not_stored(self):
        parsed = _parse("git+https://user:secret-token@example.com/repo.git#egg=app\n")
        # Only the egg name is retained; the URL (and its token) is dropped.
        self.assertEqual([d.name for d in parsed.direct_references], ["app"])
        self.assertNotIn("secret-token", repr(parsed))

    def test_pep508_direct_url_reference(self):
        parsed = _parse("mypkg @ https://example.com/mypkg-1.0.tar.gz\n")
        self.assertEqual(parsed.dependencies, [])
        self.assertEqual([(d.kind, d.name) for d in parsed.direct_references], [("url", "mypkg")])

    def test_environment_marker_is_dropped_from_name(self):
        parsed = _parse('importlib-metadata; python_version < "3.8"\n')
        self.assertEqual(parsed.dependencies, ["importlib-metadata"])

    def test_extras_and_specifier_stripped(self):
        parsed = _parse("uvicorn[standard]>=0.20\n")
        self.assertEqual(parsed.dependencies, ["uvicorn"])

    def test_line_continuation_is_joined(self):
        parsed = _parse("flask \\\n    ==2.0\n")
        self.assertEqual(parsed.dependencies, ["flask"])

    def test_inline_comment_ignored(self):
        parsed = _parse("flask  # web framework\n")
        self.assertEqual(parsed.dependencies, ["flask"])

    def test_hash_option_ignored(self):
        parsed = _parse("flask==2.0 --hash=sha256:abcdef\n")
        # The hash option after the requirement is on the same line; the name
        # is still flask and no bogus package is produced.
        self.assertEqual(parsed.dependencies, ["flask"])


if __name__ == "__main__":
    unittest.main()
