from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.models.run import RunState
from tests.acceptance.test_mvp_fixture_matrix import _prepare, _write_recommended_answers


REPRODUCIBLE_FIXTURES = [
    "node-express-like",
    "python-fastapi-like",
    "java-spring-like",
    "frontend-backend-monorepo",
    "compose-multi-service",
    "secret-candidate-node",
    "no-dockerfile-node",
    "corrupt-package-node",
]


class ManifestReproducibilityMatrixTests(unittest.TestCase):
    def test_ready_fixtures_render_byte_identical_manifest_bundles(self):
        for fixture in REPRODUCIBLE_FIXTURES:
            with self.subTest(fixture=fixture):
                first = _ready_run(fixture)
                second = _ready_run(fixture)

            self.assertEqual(first, second)


def _ready_run(fixture: str) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as tmp:
        state_home = Path(tmp) / "state"
        probe = _prepare(state_home, fixture, non_interactive=False)
        answers = Path(tmp) / "answers.yaml"
        _write_recommended_answers(probe.run_root, answers)
        outcome = _prepare(state_home, fixture, non_interactive=True, answers_file=answers)
        if outcome.state != RunState.READY:
            raise AssertionError(f"{fixture} did not reach READY: {outcome.state}")
        generated = outcome.run_root / "generated"
        return {
            path.relative_to(generated).as_posix(): path.read_bytes()
            for path in sorted(generated.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
