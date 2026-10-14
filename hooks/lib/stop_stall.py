"""An identical Stop block repeats at most a few times, because the agent changed nothing that could clear it."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

from . import blocker_state, reporting

DEFAULT_LIMIT = 2
STALL_RULE = "stop_stall"
MAX_NAMED_FILES = 3


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


@dataclass(frozen=True, slots=True)
class BlockingSet:
    findings: list[dict]
    residual: list[str]


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
    return sha256(json.dumps([rows, sorted(blocking.residual)]).encode("utf-8")).hexdigest()


def _files(findings: list[dict]) -> str:
    names = sorted({Path(str(row.get("path") or "")).name for row in findings if row.get("path")})
    shown = ", ".join(names[:MAX_NAMED_FILES])
    return f"{shown} and {len(names) - MAX_NAMED_FILES} more" if len(names) > MAX_NAMED_FILES else shown


def notice(blocking: BlockingSet, repeats: int, report: str) -> str:
    tail = f" Full report: {report}" if report else ""
    if not blocking.findings:
        return f"agent-discipline-watcher: the same Stop block repeated {repeats} times with no change. Not blocking again.{tail}"
    count = len(blocking.findings)
    return (
        f"agent-discipline-watcher: {count} findings in {_files(blocking.findings)} are unchanged "
        f"since the last {repeats} Stops. Not blocking again.{tail}"
    )


def _record_release(call: StopCall) -> None:
    reporting.record_decision(
        session_id=call.scope.session_id, hook=call.hook, event=call.event, family="",
        rule=STALL_RULE, path="", tool_use_id="", outcome="release", duration_ms=0,
        turn_id=call.turn_id, root=call.cfg.get("ledger_root"),
    )


def guarded(call: StopCall, blocking: BlockingSet, build: ReasonBuilder) -> StopOutcome:
    """Released once with a notice, then silent, so an unchangeable finding stops costing a turn."""
    previous = blocker_state.stall(call.scope)
    current = fingerprint(blocking)
    stored = previous.get("count")
    same = previous.get("fp") == current and isinstance(stored, int)
    count = stored + 1 if same else 1
    report = str(previous.get("report") or "") if same else ""
    allowed = limit(call.cfg)
    if count > allowed + 1:
        return StopOutcome("", "")
    if count == allowed + 1:
        blocker_state.note_stall(call.scope, {"fp": current, "count": count, "report": report})
        _record_release(call)
        return StopOutcome("", notice(blocking, allowed, report))
    reason, written = build(report or None)
    blocker_state.note_stall(call.scope, {"fp": current, "count": count, "report": written})
    return StopOutcome(reason, "")
