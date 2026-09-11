from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import session_state
    from .findings import Finding, Outcome
    from .finding_output import (
        clip as _clip, deduplicated as _deduplicated, format_row,
        safe_component as _safe_component, safe_text as _safe_text,
    )
except ImportError:
    import session_state
    from findings import Finding, Outcome
    from finding_output import (
        clip as _clip, deduplicated as _deduplicated, format_row,
        safe_component as _safe_component, safe_text as _safe_text,
    )

LEDGER_FILENAME = "ledger.jsonl"
LEDGER_LOCK_FILENAME = ".ledger.lock"
ADJUDICATION_FILENAME = "adjudications.jsonl"
REPORT_DIRNAME = "reports"
MAX_REPORT_FILES = 300
MAX_COMPACT_BYTES = 4096
MAX_COMPACT_FIELD_BYTES = 768
MAX_CURRENT_LEDGER_BYTES = 256 * 1024
MAX_CURRENT_LEDGER_ROWS = 512

OUTCOMES = Outcome


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    session_id: str
    hook: str
    event: str
    family: str
    rule: str
    path: str
    tool_use_id: str
    outcome: Outcome | str
    duration_ms: int
    turn_id: str


@dataclass(frozen=True, slots=True)
class HeartbeatRecord:
    session_id: str
    hook: str
    turn_id: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class LedgerInvocation:
    hook: str
    payload: dict
    ledger_root: str | os.PathLike[str] | None
    state_root: str | os.PathLike[str] | None


@dataclass(frozen=True, slots=True)
class Adjudication:
    family: str
    ref_ts: str
    label: bool


def _reports_dir() -> Path:
    return session_state.plugin_data_home() / REPORT_DIRNAME


def _prune_reports(directory: Path, keep: int) -> None:
    try:
        entries = sorted(directory.glob("*.json"), key=lambda entry: entry.stat().st_mtime)
    except OSError:
        return
    for stale in entries[: max(len(entries) - keep, 0)]:
        try:
            stale.unlink()
        except OSError:
            pass


def write_full_report(findings: list[dict], config: dict | None = None) -> str:
    fields = config or {}
    session_id = _safe_component(fields.get("session_id"), "session")
    turn_id = _safe_component(fields.get("turn_id"), "turn")
    directory = _reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}-{turn_id}-{uuid.uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, ensure_ascii=True, indent=2)
    _prune_reports(directory, MAX_REPORT_FILES)
    return str(path)


BLOCK_LEAD = "agent-discipline-watcher blocked findings:"
OBSERVE_LEAD = (
    "agent-discipline-watcher is observing these, not blocking. "
    "Judge each one and either repair it or state why it stands."
)


def compact_block(
    findings: list[dict],
    config: dict | None = None,
    lead: str = BLOCK_LEAD,
) -> tuple[str, str]:
    max_rows = int((config or {}).get("max_rows", 8))
    unique = _deduplicated(findings, config)
    report = write_full_report(unique, config)
    rows = [format_row(item) for item in unique[:max_rows]]
    extra = len(unique) - len(rows)
    if extra > 0:
        rows.append(f"... {extra} more")
    lines = [_clip(lead, MAX_COMPACT_FIELD_BYTES)]
    lines.extend(_clip(row, MAX_COMPACT_FIELD_BYTES) for row in rows)
    lines.append("Full report: " + _clip(report, MAX_COMPACT_FIELD_BYTES))
    reason = _clip("\n".join(lines), MAX_COMPACT_BYTES)
    return reason, report


def verdict_message(
    decisions: list[tuple[dict, str]], config: dict | None = None
) -> tuple[str, str]:
    blocking = [finding for finding, outcome in decisions if outcome == Outcome.BLOCK]
    if blocking:
        return "block", compact_block(blocking, config)[0]
    observed = [finding for finding, outcome in decisions if outcome == Outcome.WOULD_BLOCK]
    if not observed:
        return "release", ""
    return "observe", compact_block(observed, config, lead=OBSERVE_LEAD)[0]


def inherited_advice(findings: list[dict], config: dict | None = None) -> str:
    if not findings:
        return ""
    lead = (
        f"agent-discipline-watcher: this file already carried {len(findings)} findings "
        "you did not write. Fix them while you are in here."
    )
    return compact_block(findings, config, lead=lead)[0]


def _default_ledger_root() -> Path:
    return session_state.plugin_data_home() / "ledger"


def _ledger_dir(root: str | os.PathLike[str] | None) -> Path:
    return Path(root) if root is not None else _default_ledger_root()


