"""Trust-boundary tests because a hostile PostToolBatch payload must never execute or read past its own boundary."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import batch
import record
from lib import session_state
from testing import BatchTestCase


class HostileKey:
    """Shared because the two hostile-key tests must prove the same thing: a scan never touches a raw dict key."""

    def __init__(self, target: str, on_touch):
        self.cached_hash = hash(target)
        self._on_touch = on_touch

    def __hash__(self):
        self._on_touch()
        return self.cached_hash

    def __eq__(self, _other):
        self._on_touch()
        raise AssertionError("hostile key equality executed")


def _hostile_list_type(on_touch) -> type:
    """A factory, matching HostileKey above, because each caller needs its own attack counter wired in."""

    class HostileList(list):
        def __iter__(self):  # pylint: disable=non-iterator-returned
            on_touch()
            raise AssertionError("must not iterate list subclass")

    return HostileList


def _hostile_dict_type(on_touch) -> type:
    """A factory, matching HostileKey above, because each caller needs its own attack counter wired in."""

    class HostileDict(dict):
        def __iter__(self):  # pylint: disable=non-iterator-returned
            on_touch()
            raise AssertionError("must not iterate dict subclass")

        def get(self, *_args, **_kwargs):
            on_touch()
            raise AssertionError("must not call dict subclass get")

    return HostileDict


def _hostile_str_type(on_touch) -> type:
    """A factory, matching HostileKey above, because each caller needs its own attack counter wired in."""

    class HostileStr(str):
        def _attack(self):
            on_touch()
            raise AssertionError("hostile string method executed")

        __bool__ = _attack
        __hash__ = _attack

    return HostileStr


def _hostile_payload_type(on_touch) -> type:
    """A factory, matching HostileKey above, because each caller needs its own attack counter wired in."""

    class HostilePayload(dict):
        def _attack(self, *_args, **_kwargs):
            on_touch()
            raise AssertionError("hostile mapping method executed")

        get = _attack
        __contains__ = _attack
        __getitem__ = _attack
        __iter__ = _attack

    return HostilePayload


def _hostile_scalar_type(on_touch) -> type:
    """A factory whose instances refuse every dunder a batch scan might reach for, because the scan must never reach for any of them."""

    def attack(*_args, **_kwargs):
        on_touch()
        raise AssertionError("hostile method executed")

    return type("Hostile", (), {
        "__bool__": attack, "__get__": attack, "__getattribute__": attack,
        "__hash__": attack, "__iter__": attack, "__len__": attack, "__str__": attack,
    })


def _hostile_value_calls(hostile: object) -> list[dict]:
    """One hostile value per field, because each batch.run field must reject it without triggering any dunder."""
    return [
        {"tool_use_id": hostile, "tool_name": "Write", "tool_input": {}},
        {"tool_use_id": "id", "tool_name": hostile, "tool_input": {}},
        {"tool_use_id": "id", "tool_name": "Write", "tool_input": hostile},
        {
            "tool_use_id": "id", "tool_name": "Write",
            "tool_input": {"file_path": "bad.py", "nested": [hostile]},
        },
        {"tool_use_id": "id", "tool_name": "Write", "tool_input": {"file_path": hostile}},
    ]


class BatchValidationTests(BatchTestCase):
    def _malformed_batches(self, list_type: type, dict_type: type) -> list[object]:
        """Shared because the hostile and tame subclass tests must exercise identical batch shapes to compare their results."""
        return [
            list_type([self._call("bad.py", "tool-1")]),
            [dict_type(self._call("bad.py", "tool-1"))],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": dict_type({"file_path": "bad.py"}),
                }
            ],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": {"nested": list_type([1])},
                }
            ],
        ]

    def test_malformed_tool_inputs_write_one_degraded_marker(self):
        for malformed in ("path.py", ["path.py"], None):
            with self.subTest(tool_input=malformed):
                call = self._call(self.root / "bad.py", "tool-1")
                call["tool_input"] = malformed
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload([call]), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )

    def test_tuple_and_list_inputs_with_same_id_are_not_equated(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        tuple_call = self._call(path, "same")
        tuple_call["tool_input"] = {"file_path": str(path), "items": (1, 2)}
        list_call = self._call(path, "same")
        list_call["tool_input"] = {"file_path": str(path), "items": [1, 2]}

        response = batch.run(self._payload([tuple_call, list_call]), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_nested_invalid_json_values_write_one_degraded_marker(self):
        invalid_values = [
            {"nested": [{"opaque": object()}]},
            {"nested": [{1: "non-string key"}]},
            {"nested": [float("nan")]},
            {"nested": [float("inf")]},
        ]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                call = self._call(self.root / "bad.py", "tool-1")
                call["tool_input"] = invalid
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload([call]), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )

    def test_nested_hostile_class_property_never_executes(self):
        attacks = 0

        class Hostile(dict):
            @property
            def __class__(self):
                nonlocal attacks
                attacks += 1
                raise AssertionError("must not inspect hostile __class__ property")

            @__class__.setter
            def __class__(self, _value):
                nonlocal attacks
                attacks += 1
                raise AssertionError("must not set hostile __class__ property")

        call = self._call(self.root / "bad.py", "tool-1")
        call["tool_input"] = {"nested": [Hostile()]}

        self.assertEqual(batch.run(self._payload([call]), self.cfg), {})
        self.assertEqual(attacks, 0)
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_nested_hostile_metaclass_equality_never_executes(self):
        attacks = 0

        class HostileMeta(type):
            def __eq__(cls, _other):
                nonlocal attacks
                attacks += 1
                raise AssertionError("must not compare hostile type for equality")

        Hostile = HostileMeta("Hostile", (), {})
        call = self._call(self.root / "bad.py", "tool-1")
        call["tool_input"] = {"nested": [Hostile()]}

        self.assertEqual(batch.run(self._payload([call]), self.cfg), {})
        self.assertEqual(attacks, 0)
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_builtin_subclasses_are_rejected_without_running_overrides(self):
        attacks = 0

        def touch() -> None:
            nonlocal attacks
            attacks += 1

        hostile_list = _hostile_list_type(touch)
        hostile_dict = _hostile_dict_type(touch)
        for malformed in self._malformed_batches(hostile_list, hostile_dict):
            with self.subTest(malformed=type(malformed).__name__):
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload(malformed), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )
        self.assertEqual(attacks, 0)

    def _assert_hostile_payload_never_reaches_read_state(self, malformed: dict, on_touch) -> None:
        rows_before = len(self._rows())
        hostile_payload = _hostile_payload_type(on_touch)(self._payload(malformed))
        with patch.object(session_state, "read_state") as read_state:
            self.assertEqual(batch.run(hostile_payload, self.cfg), {})
        self.assertEqual(len(self._rows()), rows_before)
        read_state.assert_not_called()

    def test_hostile_top_level_metadata_never_executes_or_authorizes_ledger(self):
        attacks = 0

        def touch() -> None:
            nonlocal attacks
            attacks += 1

        hostile_str = _hostile_str_type(touch)
        malformed = {"not": "a call"}

        hostile_session = self._payload(malformed)
        hostile_session["session_id"] = hostile_str("s1")
        self.assertEqual(batch.run(hostile_session, self.cfg), {})
        self.assertEqual(self._rows(), [])

        hostile_cwd = self._payload(malformed)
        hostile_cwd["cwd"] = hostile_str(str(self.root))
        self.assertEqual(batch.run(hostile_cwd, self.cfg), {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

        self._assert_hostile_payload_never_reaches_read_state(malformed, touch)
        self.assertEqual(attacks, 0)

    def test_hostile_top_level_key_never_executes_or_authorizes_ledger(self):
        attacks = 0

        def touch() -> None:
            nonlocal attacks
            attacks += 1

        payload = {
            HostileKey("session_id", touch): "s1",
            "tool_calls": [self._call("bad.py", "tool-1")],
        }
        # Reset because building the dict literal above already hashed the key once to place it, and that hash is not an attack.
        attacks = 0
        rows_before = len(self._rows())

        with patch.object(session_state, "read_state") as read_state:
            self.assertEqual(batch.run(payload, self.cfg), {})

        self.assertEqual(attacks, 0)
        self.assertEqual(len(self._rows()), rows_before)
        read_state.assert_not_called()

    def test_hostile_call_key_never_executes_and_degrades_once(self):
        attacks = 0

        def touch() -> None:
            nonlocal attacks
            attacks += 1

        call = {
            HostileKey("tool_use_id", touch): "tool-1",
            "tool_name": "Write",
            "tool_input": {"file_path": "bad.py"},
        }
        payload = self._payload([call])
        # Reset because building the dict literal above already hashed the key once to place it, and that hash is not an attack.
        attacks = 0

        self.assertEqual(batch.run(payload, self.cfg), {})

        self.assertEqual(attacks, 0)
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def _assert_snapshot_matches_bad_file(self, response: dict, bad: Path) -> None:
        self.assertEqual(response.get("decision"), "block")
        advisory = response.get("reason", "")
        self.assertIsInstance(advisory, str)
        self.assertTrue(advisory.strip())
        self.assertIn("deferred_work_comment", advisory)
        decisions = self._batch_decisions()
        self.assertTrue(decisions)
        self.assertEqual({row["session_id"] for row in decisions}, {"s1"})
        self.assertEqual({row["tool_use_id"] for row in decisions}, {"tool-1"})
        self.assertEqual({row["path"] for row in decisions}, {str(bad)})

    def test_run_uses_one_sanitized_top_level_snapshot(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        mutant_root = self.root / "mutant"
        mutant_root.mkdir()
        raw_calls = [self._call(bad.name, "tool-1")]
        payload = self._payload(raw_calls)
        original_normalized_calls = batch._normalized_calls

        def mutate_source(inner_payload: dict) -> tuple[list, bool]:
            payload["session_id"] = "mutant"
            payload["cwd"] = str(mutant_root)
            raw_calls.clear()
            raw_calls.append(self._call(clean, "appended-tool"))
            raw_calls[0] = self._call(clean, "replacement-tool")
            return original_normalized_calls(inner_payload)

        with patch.object(batch, "_normalized_calls", side_effect=mutate_source):
            response = batch.run(payload, self.cfg)

        self._assert_snapshot_matches_bad_file(response, bad)
        self.assertEqual(raw_calls[0]["tool_use_id"], "replacement-tool")

    def test_hostile_call_values_degrade_without_executing_methods_or_path_helper(self):
        attacks = 0

        def touch() -> None:
            nonlocal attacks
            attacks += 1

        hostile = _hostile_scalar_type(touch)()
        for call in _hostile_value_calls(hostile):
            with self.subTest(
                field_types=tuple(type(value).__name__ for value in call.values())
            ):
                before = len(self._batch_decisions())
                with patch.object(record, "edited_paths") as edited_paths:
                    self.assertEqual(batch.run(self._payload([call]), self.cfg), {})
                edited_paths.assert_not_called()
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )
        self.assertEqual(attacks, 0)

    def test_tame_container_subclasses_degrade_once(self):
        class TameList(list):
            pass

        class TameDict(dict):
            pass

        for malformed in self._malformed_batches(TameList, TameDict):
            with self.subTest(malformed=type(malformed).__name__):
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload(malformed), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )


if __name__ == "__main__":
    unittest.main()
