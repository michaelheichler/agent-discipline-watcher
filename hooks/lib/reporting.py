"""Ledger, shared hook wrapper, and observe-report CLI."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

try:
    # Relative first because hook entry scripts import this as lib.reporting, where a bare name cannot resolve.
    from . import session_state
except ImportError:
    import session_state

LEDGER_FILENAME = "ledger.jsonl"
ADJUDICATION_FILENAME = "adjudications.jsonl"
REPORT_DIRNAME = "reports"
MAX_REPORT_FILES = 300
MAX_COMPACT_BYTES = 4096
MAX_COMPACT_FIELD_BYTES = 768

# Heartbeat rows carry outcome="" because they record an observation, not a decision.
OUTCOMES = ("block", "inject", "would_block", "no_edits", "release")

_UNSAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _reports_dir() -> Path:
    return session_state.plugin_data_home() / REPORT_DIRNAME


def _safe_component(value: object, fallback: str) -> str:
    text = _UNSAFE_COMPONENT_RE.sub("_", str(value or "")).strip("._")[:48]
    return text or fallback


def _prune_reports(directory: Path, keep: int) -> None:
    """Bounded here because nothing ever deleted a written report, and one blocking gate can write three per turn."""
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
    """Named by session and turn, and pruned on write, because the prior tempfile never got deleted by anything."""
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
    unique = _deduplicated(findings)
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


def _deduplicated(findings: list[dict]) -> list[dict]:
    seen: set[tuple[object, object, object]] = set()
    result: list[dict] = []
    for finding in findings:
        key = (finding.get("path") or finding.get("file"), finding.get("line"), finding.get("rule"))
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def _clip(value: object, limit: int) -> str:
    text = str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[: max(limit - 3, 0)].decode("utf-8", errors="ignore") + "..."


def verdict_message(
    decisions: list[tuple[dict, str]], config: dict | None = None
) -> tuple[str, str]:
    """Read gate state once for every hook, because a hook that judges findings on its own makes observe mean two things."""
    blocking = [finding for finding, outcome in decisions if outcome == "block"]
    if blocking:
        return "block", compact_block(blocking, config)[0]
    observed = [finding for finding, outcome in decisions if outcome == "would_block"]
    if not observed:
        return "release", ""
    return "observe", compact_block(observed, config, lead=OBSERVE_LEAD)[0]


def inherited_advice(findings: list[dict], config: dict | None = None) -> str:
    """Name debt the edit did not write, because dropping it in silence is what lets an old file stay broken."""
    if not findings:
        return ""
    lead = (
        f"agent-discipline-watcher: this file already carried {len(findings)} findings "
        "you did not write. Fix them while you are in here."
    )
    return compact_block(findings, config, lead=lead)[0]


def format_row(item: dict) -> str:
    path = item.get("path") or item.get("file") or "<pending>"
    status = item.get("status")
    prefix = f"[{status}] " if status else ""
    return (
        f"{prefix}{path}:{item.get('line')} "
        f"{item.get('family')}/{item.get('rule')}: "
        f"{item.get('action')}"
    )


def _default_ledger_root() -> Path:
    return session_state.plugin_data_home() / "ledger"


def _ledger_dir(root: str | os.PathLike[str] | None) -> Path:
    return Path(root) if root is not None else _default_ledger_root()


def ledger_path(root: str | os.PathLike[str] | None = None) -> Path:
    """Exposed because bin/agent-discipline needs the ledger file location without reaching into this module's private layout."""
    return _ledger_dir(root) / LEDGER_FILENAME


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _ledger_row(**fields) -> dict:
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
    """Write one decision row per finding and return the verdicts, so a gate leaves countable evidence."""
    decisions = [(finding, _resolve_outcome(finding, config)) for finding in findings]
    if not session_id:
        return decisions
    for finding, outcome in decisions:
        record_decision(
            session_id=session_id, hook=hook, event=event,
            family=str(finding.get("family", "")), rule=str(finding.get("rule", "")),
            path=str(finding.get("path", "")), tool_use_id=tool_use_id,
            outcome=outcome, duration_ms=duration_ms,
            turn_id=turn_id, root=root,
        )
    return decisions


def run_with_ledger(
    *,
    hook: str,
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
                session_id=session_id, hook=hook, turn_id=turn_id,
                root=ledger_root,
                duration_ms=int((time.monotonic() - started) * 1000),
            )


def read_jsonl(filename: str, root: str | os.PathLike[str] | None = None) -> list[dict]:
    """Public because batch.py must read this same ledger without duplicating the file's own parsing loop."""
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


# Kept because callers outside this module referenced the old private name before it was promoted.
_read_jsonl = read_jsonl


def observe_report(
    family: str, root: str | os.PathLike[str] | None = None
) -> list[dict]:
    """Return a family's would_block rows, oldest first."""
    return [
        row
        for row in read_jsonl(LEDGER_FILENAME, root)
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


def _observe_report_command(argv: list[str]) -> int:
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