@contextmanager
def ledger_lock(root: str | os.PathLike[str] | None):
    directory = _ledger_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / LEDGER_LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def ledger_path(root: str | os.PathLike[str] | None = None) -> Path:
    return _ledger_dir(root) / LEDGER_FILENAME


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ledger_row(**fields) -> dict:
    return {"ts": now_iso(), **fields}


def append_row(row: dict, root: str | os.PathLike[str] | None = None) -> None:
    try:
        line = json.dumps(row, ensure_ascii=True)
        with ledger_lock(root):
            with (_ledger_dir(root) / LEDGER_FILENAME).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: ledger append failed: {exc}\n")


def _read_turn_id(
    session_id: str, state_root: str | os.PathLike[str] | None = None
) -> str:
    if not session_id:
        return ""
    try:
        value = session_state.read_state(session_id, state_root).get("turn_id")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _decision_from_fields(fields: dict[str, object]) -> tuple[DecisionRecord, object]:
    values = dict(fields)
    root = values.pop("root", None)
    turn_id = values.pop("turn_id", "")
    required = {
        "session_id", "hook", "event", "family", "rule", "path",
        "tool_use_id", "outcome", "duration_ms",
    }
    if set(values) != required:
        raise TypeError(f"record_decision fields must be {sorted(required)!r}")
    return DecisionRecord(turn_id=turn_id, **values), root


def record_decision(*values: object, **fields: object) -> None:
    if len(values) == 1 and isinstance(values[0], DecisionRecord):
        decision = values[0]
        root = fields.pop("root", None)
        if fields:
            raise TypeError("DecisionRecord only accepts a root keyword")
    elif not values:
        decision, root = _decision_from_fields(fields)
    else:
        raise TypeError("record_decision requires a DecisionRecord or named legacy fields")
    if decision.outcome not in tuple(Outcome):
        raise ValueError(f"unknown outcome: {decision.outcome!r}")
    append_row(
        _ledger_row(
            session_id=decision.session_id, hook=decision.hook,
            event=decision.event, family=decision.family, rule=decision.rule,
            path=decision.path, tool_use_id=decision.tool_use_id,
            turn_id=decision.turn_id, outcome=decision.outcome,
            duration_ms=decision.duration_ms,
        ),
        root,
    )


def _heartbeat_from_fields(fields: dict[str, object]) -> tuple[HeartbeatRecord, object]:
    values = dict(fields)
    root = values.pop("root", None)
    duration_ms = values.pop("duration_ms", 0)
    required = {"session_id", "hook", "turn_id"}
    if set(values) != required:
        raise TypeError(f"record_heartbeat fields must be {sorted(required)!r}")
    return HeartbeatRecord(duration_ms=duration_ms, **values), root


def record_heartbeat(*values: object, **fields: object) -> None:
    if len(values) == 1 and isinstance(values[0], HeartbeatRecord):
        heartbeat = values[0]
        root = fields.pop("root", None)
        if fields:
            raise TypeError("HeartbeatRecord only accepts a root keyword")
    elif not values:
        heartbeat, root = _heartbeat_from_fields(fields)
    else:
        raise TypeError("record_heartbeat requires a HeartbeatRecord or named legacy fields")
    append_row(
        _ledger_row(
            session_id=heartbeat.session_id, hook=heartbeat.hook,
            event="observed", family="", rule="", path="", tool_use_id="",
            turn_id=heartbeat.turn_id, outcome="", duration_ms=heartbeat.duration_ms,
        ),
        root,
    )


def _resolve_outcome(finding: dict, config: dict | None) -> str:
    """Import config late, because config imports this module and a top-level import would cycle."""
    try:
        from .config import resolve_outcome
    except ImportError:
        from config import resolve_outcome
    return resolve_outcome(finding, config)


def record_findings(
    *,
    session_id: str,
    hook: str,
    event: str,
    findings: list[dict],
    turn_id: str,
    tool_use_id: str = "",
    duration_ms: int = 0,
    root: str | os.PathLike[str] | None = None,
    config: dict | None = None,
) -> list[tuple[dict, str]]:
    candidates = _deduplicated(findings, {"session_id": session_id, "turn_id": turn_id})
    evaluated = [
        (Finding.from_dict(finding), finding, _resolve_outcome(finding, config))
        for finding in candidates
    ]
    if session_id:
        for value, _finding, outcome in evaluated:
            record_decision(
                session_id=session_id, hook=hook, event=event,
                family=value.family, rule=value.rule,
                path=value.path or "", tool_use_id=tool_use_id,
                outcome=outcome, duration_ms=duration_ms,
                turn_id=turn_id, root=root,
            )
    return [(finding, outcome) for _value, finding, outcome in evaluated]


