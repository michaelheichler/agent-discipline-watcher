"""Ledger, shared hook wrapper, and observe-report CLI."""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from lib import session_state

LEDGER_FILENAME = "ledger.jsonl"
ADJUDICATION_FILENAME = "adjudications.jsonl"

# Heartbeat rows carry outcome="" because they record an observation, not a decision.
OUTCOMES = ("block", "inject", "would_block", "no_edits", "release")


def write_full_report(findings: list[dict]) -> str:
    descriptor, raw_path = tempfile.mkstemp(prefix="agent-discipline-watcher-", suffix=".json")
    path = Path(raw_path)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, ensure_ascii=True, indent=2)
    return str(path)


def compact_block(
    findings: list[dict],
    config: dict | None = None,
) -> tuple[str, str]:
    max_rows = int((config or {}).get("max_rows", 8))
    report = write_full_report(findings)
    rows = [format_row(item) for item in findings[:max_rows]]
    extra = len(findings) - len(rows)
    if extra > 0:
        rows.append(f"... {extra} more")
    reason = "agent-discipline-watcher blocked findings:\n" + "\n".join(rows)
    reason += "\nFull report: " + report
    return reason, report


def format_row(item: dict) -> str:
    path = item.get("path") or item.get("file") or "<pending>"
    return (
        f"{path}:{item.get('line')} "
        f"{item.get('family')}/{item.get('rule')}: "
        f"{item.get('action')}"
    )


def _default_ledger_root() -> Path:
    """Return the production ledger root."""
    return Path.home() / ".agent-discipline" / "ledger"


def _ledger_dir(root: str | os.PathLike[str] | None) -> Path:
    """Resolve the ledger directory, falling back to the production root."""
    return Path(root) if root is not None else _default_ledger_root()


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _ledger_row(**fields) -> dict:
    """Return a ledger row stamped with the current timestamp."""
    return {"ts": now_iso(), **fields}


def append_row(row: dict, root: str | os.PathLike[str] | None = None) -> None:
    """Append one ledger row as JSONL, swallowing write errors so an unwritable ledger can never fail a hook."""
    try:
        directory = _ledger_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=True)
        with (directory / LEDGER_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: ledger append failed: {exc}\n")


def _read_turn_id(
    session_id: str, state_root: str | os.PathLike[str] | None = None
) -> str:
    """Return the current turn_id for the session, or '' when unset or unreadable."""
    if not session_id:
        return ""
    try:
        value = session_state.read_state(session_id, state_root).get("turn_id")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def record_decision(
    *,
    session_id: str,
    hook: str,
    event: str,
    family: str,
    rule: str,
    path: str,
    tool_use_id: str,
    outcome: str,
    duration_ms: int,
    turn_id: str = "",
    root: str | os.PathLike[str] | None = None,
) -> None:
    """Append one gate-decision row, validating outcome against OUTCOMES."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r}")
    append_row(
        _ledger_row(
            session_id=session_id, hook=hook, event=event, family=family,
            rule=rule, path=path, tool_use_id=tool_use_id, turn_id=turn_id,
            outcome=outcome, duration_ms=duration_ms,
        ),
        root,
    )


def record_heartbeat(
    *,
    session_id: str,
    hook: str,
    event: str,
    turn_id: str,
    duration_ms: int = 0,
    root: str | os.PathLike[str] | None = None,
) -> None:
    """Append one observed heartbeat row so every invocation contributes its turn_id to the denominator."""
    append_row(
        _ledger_row(
            session_id=session_id, hook=hook, event="observed", family="",
            rule="", path="", tool_use_id="", turn_id=turn_id, outcome="",
            duration_ms=duration_ms,
        ),
        root,
    )


def run_with_ledger(
    *,
    hook: str,
    event: str,
    payload: dict,
    gate: Callable[[str], dict],
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Run a gate, then emit one heartbeat row stamped with the session turn_id."""
    session_id = str(payload.get("session_id") or "")
    # A sessionless invocation skips the ledger because it has no turn_id to stamp.
    turn_id = _read_turn_id(session_id, state_root) if session_id else ""
    started = time.monotonic()
    try:
        return gate(turn_id)
    finally:
        if session_id:
            record_heartbeat(
                session_id=session_id, hook=hook, event=event, turn_id=turn_id,
                root=ledger_root,
                duration_ms=int((time.monotonic() - started) * 1000),
            )


def _read_jsonl(filename: str, root: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return every parsed JSONL row, skipping blank or unparseable lines."""
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


def observe_report(
    family: str, root: str | os.PathLike[str] | None = None
) -> list[dict]:
    """Return a family's would_block rows, oldest first."""
    return [
        row
        for row in _read_jsonl(LEDGER_FILENAME, root)
        if row.get("outcome") == "would_block" and row.get("family") == family
    ]


def adjudicate(
    family: str,
    ref_ts: str,
    label: bool,
    root: str | os.PathLike[str] | None = None,
) -> dict:
    """Persist one adjudication label, where True means justified and False means false signal."""
    row = {"family": family, "ref_ts": ref_ts, "label": bool(label),
           "adjudicated_at": now_iso()}
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
    """Return false signals per 20 distinct observed turn ids, or None below the 20-turn floor."""
    # Denominator is distinct turn ids, not row count, because a turn that fired many rows is one exposure.
    turn_ids = {
        row["turn_id"]
        for row in _read_jsonl(LEDGER_FILENAME, root)
        if isinstance(row.get("turn_id"), str) and row.get("turn_id")
    }
    if len(turn_ids) < 20:
        return None
    false_count = sum(
        1
        for row in _read_jsonl(ADJUDICATION_FILENAME, root)
        if row.get("family") == family and row.get("label") is False
    )
    return false_count * 20 / len(turn_ids)


def _observe_report_command(argv: list[str]) -> int:
    """Run the observe-report subcommand."""
    if len(argv) != 3:
        sys.stderr.write("usage: python3 -m lib.reporting observe-report <family>\n")
        return 2
    family = argv[2]
    rate = false_signal_rate(family)
    rows = observe_report(family)
    if rate is None:
        sys.stdout.write(f"{family}: need 20 distinct observed turn ids for a rate\n")
    else:
        sys.stdout.write(f"{family}: false-signal rate per 20 turns = {rate:.2f}\n")
    for row in rows:
        sys.stdout.write(
            f"{row.get('ts')}\tturn={row.get('turn_id')}\t{row.get('rule')}\t{row.get('path')}\n"
        )
    return 0


def _adjudicate_command(argv: list[str]) -> int:
    """Run the adjudicate subcommand."""
    if len(argv) != 5 or argv[4] not in ("true", "false"):
        sys.stderr.write(
            "usage: python3 -m lib.reporting adjudicate <family> <ts> <true|false>\n"
        )
        return 2
    family, ref_ts, label = argv[2], argv[3], argv[4] == "true"
    adjudicate(family, ref_ts, label)
    sys.stdout.write(
        f"adjudicated {family} {ref_ts} as "
        f"{'justified' if label else 'false-signal'}\n"
    )
    return 0


def _main(argv: list[str]) -> int:
    """Dispatch the observe-report and adjudicate subcommands."""
    if len(argv) < 2:
        sys.stderr.write(
            "usage: python3 -m lib.reporting observe-report <family> | "
            "adjudicate <family> <ts> <true|false>\n"
        )
        return 2
    if argv[1] == "observe-report":
        return _observe_report_command(argv)
    if argv[1] == "adjudicate":
        return _adjudicate_command(argv)
    sys.stderr.write(f"unknown command: {argv[1]}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
