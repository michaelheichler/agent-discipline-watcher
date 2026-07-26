"""Trust-boundary tests for the additive PostToolBatch discipline gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import batch
import record
from lib import reporting, session_state


class BatchValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger_root = self.root / "ledger"
        self.state_root = self.root / "state"
        self.cfg = {
            "ledger_root": str(self.ledger_root),
            "state_root": str(self.state_root),
        }
        session_state.write_state("s1", {"turn_id": "turn-4"}, self.state_root)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _call(self, path: Path | str, tool_use_id: str | None) -> dict:
        call: dict[str, object] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(path)},
        }
        if tool_use_id is not None:
            call["tool_use_id"] = tool_use_id
        return call

    def _payload(self, calls: object, session_id: str = "s1") -> dict:
        return {
            "session_id": session_id,
            "cwd": str(self.root),
            "hook_event_name": "PostToolBatch",
            "tool_calls": calls,
        }

    def _rows(self) -> list[dict]:
        ledger = self.ledger_root / reporting.LEDGER_FILENAME
        if not ledger.exists():
            return []
        rows = []
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _batch_decisions(self) -> list[dict]:
        return [row for row in self._rows() if row.get("event") == "PostToolBatch"]

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

        class HostileList(list):
            def __iter__(self) -> Iterator[object]:
                nonlocal attacks
                attacks += 1
                if attacks:
                    raise AssertionError("must not iterate list subclass")
                return iter(())

        class HostileDict(dict):
            def __iter__(self) -> Iterator[object]:
                nonlocal attacks
                attacks += 1
                if attacks:
                    raise AssertionError("must not iterate dict subclass")
                return iter(())

            def get(self, *_args, **_kwargs):
                nonlocal attacks
                attacks += 1
                raise AssertionError("must not call dict subclass get")

        malformed_batches = [
            HostileList([self._call("bad.py", "tool-1")]),
            [HostileDict(self._call("bad.py", "tool-1"))],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": HostileDict({"file_path": "bad.py"}),
                }
            ],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": {"nested": HostileList([1])},
                }
            ],
        ]
        for malformed in malformed_batches:
            with self.subTest(malformed=type(malformed).__name__):
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload(malformed), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )
        self.assertEqual(attacks, 0)

    def test_hostile_top_level_metadata_never_executes_or_authorizes_ledger(self):
        attacks = 0

        class HostileStr(str):
            def _attack(self):
                nonlocal attacks
                attacks += 1
                raise AssertionError("hostile string method executed")

            __bool__ = _attack
            __hash__ = _attack

        class HostilePayload(dict):
            def _attack(self, *_args, **_kwargs):
                nonlocal attacks
                attacks += 1
                raise AssertionError("hostile mapping method executed")

            get = _attack
            __contains__ = _attack
            __getitem__ = _attack
            __iter__ = _attack

        malformed = {"not": "a call"}
        hostile_session = self._payload(malformed)
        hostile_session["session_id"] = HostileStr("s1")

        self.assertEqual(batch.run(hostile_session, self.cfg), {})
        self.assertEqual(self._rows(), [])

        hostile_cwd = self._payload(malformed)
        hostile_cwd["cwd"] = HostileStr(str(self.root))
        self.assertEqual(batch.run(hostile_cwd, self.cfg), {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

        rows_before = len(self._rows())
        hostile_payload = HostilePayload(self._payload(malformed))
        with patch.object(session_state, "read_state") as read_state:
            self.assertEqual(batch.run(hostile_payload, self.cfg), {})

        self.assertEqual(len(self._rows()), rows_before)
        read_state.assert_not_called()
        self.assertEqual(attacks, 0)

    def test_hostile_top_level_key_never_executes_or_authorizes_ledger(self):
        attacks = 0

        class HostileKey:
            def __init__(self, target: str):
                self.cached_hash = hash(target)

            def __hash__(self):
                nonlocal attacks
                attacks += 1
                return self.cached_hash

            def __eq__(self, _other):
                nonlocal attacks
                attacks += 1
                raise AssertionError("hostile key equality executed")

        payload = {
            HostileKey("session_id"): "s1",
            "tool_calls": [self._call("bad.py", "tool-1")],
        }
        attacks = 0
        rows_before = len(self._rows())

        with patch.object(session_state, "read_state") as read_state:
            self.assertEqual(batch.run(payload, self.cfg), {})

        self.assertEqual(attacks, 0)
        self.assertEqual(len(self._rows()), rows_before)
        read_state.assert_not_called()

    def test_hostile_call_key_never_executes_and_degrades_once(self):
        attacks = 0

        class HostileKey:
            def __init__(self, target: str):
                self.cached_hash = hash(target)

            def __hash__(self):
                nonlocal attacks
                attacks += 1
                return self.cached_hash

            def __eq__(self, _other):
                nonlocal attacks
                attacks += 1
                raise AssertionError("hostile key equality executed")

        call = {
            HostileKey("tool_use_id"): "tool-1",
            "tool_name": "Write",
            "tool_input": {"file_path": "bad.py"},
        }
        payload = self._payload([call])
        attacks = 0

        self.assertEqual(batch.run(payload, self.cfg), {})

        self.assertEqual(attacks, 0)
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_run_uses_one_sanitized_top_level_snapshot(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        mutant_root = self.root / "mutant"
        mutant_root.mkdir()
        original_call = self._call(bad.name, "tool-1")
        raw_calls = [original_call]
        payload = self._payload(raw_calls)
        original_effective_config = batch.effective_config

        def mutate_source(config: dict | None, cwd: str | None) -> dict:
            payload["session_id"] = "mutant"
            payload["cwd"] = str(mutant_root)
            raw_calls.clear()
            raw_calls.append(self._call(clean, "appended-tool"))
            raw_calls[0] = self._call(clean, "replacement-tool")
            return original_effective_config(config, cwd)

        with patch.object(batch, "effective_config", side_effect=mutate_source):
            response = batch.run(payload, self.cfg)

        self.assertEqual(response["decision"], "block")
        self.assertIn("deferred_work_comment", response["reason"])
        decisions = self._batch_decisions()
        self.assertTrue(decisions)
        self.assertEqual({row["session_id"] for row in decisions}, {"s1"})
        self.assertEqual({row["tool_use_id"] for row in decisions}, {"tool-1"})
        self.assertEqual({row["path"] for row in decisions}, {str(bad)})
        self.assertEqual(raw_calls[0]["tool_use_id"], "replacement-tool")

    def test_hostile_call_values_degrade_without_executing_methods_or_path_helper(self):
        attacks = 0

        def attack(*_args, **_kwargs):
            nonlocal attacks
            attacks += 1
            raise AssertionError("hostile method executed")

        hostile_type = type(
            "Hostile",
            (),
            {
                "__bool__": attack,
                "__get__": attack,
                "__getattribute__": attack,
                "__hash__": attack,
                "__iter__": attack,
                "__len__": attack,
                "__str__": attack,
            },
        )
        hostile = hostile_type()
        calls: list[dict] = [
            {"tool_use_id": hostile, "tool_name": "Write", "tool_input": {}},
            {"tool_use_id": "id", "tool_name": hostile, "tool_input": {}},
            {"tool_use_id": "id", "tool_name": "Write", "tool_input": hostile},
            {
                "tool_use_id": "id",
                "tool_name": "Write",
                "tool_input": {"file_path": "bad.py", "nested": [hostile]},
            },
            {
                "tool_use_id": "id",
                "tool_name": "Write",
                "tool_input": {"file_path": hostile},
            },
        ]
        for call in calls:
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

        malformed_batches = [
            TameList([self._call("bad.py", "tool-1")]),
            [TameDict(self._call("bad.py", "tool-1"))],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": TameDict({"file_path": "bad.py"}),
                }
            ],
            [
                {
                    "tool_use_id": "tool-1",
                    "tool_name": "Write",
                    "tool_input": {"nested": TameList([1])},
                }
            ],
        ]
        for malformed in malformed_batches:
            with self.subTest(malformed=type(malformed).__name__):
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload(malformed), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )


if __name__ == "__main__":
    unittest.main()