def _ledger_call(
    values: tuple[object, ...],
    fields: dict[str, object],
) -> tuple[LedgerInvocation, Callable[[str], dict]]:
    if len(values) == 2 and isinstance(values[0], LedgerInvocation) and callable(values[1]):
        if fields:
            raise TypeError("LedgerInvocation cannot be combined with named fields")
        return values[0], values[1]
    if values:
        raise TypeError("run_with_ledger requires named legacy fields or an invocation and gate")
    legacy = dict(fields)
    gate = legacy.pop("gate", None)
    invocation = LedgerInvocation(
        hook=legacy.pop("hook"),
        payload=legacy.pop("payload"),
        ledger_root=legacy.pop("ledger_root", None),
        state_root=legacy.pop("state_root", None),
    )
    if legacy or not callable(gate):
        raise TypeError("run_with_ledger legacy fields are invalid")
    return invocation, gate


def run_with_ledger(*values: object, **fields: object) -> dict:
    invocation, gate = _ledger_call(values, fields)
    session_id = str(invocation.payload.get("session_id") or "")
    host_turn_id = invocation.payload.get("turn_id")
    turn_id = (
        host_turn_id if isinstance(host_turn_id, str) and host_turn_id
        else _read_turn_id(session_id, invocation.state_root)
    ) if session_id else ""
    if session_id:
        session_state.acquire_session_lease(session_id, invocation.state_root)
    started = time.monotonic()
    try:
        return gate(turn_id)
    finally:
        if session_id:
            record_heartbeat(
                HeartbeatRecord(
                    session_id,
                    invocation.hook,
                    turn_id,
                    int((time.monotonic() - started) * 1000),
                ),
                root=invocation.ledger_root,
            )


def read_jsonl(filename: str, root: str | os.PathLike[str] | None = None) -> list[dict]:
    path = _ledger_dir(root) / filename
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


_read_jsonl = read_jsonl


def read_session_turn(
    session_id: str,
    turn_id: str,
    root: str | os.PathLike[str] | None = None,
    *,
    max_bytes: int = MAX_CURRENT_LEDGER_BYTES,
    max_rows: int = MAX_CURRENT_LEDGER_ROWS,
) -> list[dict]:
    if (
        not isinstance(session_id, str) or not session_id
        or not isinstance(turn_id, str) or not turn_id
    ):
        return []
    path = _ledger_dir(root) / LEDGER_FILENAME
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            window = max(1, int(max_bytes))
            handle.seek(max(0, size - window))
            data = handle.read(window)
    except OSError:
        return []
    if size > len(data):
        newline = data.find(b"\n")
        data = data[newline + 1:] if newline >= 0 else b""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        lines = data.decode("utf-8", errors="ignore").splitlines()
    rows: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("session_id") == session_id and row.get("turn_id") != turn_id:
            break
        if row.get("session_id") == session_id and row.get("turn_id") == turn_id:
            rows.append(row)
            if len(rows) >= max(1, int(max_rows)):
                break
    rows.reverse()
    return rows


read_current_session_turn = read_session_turn
read_current_turn = read_session_turn


def observe_report(
    family: str, root: str | os.PathLike[str] | None = None
) -> list[dict]:
    return [
        row
        for row in read_jsonl(LEDGER_FILENAME, root)
        if row.get("outcome") == "would_block" and row.get("family") == family
    ]


def adjudicate(adjudication: Adjudication | str, *values: object) -> dict:
    if isinstance(adjudication, str):
        if len(values) not in {2, 3} or not isinstance(values[0], str):
            raise TypeError("adjudicate requires family, reference timestamp, label, and optional root")
        adjudication = Adjudication(adjudication, values[0], bool(values[1]))
        root = values[2] if len(values) == 3 else None
    else:
        if len(values) > 1:
            raise TypeError("Adjudication accepts at most one root")
        root = values[0] if values else None
    row = {
        "family": adjudication.family,
        "ref_ts": adjudication.ref_ts,
        "label": adjudication.label,
        "adjudicated_at": now_iso(),
    }
    try:
        directory = _ledger_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ADJUDICATION_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: adjudication write failed: {exc}\n")
    return row


def false_signal_rate(
    family: str, root: str | os.PathLike[str] | None = None
) -> float | None:
    turn_ids = {
        row["turn_id"]
        for row in read_jsonl(LEDGER_FILENAME, root)
        if isinstance(row.get("turn_id"), str) and row.get("turn_id")
    }
    if len(turn_ids) < 20:
        return None
    false_count = sum(
        1
        for row in read_jsonl(ADJUDICATION_FILENAME, root)
        if row.get("family") == family and row.get("label") is False
    )
    return false_count * 20 / len(turn_ids)
