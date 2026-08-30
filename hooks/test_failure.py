"""Tests for failure streaks and the session-scoped MCP circuit breaker, because a repeated failure must interrupt the agent before it burns the same retry again."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest import mock

import failure
import pre_mcp
import record
from lib import reporting, session_state
from testing import CollidingKey, HostileDict, HostileString


class HostileNumber:
    calls = 0

    def __float__(self) -> float:
        type(self).calls += 1
        return 1.0

    def __bool__(self) -> bool:
        type(self).calls += 1
        return True


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = {
            "state_root": str(self.root / "state"),
            "ledger_root": str(self.root / "ledger"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def payload(self, **overrides: object) -> dict:
        values = {
            "tool": "Write",
            "target": "/work/a.py",
            "error": "permission denied",
            "session": "s1",
            "interrupt": False,
            "duration": 12,
        }
        values.update(overrides)
        return {
            "session_id": values["session"],
            "hook_event_name": "PostToolUseFailure",
            "tool_name": values["tool"],
            "tool_use_id": "call-1",
            "tool_input": {"file_path": values["target"]},
            "error": values["error"],
            "is_interrupt": values["interrupt"],
            "duration_ms": values["duration"],
        }

    def state(self, session: str = "s1") -> dict:
        return session_state.read_state(session, self.cfg["state_root"])

    def rows(self) -> list[dict]:
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.cfg["ledger_root"])

    def succeed(self, **overrides: object) -> dict:
        record_gate = bool(overrides.pop("record_gate", False))
        payload = self.payload(**overrides)
        payload.pop("error")
        payload["hook_event_name"] = "PostToolUse"
        if record_gate:
            return record.run(payload, self.cfg)
        failure.record_success(payload, self.cfg)
        return {}


class FailureHookTests(HookTestCase):
    def test_records_per_tool_and_target_metadata(self):
        self.assertEqual(failure.run(self.payload(), self.cfg, now=100.0), {})
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        expected = {
            "count": 1,
            "error": "permission denied",
            "is_interrupt": False,
            "duration_ms": 12,
        }
        self.assertEqual(streaks["tools"]["Write"], expected)
        self.assertEqual(streaks["targets"]["/work/a.py"], expected)

    def test_tool_target_and_session_streaks_are_independent(self):
        failure.run(self.payload(tool="Write", target="a"), self.cfg, now=1.0)
        failure.run(self.payload(tool="Read", target="b"), self.cfg, now=2.0)
        failure.run(self.payload(tool="Write", target="a"), self.cfg, now=3.0)
        failure.run(
            self.payload(tool="Write", target="a", session="s2"), self.cfg, now=4.0
        )
        first = self.state()
        second = self.state("s2")
        self.assertEqual(
            first[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]["count"], 2
        )
        self.assertEqual(
            first[failure.FAILURE_STREAKS_KEY]["tools"]["Read"]["count"], 1
        )
        self.assertEqual(first[failure.FAILURE_STREAKS_KEY]["targets"]["a"]["count"], 2)
        self.assertEqual(first[failure.FAILURE_STREAKS_KEY]["targets"]["b"]["count"], 1)
        self.assertEqual(
            second[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]["count"], 1
        )

    def test_changed_error_restarts_matching_streaks(self):
        failure.run(self.payload(error="first"), self.cfg, now=1.0)
        failure.run(self.payload(error="first"), self.cfg, now=2.0)
        failure.run(self.payload(error="second"), self.cfg, now=3.0)
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        self.assertEqual(streaks["tools"]["Write"]["count"], 1)
        self.assertEqual(streaks["targets"]["/work/a.py"]["count"], 1)
        self.assertEqual(streaks["tools"]["Write"]["error"], "second")

    def test_interrupts_are_recorded_but_do_not_inject_or_open_mcp(self):
        payload = self.payload(tool="mcp__github__search", interrupt=True)
        for when in (1.0, 2.0, 3.0):
            self.assertEqual(failure.run(payload, self.cfg, now=when), {})
        state = self.state()
        self.assertEqual(
            state[failure.FAILURE_STREAKS_KEY]["tools"]["mcp__github__search"]["count"],
            3,
        )
        self.assertTrue(
            state[failure.FAILURE_STREAKS_KEY]["tools"]["mcp__github__search"][
                "is_interrupt"
            ]
        )
        self.assertNotIn(failure.MCP_HEALTH_KEY, state)

    def test_missing_or_malformed_metadata_is_safe(self):
        payload = self.payload(
            target={"secret": "value"}, error=7, interrupt="false", duration=True
        )
        failure.run(payload, self.cfg, now=1.0)
        self.assertEqual(self.state(), {})
        sessionless = self.payload()
        sessionless.pop("session_id")
        self.assertEqual(failure.run(sessionless, self.cfg, now=2.0), {})

    def test_error_is_normalized_before_streak_and_empty_check(self):
        payload = self.payload(error=" \t permission\n   denied \r")
        failure.run(payload, self.cfg, now=1.0)
        streak = self.state()[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]
        self.assertEqual(streak["error"], "permission denied")

        whitespace = self.payload(error=" \t\n", session="blank")
        for when in (1.0, 2.0, 3.0):
            self.assertEqual(failure.run(whitespace, self.cfg, now=when), {})
        self.assertEqual(self.state("blank"), {})
        blank_rows = [row for row in self.rows() if row.get("session_id") == "blank"]
        self.assertTrue(all(row["event"] == "observed" for row in blank_rows))

    def test_repeated_signature_refreshes_duration(self):
        failure.run(self.payload(duration=12), self.cfg, now=1.0)
        failure.run(self.payload(duration=99), self.cfg, now=2.0)
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        self.assertEqual(streaks["tools"]["Write"]["count"], 2)
        self.assertEqual(streaks["tools"]["Write"]["duration_ms"], 99)
        self.assertEqual(streaks["targets"]["/work/a.py"]["duration_ms"], 99)

    def test_invalid_durations_are_recorded_as_canonical_zero(self):
        invalid = (
            float("nan"),
            float("inf"),
            -1,
            True,
            10**100,
            1.9,
            -0.0,
            "12",
            HostileNumber(),
        )
        HostileNumber.calls = 0
        for index, duration in enumerate(invalid):
            session = f"duration-{index}"
            failure.run(
                self.payload(session=session, duration=duration), self.cfg, now=1.0
            )
            streak = self.state(session)[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]
            self.assertEqual(streak["duration_ms"], 0)
            self.assertIs(type(streak["duration_ms"]), int)
        self.assertEqual(HostileNumber.calls, 0)

    def test_duration_contract_accepts_only_nonnegative_exact_integers(self):
        failure.run(self.payload(duration=12), self.cfg, now=1.0)
        streak = self.state()[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]
        self.assertEqual(streak["duration_ms"], 12)
        self.assertIs(type(streak["duration_ms"]), int)

    def test_invalid_now_never_writes_state(self):
        invalid = (
            float("nan"),
            float("inf"),
            -1,
            True,
            "1",
            10**100,
            HostileNumber(),
        )
        HostileNumber.calls = 0
        for index, now in enumerate(invalid):
            session = f"clock-{index}"
            self.assertEqual(
                failure.run(
                    self.payload(session=session), self.cfg, now=cast(float, now)
                ),
                {},
            )
            self.assertEqual(self.state(session), {})
        self.assertEqual(HostileNumber.calls, 0)

    def test_concurrent_failures_are_atomic_and_inject_once(self):
        payload = self.payload()
        with ThreadPoolExecutor(max_workers=12) as executor:
            responses = list(
                executor.map(
                    lambda when: failure.run(payload, self.cfg, now=float(when)),
                    range(1, 25),
                )
            )
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        self.assertEqual(streaks["tools"]["Write"]["count"], 24)
        self.assertEqual(streaks["targets"]["/work/a.py"]["count"], 24)
        self.assertEqual(sum("systemMessage" in response for response in responses), 1)

    def test_sequential_and_concurrent_failures_preserve_unknown_streak_members(self):
        metadata = {"owner": "keep", "nested": {"version": 7}}
        session_state.write_state(
            "s1",
            {
                failure.FAILURE_STREAKS_KEY: {
                    "metadata": metadata,
                    "tools": {"Other": {"custom": "value"}},
                    "targets": {"elsewhere": {"custom": "target"}},
                }
            },
            self.cfg["state_root"],
        )
        failure.run(self.payload(), self.cfg, now=1.0)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda when: failure.run(self.payload(), self.cfg, now=float(when)),
                    range(2, 17),
                )
            )
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        self.assertEqual(streaks["metadata"], metadata)
        self.assertEqual(streaks["tools"]["Other"], {"custom": "value"})
        self.assertEqual(streaks["targets"]["elsewhere"], {"custom": "target"})

    def test_boundary_rejects_subclasses_and_hostile_keys_without_protocol_calls(self):
        hostile_key = CollidingKey()
        payload: dict[object, object] = {hostile_key: "hidden"}
        payload.update(self.payload())
        CollidingKey.calls = 0
        HostileString.calls = 0
        payload["cwd"] = HostileString("/work")
        payload["error"] = HostileString("secret")
        payload["tool_input"] = HostileDict(file_path="/work/hidden")
        self.assertEqual(failure.run(payload, self.cfg, now=1.0), {})
        self.assertEqual(CollidingKey.calls, 0)
        self.assertEqual(HostileString.calls, 0)
        self.assertEqual(HostileDict.calls, 0)

        HostileDict.calls = 0
        self.assertEqual(failure.run({}, HostileDict(self.cfg), now=1.0), {})
        self.assertEqual(HostileDict.calls, 0)
        self.assertEqual(self.state(), {})

        HostileDict.calls = 0
        self.assertEqual(
            failure.run(HostileDict(self.payload()), self.cfg, now=1.0), {}
        )
        self.assertEqual(HostileDict.calls, 0)

    def test_invalid_cwd_is_empty_before_effective_config(self):
        invalid = (
            "/work\x00escape",
            "/work\nother",
            "x" * 4097,
            HostileString("/work"),
        )
        for cwd in invalid:
            payload = self.payload(session="safe-cwd")
            payload["cwd"] = cwd
            with mock.patch.object(
                failure, "effective_config", wraps=failure.effective_config
            ) as effective:
                failure.run(payload, self.cfg, now=1.0)
            self.assertIsNone(effective.call_args.args[1])

    def test_oversized_tool_is_not_a_state_key(self):
        failure.run(self.payload(tool="x" * 264), self.cfg, now=1.0)
        streaks = self.state()[failure.FAILURE_STREAKS_KEY]
        self.assertEqual(streaks["tools"], {})
        self.assertEqual(streaks["targets"]["/work/a.py"]["count"], 1)

    def test_exact_threshold_injects_once_and_names_repeat(self):
        payload = self.payload()
        self.assertEqual(failure.run(payload, self.cfg, now=1.0), {})
        self.assertEqual(failure.run(payload, self.cfg, now=2.0), {})
        response = failure.run(payload, self.cfg, now=3.0)
        self.assertEqual(
            response,
            {
                "systemMessage": (
                    "Tool failure repeated 3 times for Write on /work/a.py: "
                    "permission denied. Stop retrying or weakening the change. "
                    "Fix the root cause before calling the tool again."
                )
            },
        )
        self.assertEqual(failure.run(payload, self.cfg, now=4.0), {})

    def test_guidance_names_only_dimensions_at_threshold(self):
        for index, target in enumerate(("a", "b", "c"), start=1):
            response = failure.run(
                self.payload(tool="Write", target=target, session="tool-only"),
                self.cfg,
                now=float(index),
            )
        self.assertIn("for Write:", response["systemMessage"])
        self.assertNotIn(" on c", response["systemMessage"])

        for index, tool in enumerate(("Write", "Read", "Edit"), start=1):
            response = failure.run(
                self.payload(tool=tool, target="same", session="target-only"),
                self.cfg,
                now=float(index),
            )
        self.assertIn("3 times on same:", response["systemMessage"])
        self.assertNotIn("Edit", response["systemMessage"])

        payload = self.payload(session="both")
        for when in (1.0, 2.0, 3.0):
            response = failure.run(payload, self.cfg, now=when)
        self.assertIn("for Write on /work/a.py:", response["systemMessage"])

    def test_file_target_aliases_share_canonical_streak(self):
        aliases = ("/work/a.py", "/work/./a.py", "/work/x/../a.py")
        for when, target in enumerate(aliases, start=1):
            payload = self.payload(target=target)
            payload["cwd"] = "/work"
            response = failure.run(payload, self.cfg, now=float(when))
        targets = self.state()[failure.FAILURE_STREAKS_KEY]["targets"]
        self.assertEqual(set(targets), {"/work/a.py"})
        self.assertEqual(targets["/work/a.py"]["count"], 3)
        self.assertIn("on /work/a.py", response["systemMessage"])

    def test_relative_target_policy_uses_absolute_cwd_or_stays_relative(self):
        with_cwd = self.payload(session="with-cwd", target="x/../a.py")
        with_cwd["cwd"] = "/work/project"
        failure.run(with_cwd, self.cfg, now=1.0)
        self.assertIn(
            "/work/project/a.py",
            self.state("with-cwd")[failure.FAILURE_STREAKS_KEY]["targets"],
        )

        failure.run(
            self.payload(session="without-cwd", target="x/../a.py"),
            self.cfg,
            now=1.0,
        )
        self.assertIn(
            "a.py", self.state("without-cwd")[failure.FAILURE_STREAKS_KEY]["targets"]
        )

    def test_invalid_session_writes_no_state_or_ledger(self):
        before = len(self.rows())
        invalid = (
            ".",
            "..",
            "../escape",
            "..\\escape",
            "bad session",
            "x" * 129,
            "line\nfeed",
        )
        for session in invalid:
            self.assertEqual(
                failure.run(self.payload(session=session), self.cfg, now=1.0), {}
            )
        self.assertEqual(len(self.rows()), before)
        self.assertFalse(Path(self.cfg["state_root"]).exists())

    def test_invalid_session_stops_before_config_and_ledger_wrapper(self):
        for session in (".", ".."):
            with (
                mock.patch.object(failure, "effective_config") as effective,
                mock.patch.object(failure, "run_with_ledger") as ledger,
            ):
                self.assertEqual(
                    failure.run(self.payload(session=session), self.cfg, now=1.0), {}
                )
            effective.assert_not_called()
            ledger.assert_not_called()

    EXPECTED_DECISION_ROW = {
        "session_id": "s1",
        "hook": "failure",
        "event": "PostToolUseFailure",
        "family": "tool_failure",
        "rule": "repeated_failure",
        "path": "/work/a.py",
        "tool_use_id": "call-1",
        "turn_id": "",
        "outcome": "inject",
        "duration_ms": 12,
    }

    def test_guidance_and_heartbeat_ledger_rows_are_exact(self):
        for when in (1.0, 2.0, 3.0):
            failure.run(self.payload(), self.cfg, now=when)
        rows = self.rows()
        decisions = [row for row in rows if row["event"] == "PostToolUseFailure"]
        heartbeats = [row for row in rows if row["event"] == "observed"]

        self.assertEqual(len(decisions), 1)
        projected = {key: decisions[0][key] for key in self.EXPECTED_DECISION_ROW}
        self.assertEqual(projected, self.EXPECTED_DECISION_ROW)
        self.assertEqual(len(heartbeats), 3)
        self.assertTrue(all(row["hook"] == "failure" for row in heartbeats))

    def test_corrupt_state_blocks_the_update_without_replacing_it(self):
        state_dir = Path(self.cfg["state_root"]) / "s1"
        state_dir.mkdir(parents=True)
        state_file = state_dir / session_state.STATE_FILENAME
        state_file.write_text("{broken", encoding="utf-8")
        self.assertEqual(failure.run(self.payload(), self.cfg, now=1.0), {})
        self.assertEqual(state_file.read_text(encoding="utf-8"), "{broken")

    def test_legacy_shaped_streaks_self_heal(self):
        session_state.write_state(
            "s1", {failure.FAILURE_STREAKS_KEY: ["legacy"]}, self.cfg["state_root"]
        )
        failure.run(self.payload(), self.cfg, now=1.0)
        self.assertEqual(
            self.state()[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]["count"], 1
        )

    def test_state_update_failure_allows(self):
        with mock.patch.object(
            failure.session_state, "update_state_strict", side_effect=OSError("read only")
        ):
            self.assertEqual(failure.run(self.payload(), self.cfg, now=1.0), {})

    def test_valid_session_forms_are_isolated_and_oversize_is_rejected(self):
        sessions = (
            "scope:child",
            "scope.child",
            "123e4567-e89b-12d3-a456-426614174000",
            "s" * 128,
        )
        for index, session in enumerate(sessions, start=1):
            failure.run(self.payload(session=session), self.cfg, now=float(index))
            streak = self.state(session)[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]
            self.assertEqual(streak["count"], 1)
        self.assertEqual(
            len({str(Path(self.cfg["state_root"]) / item) for item in sessions}), 4
        )
        failure.run(self.payload(session="s" * 129), self.cfg, now=10.0)
        self.assertFalse((Path(self.cfg["state_root"]) / ("s" * 129)).exists())

    def test_target_normalization_is_lexical_and_pins_windows_like_input(self):
        symlink = self.root / "alias"
        destination = self.root / "destination" / "nested"
        destination.mkdir(parents=True)
        symlink.symlink_to(destination, target_is_directory=True)
        payload = self.payload(
            target=str(symlink / ".." / "file.py"), session="lexical"
        )
        failure.run(payload, self.cfg, now=1.0)
        targets = self.state("lexical")[failure.FAILURE_STREAKS_KEY]["targets"]
        self.assertEqual(set(targets), {str(self.root / "file.py")})

        windows = self.payload(target=r"C:\work\file.py", session="windows")
        failure.run(windows, self.cfg, now=2.0)
        windows_targets = self.state("windows")[failure.FAILURE_STREAKS_KEY]["targets"]
        self.assertEqual(set(windows_targets), {r"C:\work\file.py"})


class SuccessResetTests(HookTestCase):
    def test_success_resets_counts_backoff_and_threshold_guidance(self):
        payload = self.payload(tool="mcp__github__search")
        failure.run(payload, self.cfg, now=1.0)
        failure.run(payload, self.cfg, now=2.0)
        self.assertEqual(self.succeed(tool="mcp__github__search"), {})
        self.assertEqual(
            pre_mcp.run(
                {
                    "session_id": "s1",
                    "tool_name": "mcp__github__other",
                    "tool_use_id": "probe",
                },
                self.cfg,
                now=3.0,
            ),
            {},
        )
        self.assertEqual(failure.run(payload, self.cfg, now=4.0), {})
        state = self.state()
        self.assertEqual(
            state[failure.FAILURE_STREAKS_KEY]["tools"]["mcp__github__search"]["count"],
            1,
        )
        self.assertEqual(state[failure.MCP_HEALTH_KEY]["github"]["failure_count"], 1)
        self.assertEqual(state[failure.MCP_HEALTH_KEY]["github"]["retry_after"], 34.0)

    def test_success_between_failures_prevents_threshold_guidance(self):
        payload = self.payload()
        failure.run(payload, self.cfg, now=1.0)
        failure.run(payload, self.cfg, now=2.0)
        self.succeed()
        self.assertEqual(failure.run(payload, self.cfg, now=3.0), {})
        self.assertEqual(
            self.state()[failure.FAILURE_STREAKS_KEY]["tools"]["Write"]["count"], 1
        )

    def _seed_streaks_for_removal_test(self) -> None:
        failure.run(self.payload(tool="Write", target="a"), self.cfg, now=1.0)
        failure.run(self.payload(tool="Read", target="b"), self.cfg, now=2.0)
        failure.run(self.payload(tool="mcp__github__search", target="mcp-a"), self.cfg, now=3.0)
        failure.run(self.payload(tool="mcp__github__other", target="mcp-b"), self.cfg, now=4.0)
        failure.run(self.payload(tool="mcp__linkup__search", target="linkup"), self.cfg, now=5.0)
        session_state.update_state(
            "s1",
            lambda state: {
                **state,
                "unrelated": {"keep": True},
                failure.FAILURE_STREAKS_KEY: {
                    **state[failure.FAILURE_STREAKS_KEY],
                    "metadata": {"owner": "keep", "nested": {"version": 7}},
                },
            },
            self.cfg["state_root"],
        )

    def assert_only_matching_mcp_entry_was_removed(self, state: dict) -> None:
        streaks = state[failure.FAILURE_STREAKS_KEY]
        self.assertNotIn("mcp__github__search", streaks["tools"])
        self.assertNotIn("mcp-a", streaks["targets"])
        self.assertIn("mcp__github__other", streaks["tools"])
        self.assertIn("mcp-b", streaks["targets"])
        self.assertIn("Write", streaks["tools"])
        self.assertIn("a", streaks["targets"])
        self.assertEqual(streaks["metadata"], {"owner": "keep", "nested": {"version": 7}})
        self.assertEqual(state["unrelated"], {"keep": True})
        self.assertNotIn("github", state[failure.MCP_HEALTH_KEY])
        self.assertIn("linkup", state[failure.MCP_HEALTH_KEY])

    def test_success_removes_only_matching_entries_and_mcp_server(self):
        self._seed_streaks_for_removal_test()

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda _: self.succeed(tool="mcp__github__search", target="mcp-a"),
                    range(16),
                )
            )

        self.assert_only_matching_mcp_entry_was_removed(self.state())

    def test_success_state_write_failure_blocks_undecidable_instead_of_losing_state(self):
        failure.run(self.payload(), self.cfg, now=1.0)
        before = self.state()
        with (
            mock.patch.object(failure.session_state, "update_state", side_effect=OSError("read only")),
            mock.patch.object(failure.session_state, "update_state_strict", side_effect=OSError("read only")),
        ):
            response = self.succeed(record_gate=True)
        self.assertEqual(response["decision"], "block")
        self.assertIn("could not evaluate this edit", response["reason"])
        self.assertEqual(self.state(), before)

    def test_invalid_success_session_writes_no_state_or_ledger(self):
        for session in (".", "..", "x" * 129):
            self.assertEqual(self.succeed(session=session), {})
        self.assertFalse(Path(self.cfg["state_root"]).exists())
        self.assertEqual(self.rows(), [])

    def test_invalid_success_helper_session_stops_before_config_and_state(self):
        for session in (".", ".."):
            with (
                mock.patch.object(failure, "effective_config") as effective,
                mock.patch.object(failure.session_state, "update_state") as update,
            ):
                failure.record_success(self.payload(session=session), self.cfg)
            effective.assert_not_called()
            update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
