"""Split out because hostile input must never persist state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest import mock

import failure
import pre_mcp
import record
from lib import session_state
from test_failure import HookTestCase, HostileDict, HostileNumber, HostileString

INVALID_SESSIONS: tuple[object, ...] = (
    ".",
    "..",
    "../escape",
    "..\\escape",
    HostileString("hostile"),
    "x" * 129,
)
HOSTILE_MCP_NAMES = (
    "mcp__github",
    "mcp____search",
    "mcp__github__",
    "mcp__../x__search",
    "MCP__github__search",
    "mcp__git hub__search",
    "mcp__github__/search",
    "mcp__github__search!",
    "mcp__github__search/name",
    "mcp__githüb__search",
    "mcp__github__搜索",
    "mcp__" + "a" * 129 + "__search",
)
INVALID_NOW: tuple[object, ...] = (
    float("nan"),
    float("inf"),
    -1,
    True,
    "20",
    10**100,
    HostileNumber(),
)
LEDGER_FIELDS = ("family", "rule", "path", "tool_use_id", "outcome", "duration_ms")


class RecordContinuityTests(HookTestCase):
    def _violating_file(self) -> Path:
        target = self.root / "violation.py"
        target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
        return target

    @staticmethod
    def _block_without_report_path(response: dict) -> tuple[object, str]:
        reason = str(response.get("reason", ""))
        return response.get("decision"), reason.split("\nFull report:", maxsplit=1)[0]

    def _record_write(self, target: Path, **fields: object) -> dict:
        payload = {"cwd": str(self.root), "tool_name": "Write", "tool_input": {"file_path": str(target)}}
        return record.run({**payload, **fields}, self.cfg)

    def test_invalid_session_is_sessionless_for_persistence_but_not_scan(self) -> None:
        target = self._violating_file()
        sessionless = self._block_without_report_path(self._record_write(target))
        for invalid in INVALID_SESSIONS:
            response = self._record_write(target, session_id=invalid)
            self.assertEqual(self._block_without_report_path(response), sessionless)
        self.assertFalse(Path(self.cfg["state_root"]).exists())
        self.assertFalse(Path(self.cfg["ledger_root"]).exists())

    def test_invalid_cwd_is_none_for_config_lookup_and_scan_continues(self) -> None:
        target = self._violating_file()
        invalid_cwds: tuple[object, ...] = (
            "/repo\x00escape",
            "/repo\nother",
            "x" * 4097,
            HostileString("/repo"),
        )
        for cwd in invalid_cwds:
            target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
            with mock.patch.object(
                record, "effective_config", wraps=record.effective_config
            ) as effective:
                response = self._record_write(target, cwd=cwd)
            self.assertEqual(response.get("decision"), "block")
            advisory = response.get("reason", "")
            self.assertIsInstance(advisory, str)
            self.assertTrue(advisory.strip())
            self.assertIn("PostToolUse payload requires a trusted cwd", advisory)
            self.assertIsNone(effective.call_args.args[1])

    def _malicious_project(self, state: Path, ledger: Path) -> Path:
        project = self.root / "project"
        project.mkdir()
        roots = {"state_root": str(state), "ledger_root": str(ledger)}
        (project / ".agent-discipline.json").write_text(json.dumps(roots), encoding="utf-8")
        return project

    def test_project_config_cannot_redirect_any_persistence_root(self) -> None:
        malicious_state = self.root / "redirected-state"
        malicious_ledger = self.root / "redirected-ledger"
        project = self._malicious_project(malicious_state, malicious_ledger)
        target = project / "clean.py"
        target.write_text("print(1)\n", encoding="utf-8")
        failure_payload = self.payload(tool="mcp__github__search")
        failure_payload["cwd"] = str(project)
        failure.run(failure_payload, self.cfg, now=10.0)
        probe = {"session_id": "s1", "cwd": str(project), "tool_name": "mcp__github__other", "tool_use_id": "probe"}
        pre_mcp.run(probe, self.cfg, now=20.0)
        self._record_write(target, session_id="s1", cwd=str(project))
        self.assertTrue(Path(self.cfg["ledger_root"]).exists())
        self.assertFalse(malicious_state.exists() or malicious_ledger.exists())


class McpCircuitBreakerTests(HookTestCase):
    def mcp_payload(self, server: str = "github", session: str = "s1") -> dict[str, object]:
        return {
            "session_id": session,
            "hook_event_name": "PreToolUse",
            "tool_name": f"mcp__{server}__search",
            "tool_use_id": "probe-1",
        }

    def fail_mcp(self, when: float, session: str = "s1") -> dict:
        payload = self.payload(tool="mcp__github__search", session=session)
        return failure.run(payload, self.cfg, now=when)

    def test_parser_accepts_exact_shape_and_rejects_hostile_names(self) -> None:
        accepted = {
            "mcp__github-1__search_repos": ("github-1", "search_repos"),
            "mcp__server.name__tool.name": ("server.name", "tool.name"),
            "mcp___server__-tool": ("_server", "-tool"),
            "mcp__-server___tool": ("-server", "_tool"),
            "mcp__server__search__extra": ("server", "search__extra"),
        }
        for name, parsed in accepted.items():
            self.assertEqual(failure.parse_mcp_tool(name), parsed)
        for name in HOSTILE_MCP_NAMES:
            self.assertIsNone(failure.parse_mcp_tool(name), name)

    def test_parser_part_lengths_are_exact(self) -> None:
        server = "s" * 128
        tool = "t" * 128
        self.assertEqual(
            failure.parse_mcp_tool(f"mcp__{server}__{tool}"), (server, tool)
        )
        self.assertIsNone(failure.parse_mcp_tool(f"mcp__{server}x__search"))
        self.assertIsNone(failure.parse_mcp_tool(f"mcp__server__{tool}x"))
        self.assertIsNone(failure.parse_mcp_tool(HostileString("mcp__a__b")))

    def test_backoff_sequence_and_exact_expiry(self) -> None:
        now = 100.0
        for expected_count, expected_delay in enumerate(
            (30, 60, 120, 240, 480, 600, 600), start=1
        ):
            self.fail_mcp(now)
            health = self.state()[failure.MCP_HEALTH_KEY]["github"]
            self.assertEqual(health["failure_count"], expected_count)
            self.assertEqual(health["retry_after"], now + expected_delay)
            blocked = pre_mcp.run(
                self.mcp_payload(), self.cfg, now=now + expected_delay - 0.001
            )
            self.assertEqual(blocked["decision"], "block")
            self.assertEqual(
                pre_mcp.run(self.mcp_payload(), self.cfg, now=now + expected_delay), {}
            )
            now += expected_delay

    def test_clock_reversal_does_not_move_deadline_back(self) -> None:
        self.fail_mcp(100.0)
        self.fail_mcp(90.0)
        health = self.state()[failure.MCP_HEALTH_KEY]["github"]
        self.assertEqual(health["failure_count"], 2)
        self.assertEqual(health["last_failure_at"], 100.0)
        self.assertEqual(health["retry_after"], 160.0)

    def test_huge_legacy_count_is_capped_without_large_exponent(self) -> None:
        session_state.write_state(
            "s1",
            {
                failure.MCP_HEALTH_KEY: {
                    "github": {"failure_count": 10**100, "last_failure_at": 5.0}
                }
            },
            self.cfg["state_root"],
        )
        self.fail_mcp(10.0)
        health = self.state()[failure.MCP_HEALTH_KEY]["github"]
        self.assertEqual(health["failure_count"], 10**100 + 1)
        self.assertEqual(health["retry_after"], 610.0)

    def test_expired_probe_then_failure_extends_backoff(self) -> None:
        self.fail_mcp(10.0)
        self.assertEqual(pre_mcp.run(self.mcp_payload(), self.cfg, now=40.0), {})
        self.fail_mcp(40.0)
        self.assertEqual(
            self.state()[failure.MCP_HEALTH_KEY]["github"]["retry_after"], 100.0
        )
        self.assertEqual(
            pre_mcp.run(self.mcp_payload(), self.cfg, now=99.0)["decision"], "block"
        )

    def test_malformed_legacy_or_unreadable_state_allows(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {},
            {failure.MCP_HEALTH_KEY: []},
            {failure.MCP_HEALTH_KEY: {"github": "bad"}},
            {failure.MCP_HEALTH_KEY: {"github": {"retry_after": "later"}}},
            {
                failure.MCP_HEALTH_KEY: {
                    "github": {"failure_count": 1, "retry_after": 10**100}
                }
            },
        )
        for index, state in enumerate(cases):
            session = f"s{index}"
            session_state.write_state(session, state, self.cfg["state_root"])
            self.assertEqual(
                pre_mcp.run(self.mcp_payload(session=session), self.cfg, now=1.0), {}
            )
        with mock.patch.object(
            pre_mcp.session_state, "read_state", side_effect=OSError("denied")
        ):
            self.assertEqual(pre_mcp.run(self.mcp_payload(), self.cfg, now=1.0), {})

    def test_health_is_per_session_and_non_mcp_names_allow(self) -> None:
        self.fail_mcp(1.0, session="s1")
        self.assertEqual(
            pre_mcp.run(self.mcp_payload(session="s2"), self.cfg, now=2.0), {}
        )
        payload = self.mcp_payload()
        payload["tool_name"] = "mcp__../github__search"
        self.assertEqual(pre_mcp.run(payload, self.cfg, now=2.0), {})

    def test_health_is_isolated_per_server_for_producer_and_consumer(self) -> None:
        failure.run(self.payload(tool="mcp__github__search"), self.cfg, now=10.0)
        failure.run(self.payload(tool="mcp__linkup__search"), self.cfg, now=20.0)
        health = self.state()[failure.MCP_HEALTH_KEY]
        self.assertEqual(set(health), {"github", "linkup"})
        self.assertEqual(health["github"]["retry_after"], 40.0)
        self.assertEqual(health["linkup"]["retry_after"], 50.0)
        self.assertEqual(
            pre_mcp.run(self.mcp_payload("github"), self.cfg, now=30.0)["decision"],
            "block",
        )
        self.assertEqual(
            pre_mcp.run(self.mcp_payload("linkup"), self.cfg, now=30.0)["decision"],
            "block",
        )
        self.assertEqual(pre_mcp.run(self.mcp_payload("other"), self.cfg, now=30.0), {})

    def test_invalid_pre_mcp_clock_allows_without_protocol_calls(self) -> None:
        self.fail_mcp(10.0)
        HostileNumber.calls = 0
        for now in INVALID_NOW:
            self.assertEqual(
                pre_mcp.run(self.mcp_payload(), self.cfg, now=cast(float, now)), {}
            )
        self.assertEqual(HostileNumber.calls, 0)

    def test_invalid_pre_mcp_boundary_allows_without_protocol_calls(self) -> None:
        self.fail_mcp(10.0)
        HostileDict.calls = 0
        self.assertEqual(
            pre_mcp.run(HostileDict(self.mcp_payload()), self.cfg, now=20.0), {}
        )
        self.assertEqual(HostileDict.calls, 0)
        self.assertEqual(pre_mcp.run({}, HostileDict(self.cfg), now=20.0), {})
        self.assertEqual(HostileDict.calls, 0)

    def test_invalid_pre_mcp_cwd_still_allows_healthy_server(self) -> None:
        invalid_cwds: tuple[object, ...] = (
            "/work\x00escape",
            "/work\nother",
            "x" * 4097,
            HostileString("/work"),
        )
        for cwd in invalid_cwds:
            payload = self.mcp_payload()
            payload["cwd"] = cwd
            self.assertEqual(pre_mcp.run(payload, self.cfg, now=1.0), {})

    def test_invalid_pre_mcp_session_writes_no_ledger(self) -> None:
        self.fail_mcp(10.0)
        before = len(self.rows())
        for session in (".", "..", "../escape"):
            payload = self.mcp_payload(session=session)
            self.assertEqual(pre_mcp.run(payload, self.cfg, now=20.0), {})
        self.assertEqual(len(self.rows()), before)

    def test_invalid_pre_mcp_session_stops_before_config_and_ledger_wrapper(self) -> None:
        for session in (".", ".."):
            with (
                mock.patch.object(pre_mcp, "safe_config") as safe_config,
                mock.patch.object(pre_mcp, "run_with_ledger") as ledger,
            ):
                self.assertEqual(
                    pre_mcp.run(self.mcp_payload(session=session), self.cfg, now=1.0),
                    {},
                )
            safe_config.assert_not_called()
            ledger.assert_not_called()

    def test_block_ledger_and_heartbeat_are_exact(self) -> None:
        self.fail_mcp(10.0)
        response = pre_mcp.run(self.mcp_payload(), self.cfg, now=20.0)
        self.assertEqual(
            response["reason"],
            "MCP server github is unavailable after 1 failure until 40.000. "
            "Fix the provider root cause or retry after expiry.",
        )
        rows = [row for row in self.rows() if row["hook"] == "pre_mcp"]
        decision = next(row for row in rows if row["event"] == "PreToolUse")
        expected = ("mcp_health", "server_backoff", "github", "probe-1", "block", 0)
        self.assertEqual({key: decision[key] for key in LEDGER_FIELDS}, dict(zip(LEDGER_FIELDS, expected)))
        self.assertEqual(sum(row["event"] == "observed" for row in rows), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
