import unittest

from pydantic import ValidationError

from k8sagent.changeset import (
    Change,
    ChangeSet,
    apply_changeset,
    diff_changeset,
    render_diff_text,
    validate_changeset,
)
from k8sagent.errors import ChangeSetError
from k8sagent.models.intent import AgentKubernetesIntent, ComponentIntentSpec


def make_intent() -> AgentKubernetesIntent:
    return AgentKubernetesIntent(
        components=[ComponentIntentSpec(component_id="api", role="application")]
    )


class ChangeSetTests(unittest.TestCase):
    def test_set_namespace_validate_diff_apply(self):
        intent = make_intent()
        cs = ChangeSet(
            origin="wizard",
            changes=[Change(op="set", path="namespace", value="prod")],
            summary="set namespace",
        )
        validate_changeset(cs, intent)
        diffs = diff_changeset(cs, intent)
        self.assertEqual(diffs[0].before, None)
        self.assertEqual(diffs[0].after, "prod")
        self.assertIn("namespace: None -> prod", render_diff_text(diffs))
        updated = apply_changeset(cs, intent, source="user_decision")
        self.assertEqual(updated.namespace.value, "prod")

    def test_unsupported_path_reports_path(self):
        cs = ChangeSet(origin="wizard", changes=[Change(op="set", path="bad.path", value="x")])
        with self.assertRaises(ChangeSetError) as ctx:
            validate_changeset(cs, make_intent())
        self.assertIn("bad.path", str(ctx.exception))

    def test_invalid_value_rejected(self):
        cs = ChangeSet(
            origin="wizard",
            changes=[Change(op="set", path="components.api.service.port", value=70000)],
        )
        with self.assertRaises(ChangeSetError):
            validate_changeset(cs, make_intent())

    def test_empty_and_too_many_changes_rejected(self):
        with self.assertRaises(ValidationError):
            ChangeSet(origin="wizard", changes=[])
        with self.assertRaises(ValidationError):
            ChangeSet(
                origin="wizard",
                changes=[Change(op="set", path="namespace", value=f"n{i}") for i in range(21)],
            )

    def test_unset_diff(self):
        intent = apply_changeset(
            ChangeSet(origin="wizard", changes=[Change(op="set", path="namespace", value="prod")]),
            make_intent(),
            source="user_decision",
        )
        cs = ChangeSet(origin="wizard", changes=[Change(op="unset", path="namespace")])
        diffs = diff_changeset(cs, intent)
        self.assertEqual(diffs[0].before, "prod")
        self.assertIsNone(diffs[0].after)

    def test_apply_is_pure(self):
        intent = make_intent()
        updated = apply_changeset(
            ChangeSet(origin="wizard", changes=[Change(op="set", path="namespace", value="prod")]),
            intent,
            source="user_decision",
        )
        self.assertIsNone(intent.namespace)
        self.assertEqual(updated.namespace.value, "prod")

    def test_partial_failure_rejects_all_changes(self):
        intent = make_intent()
        cs = ChangeSet(
            origin="wizard",
            changes=[
                Change(op="set", path="namespace", value="prod"),
                Change(op="set", path="components.api.service.port", value=70000),
            ],
        )
        with self.assertRaises(ChangeSetError):
            apply_changeset(cs, intent, source="user_decision")
        self.assertIsNone(intent.namespace)

    def test_set_requires_value(self):
        with self.assertRaises(ValidationError):
            ChangeSet(origin="wizard", changes=[Change(op="set", path="namespace")])


if __name__ == "__main__":
    unittest.main()
