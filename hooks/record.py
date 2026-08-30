from __future__ import annotations

import os
import stat
import sys
import time
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import cast

from failure import _config_roots, normalize_payload, record_success
from lib import blocker_state, journal, payloads, scan_input
from lib.config import effective_config, effective_hook_config
from lib.findings import Finding, VerdictKind
from lib.hookio import advise, claude_feedback_response, read_payload, write_payload
from lib.payloads import RecordPayload, exact_string_dict, record_payload
from lib.baseline import split_committed
from lib.reporting import (
    append_row,
    inherited_advice,
    now_iso,
    record_findings,
    run_with_ledger,
    verdict_message,
)
from lib.scanner import scan_all

UNDECIDABLE_KEY = "<record-error>"
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this edit. Treat the turn as unscanned and rerun the check "
    "after repairing the gate config. Cause: "
)


@dataclass(frozen=True, slots=True)
class _RecordVerdict:
    kind: VerdictKind
    reason: str


@dataclass(frozen=True, slots=True)
class _EditJournal:
    payload: RecordPayload
    paths: list[str]
    root: str | Path | None
    state_root: str | Path | None


@dataclass(frozen=True, slots=True)
class _RecordGateContext:
    journal: _EditJournal
    tracked_paths: list[str]
    cwd: Path
    config: dict
    blocker_scope: blocker_state.BlockerScope


def edited_paths(payload: object) -> list[str]:
    return list(payloads.edited_paths(payload))


def _journal_edits(edits: _EditJournal, turn_id: str = "") -> None:
    stamp = now_iso()
    for path in edits.paths:
        append_row(
            {
                "ts": stamp,
                "session_id": edits.payload["session_id"],
                "hook": "record",
                "event": "edit",
                "family": "",
                "rule": "",
                "path": path,
                "tool": edits.payload["tool_name"],
                "tool_use_id": edits.payload["tool_use_id"],
                "turn_id": turn_id,
                "outcome": "",
            },
            edits.root,
        )
        if edits.payload["session_id"]:
            try:
                journal.record_edit(
                    edits.payload["session_id"], turn_id,
                    edits.payload["tool_use_id"],
                    payloads.resolved_path(path, Path(edits.payload["cwd"] or ".")),
                    state_root=edits.state_root,
                )
            except Exception as exc:
                sys.stderr.write(f"agent-discipline-watcher: candidate journal append failed: {exc}\n")


def _stamped(findings: list[dict], path: Path, content_hash: str | None = None) -> list[dict]:
    """Stamp the resolved path onto each finding, because the scanner works from text and the report names files."""
    stamped = []
    for finding in findings:
        item = Finding.from_dict(finding).with_path(str(path))
        stamped.append(item.with_content_hash(content_hash) if content_hash else item)
    return stamped




_MAX_OPEN_SCAN_BYTES = 1_000_000

def _approved_path(raw_path: object, cwd: Path) -> tuple[Path, tuple[int, int]] | None:
    """Resolve a candidate under cwd and capture its device and inode before opening it."""
    if not isinstance(raw_path, str):
        return None
    candidate_text = raw_path.strip()
    if not candidate_text or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate_text):
        return None
    try:
        root = cwd.expanduser().resolve(strict=True)
        path = payloads.resolved_path(candidate_text, cwd).resolve(strict=True)
        path.relative_to(root)
        metadata = path.stat()
    except (OSError, RuntimeError, ValueError):
        return None
    if not stat.S_ISREG(metadata.st_mode):
        return None
    return path, (metadata.st_dev, metadata.st_ino)

def _held_fallback(descriptor: int, path: Path) -> list[dict]:
    """Build a fallback finding from the approved descriptor without reopening the pathname."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            result = scan_input._count_open_file_lines(stream)
    except (OSError, ValueError):
        result = None
    if result is None:
        return scan_input.fallback_findings_from_count(path, 0, capped=False)
    count, capped = result
    return scan_input.fallback_findings_from_count(path, count, capped)

def _scan_open_file(
    path: Path, identity: tuple[int, int], cfg: dict
) -> tuple[list[dict], list[dict]] | None:
    """Read and scan bytes from the descriptor whose inode was approved."""
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != identity or not stat.S_ISREG(metadata.st_mode):
            return None
        limit = min(
            _MAX_OPEN_SCAN_BYTES,
            max(0, scan_input.int_setting(cfg, "max_scan_bytes", "ADW_MAX_SCAN_BYTES", _MAX_OPEN_SCAN_BYTES)),
        )
        raw = os.read(descriptor, limit + 1)
        if len(raw) > limit or b"\0" in raw[:8192]:
            return _held_fallback(descriptor, path), []
        text = raw.decode("utf-8", errors="replace")
        return split_committed(path, scan_all(str(path), text, cfg), cfg)
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _scan_paths(paths: list[str], cwd: Path, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Scan only regular files inside cwd from an inode-checked descriptor."""
    owned_rows: list[dict] = []
    inherited_rows: list[dict] = []
    for raw_path in paths:
        approved = _approved_path(raw_path, cwd)
        if approved is None:
            owned_rows.extend(scan_input.fallback_findings_from_count(Path(raw_path), 0, capped=False))
            continue
        path, identity = approved
        scanned = _scan_open_file(path, identity, cfg)
        if scanned is None:
            owned_rows.extend(scan_input.fallback_findings_from_count(path, 0, capped=False))
            continue
        owned, inherited = scanned
        owned_rows.extend(_stamped(owned, path))
        inherited_rows.extend(_stamped(inherited, path))
    return owned_rows, inherited_rows


