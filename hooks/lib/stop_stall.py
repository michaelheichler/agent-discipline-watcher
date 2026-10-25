"""Because no turn may stay stuck, an unchanged Stop block releases after a few repeats."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

from . import blocker_state, reporting, stop_scan

DEFAULT_LIMIT = 2
OWN_FINDING_LIMIT = 5
STALL_RULE = "stop_stall"
OWN_FAMILY = "own_finding"
MAX_NAMED_FILES = 3
MAX_LISTED_OWN = 5


class StopOutcome(NamedTuple):
    reason: str
    notice: str


@dataclass(frozen=True, slots=True)
class StopCall:
    scope: blocker_state.BlockerScope
    cfg: dict
    hook: str
    event: str
    turn_id: str
    stall_key: str = blocker_state.STALL_KEY


@dataclass(frozen=True, slots=True)
class BlockingSet:
    """`stamps` mark unscanned files, because an edit to a file Stop could not read must still reset the breaker."""

    findings: list[dict]
    residual: list[str]
    stamps: tuple[str, ...] = ()
    owned: bool = False


ReasonBuilder = Callable[[str | None], tuple[str, str]]


def limit(cfg: dict) -> int:
    value = cfg.get("stop_stall_limit", DEFAULT_LIMIT)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else DEFAULT_LIMIT


def fingerprint(blocking: BlockingSet) -> str:
    rows = sorted(
        [str(row.get("path", "")), str(row.get("rule", "")), str(row.get("line", "")),
         str(row.get("snippet", "")), str(row.get("content_hash", ""))]
        for row in blocking.findings
    )
    payload = [rows, sorted(blocking.residual), sorted(blocking.stamps)]
    return sha256(json.dumps(payload).encode("utf-8")).hexdigest()


def _files(findings: list[dict]) -> str:
    names = sorted({Path(str(row.get("path") or "")).name for row in findings if row.get("path")})
    shown = ", ".join(names[:MAX_NAMED_FILES])
    return f"{shown} and {len(names) - MAX_NAMED_FILES} more" if len(names) > MAX_NAMED_FILES else shown


def _own_findings(findings: list[dict]) -> str:
    own = [row for row in findings if not row.get(stop_scan.INHERITED_FIELD)]
    names = [f"{Path(str(row.get('path') or '')).name}:{row.get('line', '')} {row.get('rule', '')}" for row in own]
    shown = ", ".join(names[:MAX_LISTED_OWN])
    return f"{shown} and {len(names) - MAX_LISTED_OWN} more" if len(names) > MAX_LISTED_OWN else shown


def notice(blocking: BlockingSet, repeats: int, report: str) -> str:
    tail = f" Full report: {report}" if report else ""
    if not blocking.findings:
        return f"agent-discipline-watcher: the same Stop block repeated {repeats} times with no change. Not blocking again.{tail}"
    if blocking.owned:
        return (
            f"agent-discipline-watcher: the agent left its own findings unfixed through {repeats} identical Stops. "
            f"Not blocking again. Unfixed: {_own_findings(blocking.findings)}.{tail}"
        )
    count = len(blocking.findings)
    return (
        f"agent-discipline-watcher: {count} findings in {_files(blocking.findings)} are unchanged "
        f"since the last {repeats} Stops. Not blocking again.{tail}"
    )


def _record_release(call: StopCall, owned: bool) -> None:
    reporting.record_decision(
        session_id=call.scope.session_id, hook=call.hook, event=call.event, family=OWN_FAMILY if owned else "",
        rule=STALL_RULE, path="", tool_use_id="", outcome="release", duration_ms=0,
        turn_id=call.turn_id, root=call.cfg.get("ledger_root"),
    )


def _allowed(cfg: dict, blocking: BlockingSet) -> int:
    """Higher for own findings, so the agent gets more turns to fix them."""
    return max(limit(cfg), OWN_FINDING_LIMIT) if blocking.owned else limit(cfg)


def guarded(call: StopCall, blocking: BlockingSet, build: ReasonBuilder) -> StopOutcome:
    """Released once with a notice, then silent, so no finding traps a turn."""
    key = call.stall_key
    previous = blocker_state.stall(call.scope, key)
    current = fingerprint(blocking)
    stored = previous.get("count")
    same = previous.get("fp") == current and isinstance(stored, int)
    count = stored + 1 if same else 1
    report = str(previous.get("report") or "") if same else ""
    allowed = _allowed(call.cfg, blocking)
    if count > allowed + 1:
        return StopOutcome("", "")
    if count == allowed + 1:
        blocker_state.note_stall(call.scope, {"fp": current, "count": count, "report": report}, key)
        _record_release(call, blocking.owned)
        return StopOutcome("", notice(blocking, allowed, report))
    reason, written = build(report or None)
    blocker_state.note_stall(call.scope, {"fp": current, "count": count, "report": written}, key)
    return StopOutcome(reason, "")
