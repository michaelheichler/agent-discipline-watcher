"""Ledger, shared hook wrapper, and observe-report CLI."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

try:
    # Relative first because hook entry scripts import this as lib.reporting, where a bare name cannot resolve.
    from . import embeddings, session_state
except ImportError:
    import embeddings
    import session_state

LEDGER_FILENAME = "ledger.jsonl"
ADJUDICATION_FILENAME = "adjudications.jsonl"

TOOL_USE_REPORT_DIRNAME = ".adw-tool-reports"
TOOL_USE_REPORT_PROTOCOL_VERSION = 1
TOOL_USE_REPORT_MAX_AGE_SECONDS = 3600
TOOL_USE_REPORT_MAX_BYTES = 20_000
TOOL_USE_REPORT_MAX_UNRESOLVED = 10
AMBIGUOUS_COMMENT_RULES = frozenset({"what_comment", "what_docstring", "weak_why_comment"})

_WHY_PROTOTYPES = [
    {"label": "WHY", "text": "kept because callers require stable ordering across retries"},
    {"label": "WHY", "text": "guards against a race that only shows up under concurrent writers"},
    {"label": "WHY", "text": "works around a platform limit that has no better fix"},
]


def _what_prototypes() -> list[dict]:
    """Sample the shared WHAT corpus instead of duplicating labeled examples in this module."""
    corpus = Path(__file__).with_name("corpus_what_comments.jsonl")
    try:
        lines = corpus.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[:5]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("text"):
            rows.append({"label": "WHAT", "text": str(row["text"])})
    return rows


def _comment_prototypes() -> list[dict]:
    return _WHY_PROTOTYPES + _what_prototypes()

# Heartbeat rows carry outcome="" because they record an observation, not a decision.
OUTCOMES = ("block", "must_fix", "inject", "would_block", "no_edits", "release")


def write_full_report(findings: list[dict]) -> str:
    descriptor, raw_path = tempfile.mkstemp(prefix="agent-discipline-watcher-", suffix=".json")
    path = Path(raw_path)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, ensure_ascii=True, indent=2)
    return str(path)


BLOCK_LEAD = "agent-discipline-watcher blocked findings:"
MUST_FIX_LEAD = (
    "agent-discipline-watcher changed or flagged the following. This is not a suggestion: "
    "re-check every line below before you consider this edit done."
)
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
    report = write_full_report(findings)
    rows = [format_row(item) for item in findings[:max_rows]]
    extra = len(findings) - len(rows)
    if extra > 0:
        rows.append(f"... {extra} more")
    reason = lead + "\n" + "\n".join(rows)
    reason += "\nFull report: " + report
    return reason, report


def verdict_message(
    decisions: list[tuple[dict, str]], config: dict | None = None
) -> tuple[str, str]:
    """Read gate state once for every hook, because a hook that judges findings on its own makes observe mean two things."""
    blocking = [finding for finding, outcome in decisions if outcome == "block"]
    if blocking:
        return "block", compact_block(blocking, config)[0]
    must_fix = [finding for finding, outcome in decisions if outcome == "must_fix"]
    if must_fix:
        return "must_fix", compact_block(must_fix, config, lead=MUST_FIX_LEAD)[0]
    observed = [finding for finding, outcome in decisions if outcome == "would_block"]
    if not observed:
        return "release", ""
    return "observe", compact_block(observed, config, lead=OBSERVE_LEAD)[0]


def correction_notice(changes: list[dict], flagged: list[dict], config=None) -> str:
    """Render changed and unresolved findings as one forceful, itemized correction checklist."""
    tagged_flagged = [
        item if item.get("status") else {**item, "status": "flagged"}
        for item in flagged
    ]
    return compact_block([*changes, *tagged_flagged], config, lead=MUST_FIX_LEAD)[0]


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


def _report_dir(transcript_path: str) -> Path | None:
    if not transcript_path:
        return None
    return Path(transcript_path).resolve().parent / TOOL_USE_REPORT_DIRNAME


def tool_use_report_path(transcript_path: str, session_id: str, tool_use_id: str) -> Path | None:
    """Key the filename by session and tool_use_id so parallel tool calls never collide."""
    directory = _report_dir(transcript_path)
    if directory is None or not session_id or not tool_use_id:
        return None
    digest = hashlib.sha256(f"{session_id}:{tool_use_id}".encode("utf-8")).hexdigest()
    return directory / f"{digest}.json"


def _bounded(value: object, cap: int) -> str:
    return str(value if value is not None else "")[:cap]


def _bounded_unresolved(rows: list[dict]) -> list[dict]:
    return [
        {
            "path": _bounded(row.get("path"), 300),
            "line": row.get("line") if isinstance(row.get("line"), int) else 0,
            "rule": _bounded(row.get("rule"), 80),
            "snippet": _bounded(row.get("snippet"), 300),
            "nearby": _bounded(row.get("nearby", row.get("detail")), 300),
        }
        for row in rows[:TOOL_USE_REPORT_MAX_UNRESOLVED]
    ]


def _ambiguous_matches(unresolved: list[dict]) -> dict[str, dict] | None:
    candidates = [
        {"id": str(index), "text": row.get("snippet") or row.get("detail") or ""}
        for index, row in enumerate(unresolved)
        if row.get("rule") in AMBIGUOUS_COMMENT_RULES
    ]
    if not candidates:
        return None
    return embeddings.enrich(candidates, _comment_prototypes())


def _tool_use_report_body(
    target_path: str, tool_name: str, cleanup_counts: dict, unresolved: list[dict]
) -> dict:
    bounded_unresolved = _bounded_unresolved(unresolved)
    body = {
        "protocol_version": TOOL_USE_REPORT_PROTOCOL_VERSION,
        "prototype_version": embeddings.PROTOTYPE_VERSION,
        "ts": now_iso(),
        "target_path": _bounded(target_path, 500),
        "tool_name": _bounded(tool_name, 40),
        "cleanup_counts": {
            str(key): value for key, value in (cleanup_counts or {}).items()
            if isinstance(value, int) and not isinstance(value, bool)
        },
        "unresolved": bounded_unresolved,
    }
    matches = _ambiguous_matches(bounded_unresolved)
    if matches:
        body["embedding_matches"] = matches
    return body


def _serialize_bounded(body: dict) -> str:
    raw = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= TOOL_USE_REPORT_MAX_BYTES:
        return raw
    body.pop("embedding_matches", None)
    body["unresolved"] = body["unresolved"][:3]
    return json.dumps(body, ensure_ascii=True, separators=(",", ":"))


def _write_report_file(path: Path, raw: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.chmod(path, 0o600)
    except OSError:
        return False
    return True


def write_tool_use_report(
    *,
    transcript_path: str,
    session_id: str,
    tool_use_id: str,
    target_path: str,
    tool_name: str,
    cleanup_counts: dict | None = None,
    unresolved: list[dict] | None = None,
) -> str | None:
    """Write one mode-0600 report the Haiku reviewer can read, returning None when it cannot be placed safely."""
    path = tool_use_report_path(transcript_path, session_id, tool_use_id)
    if path is None:
        return None
    body = _tool_use_report_body(target_path, tool_name, cleanup_counts or {}, unresolved or [])
    raw = _serialize_bounded(body)
    return str(path) if _write_report_file(path, raw) else None


def read_tool_use_report(transcript_path: str, session_id: str, tool_use_id: str) -> dict | None:
    path = tool_use_report_path(transcript_path, session_id, tool_use_id)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sweep_tool_use_reports(
    transcript_path: str,
    max_age_seconds: float = TOOL_USE_REPORT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> int:
    """Remove report files older than the cutoff, run at SessionStart and again on later pre-tool calls."""
    directory = _report_dir(transcript_path)
    if directory is None or not directory.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        try:
            stale = entry.stat().st_mtime < cutoff
        except OSError:
            continue
        if stale:
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _default_ledger_root() -> Path:
    return session_state.plugin_data_home() / "ledger"


def _ledger_dir(root: str | os.PathLike[str] | None) -> Path:
    return Path(root) if root is not None else _default_ledger_root()


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


def _read_jsonl(filename: str, root: str | os.PathLike[str] | None = None) -> list[dict]:
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