def _projected_payload(payload: dict) -> RecordPayload:
    projected = record_payload(payload)
    identity = normalize_payload(payload)
    for field in ("session_id", "cwd", "tool_name", "tool_use_id"):
        projected[field] = identity[field]
    return projected


def _scan_config(trusted_config: dict) -> dict:
    """Strip the storage roots, because they steer the ledger rather than the scan."""
    scan_config = dict(trusted_config)
    scan_config.pop("state_root", None)
    scan_config.pop("ledger_root", None)
    return scan_config


def _note_success(projected: RecordPayload, trusted_config: dict) -> None:
    record_success(
        {
            "session_id": projected["session_id"],
            "cwd": projected["cwd"],
            "tool_name": projected["tool_name"],
            "tool_use_id": projected["tool_use_id"],
            "tool_input": {"file_path": projected["file_path"]},
        },
        trusted_config,
    )


def _response(
    verdict: _RecordVerdict, inherited: list[dict], cfg: dict
) -> dict:
    """Report findings without rewriting the file because PostToolUse cannot safely roll back a completed edit."""
    notice = inherited_advice(inherited, cfg)
    content = "\n".join(part for part in (verdict.reason, notice) if part)
    if verdict.kind == "block":
        return {"decision": "block", "reason": content}
    return advise(content, "PostToolUse") if content else {}


def _clear_blocker_state(
    scope: blocker_state.BlockerScope,
    tracked_paths: list[str],
    verdict: _RecordVerdict,
) -> None:
    """Leaves UNDECIDABLE_KEY untouched, because an unrelated edit succeeding is not evidence the earlier unscanned write was safe, and only Stop-time reconciliation of that specific failure may release it."""
    blocker_state.touch_paths(scope, tracked_paths)
    for path in tracked_paths:
        if verdict.kind == VerdictKind.BLOCK:
            blocker_state.set_pending(scope, path, verdict.reason)
        else:
            blocker_state.clear_pending(scope, path)


def _gate_for(context: _RecordGateContext) -> Callable[[str], dict]:
    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        projected = context.journal.payload
        if projected["session_id"]:
            _journal_edits(context.journal, turn_id)
        owned, inherited = _scan_paths(
            context.journal.paths, context.cwd, context.config
        )
        decisions = record_findings(
            session_id=projected["session_id"], hook="record",
            event="PostToolUse", findings=owned, turn_id=turn_id,
            tool_use_id=projected["tool_use_id"],
            duration_ms=int((time.monotonic() - started) * 1000),
            root=context.journal.root, config=context.config,
        )
        report_cfg = {
            **context.config,
            "session_id": projected["session_id"],
            "turn_id": turn_id,
        }
        kind, reason = verdict_message(decisions, report_cfg)
        verdict = _RecordVerdict(VerdictKind(kind), reason)
        response = _response(verdict, inherited, report_cfg)
        if projected["session_id"]:
            _clear_blocker_state(context.blocker_scope, context.tracked_paths, verdict)
        return response

    return gate


def _run_record(payload: dict, config: dict | None) -> dict:
    projected = _projected_payload(payload)
    trusted_config = exact_string_dict(config)
    roots = _config_roots(trusted_config)
    state_root = cast(str | Path | None, roots.state)
    ledger_root = cast(str | Path | None, roots.ledger)
    cwd_text = projected["cwd"]
    cfg = effective_config(_scan_config(trusted_config), cwd_text or None)
    cfg["state_root"] = state_root
    if projected["session_id"]:
        cfg["session_id"] = projected["session_id"]
        _note_success(projected, trusted_config)
    gate_context = _gate_context_for(payload, projected, cfg, state_root, ledger_root)
    return run_with_ledger(
        hook="record",
        payload=dict(projected),
        gate=_gate_for(gate_context),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def _gate_context_for(
    payload: dict,
    projected: RecordPayload,
    cfg: dict,
    state_root: str | Path | None,
    ledger_root: str | Path | None,
)-> _RecordGateContext:
    if not projected["cwd"]:
        raise ValueError("PostToolUse payload requires a trusted cwd")
    cwd = Path(projected["cwd"])
    paths = list(payloads.edited_paths(payload))
    return _RecordGateContext(
        journal=_EditJournal(projected, paths, ledger_root, state_root),
        tracked_paths=[str(payloads.resolved_path(raw, cwd)) for raw in paths],
        cwd=cwd,
        config=cfg,
        blocker_scope=blocker_state.BlockerScope(
            projected["session_id"], payloads.agent_id(payload), state_root
        ),
    )


def _record_undecidable_blocker(
    payload: dict, config: dict | None, reason: str
) -> None:
    session_id = payloads.session_id(payload)
    if not session_id:
        return
    try:
        root = effective_hook_config(config, payloads.cwd(payload) or None).get("state_root")
        blocker_state.set_pending(
            session_id, blocker_state.scope(payload), UNDECIDABLE_KEY, reason, root,
        )
    except Exception as state_exc:
        sys.stderr.write(f"agent-discipline-watcher: blocker state update failed: {state_exc}\n")


def run(payload: dict, config: dict | None = None) -> dict:
    """Block on failure here, mirroring batch.py, because returning {} let a broken gate silently release the turn."""
    try:
        return _run_record(payload, config)
    except Exception as exc:
        reason = UNDECIDABLE + str(exc)
        _record_undecidable_blocker(payload, config, reason)
        return {"decision": "block", "reason": reason}


if __name__ == "__main__":
    write_payload(claude_feedback_response(run(read_payload()), "PostToolUse"))
