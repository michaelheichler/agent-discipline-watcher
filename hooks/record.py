"""PostToolUse edit journal and scan gate."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

from failure import _config_roots, normalize_payload, record_success
from lib import blocker_state, payloads, scan_input
from lib.config import effective_config, effective_hook_config
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
from lib.scanner import read_scannable, scan_all

UNDECIDABLE_KEY = "<record-error>"
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this edit. Treat the turn as unscanned and rerun the check "
    "after repairing the gate config. Cause: "
)


def edited_paths(payload: object) -> list[str]:
    """Return edited paths from the central exact-type event projection."""
    return list(payloads.edited_paths(payload))


def _journal_edits(
    payload: RecordPayload,
    paths: list[str],
    root: str | Path | None,
    turn_id: str = "",
) -> None:
    stamp = now_iso()
    for path in paths:
        append_row(
            {
                "ts": stamp,
                "session_id": payload["session_id"],
                "hook": "record",
                "event": "edit",
                "family": "",
                "rule": "",
                "path": path,
                "tool": payload["tool_name"],
                "tool_use_id": payload["tool_use_id"],
                "turn_id": turn_id,
                "outcome": "",
            },
            root,
        )


def _stamped(findings: list[dict], path: Path) -> list[dict]:
    """Stamp the resolved path onto each finding, because the scanner works from text and the report names files."""
    return [{**finding, "path": str(path)} for finding in findings]


def _scan_paths(paths: list[str], cwd: Path, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Scan each edited path and return the owned and inherited findings apart, since only the first may block."""
    owned_rows: list[dict] = []
    inherited_rows: list[dict] = []
    for raw_path in paths:
        path = payloads.resolved_path(raw_path, cwd)
        if not path.exists() or not path.is_file():
            continue
        text = read_scannable(path, cfg)
        if text is None:
            owned_rows.extend(_stamped(scan_input.fallback_findings(path), path))
            continue
        owned, inherited = split_committed(path, scan_all(str(path), text, cfg), cfg)
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


def _response(kind: str, message: str, inherited: list[dict], cfg: dict) -> dict:
    """Block enforced findings after a post-write scan without mutating the file."""
    notice = inherited_advice(inherited, cfg)
    content = "\n".join(part for part in (message, notice) if part)
    if kind == "block":
        return {"decision": "block", "reason": content}
    return advise(content, "PostToolUse") if content else {}


def _clear_blocker_state(
    session_id: str, agent_id: str, tracked_paths: list[str], cfg: dict, kind: str, reason: str,
) -> None:
    blocker_state.touch_paths(session_id, agent_id, tracked_paths, cfg.get("state_root"))
    for path in tracked_paths:
        if kind == "block":
            blocker_state.set_pending(session_id, agent_id, path, reason, cfg.get("state_root"))
        else:
            blocker_state.clear_pending(session_id, agent_id, path, cfg.get("state_root"))
    blocker_state.clear_pending(session_id, agent_id, UNDECIDABLE_KEY, cfg.get("state_root"))


def _gate_for(projected: RecordPayload, paths: list[str], tracked_paths: list[str], cwd: Path, cfg: dict, ledger_root, agent_id: str) -> Callable[[str], dict]:

    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        if projected["session_id"]:
            _journal_edits(projected, paths, ledger_root, turn_id)
        owned, inherited = _scan_paths(paths, cwd, cfg)
        decisions = record_findings(
            session_id=projected["session_id"], hook="record",
            event="PostToolUse", findings=owned, turn_id=turn_id,
            tool_use_id=projected["tool_use_id"],
            duration_ms=int((time.monotonic() - started) * 1000),
            root=ledger_root, config=cfg,
        )
        report_cfg = {**cfg, "session_id": projected["session_id"], "turn_id": turn_id}
        kind, reason = verdict_message(decisions, report_cfg)
        response = _response(kind, reason, inherited, report_cfg)
        if projected["session_id"]:
            _clear_blocker_state(projected["session_id"], agent_id, tracked_paths, cfg, kind, reason)
        return response

    return gate


def _run_record(payload: dict, config: dict | None) -> dict:
    projected = _projected_payload(payload)
    trusted_config = exact_string_dict(config)
    state_root, ledger_root = _config_roots(trusted_config)
    cwd_text = projected["cwd"]
    cfg = effective_config(_scan_config(trusted_config), cwd_text or None)
    cfg["state_root"] = state_root
    if projected["session_id"]:
        cfg["session_id"] = projected["session_id"]
        _note_success(projected, trusted_config)
    cwd = Path(cwd_text or ".")
    paths = list(payloads.edited_paths(payload))
    tracked_paths = [str(payloads.resolved_path(raw_path, cwd)) for raw_path in paths]
    agent_id = payloads.agent_id(payload)
    return run_with_ledger(
        hook="record",
        payload=dict(projected),
        gate=_gate_for(projected, paths, tracked_paths, cwd, cfg, ledger_root, agent_id),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def run(payload: dict, config: dict | None = None) -> dict:
    """Block on failure here, mirroring batch.py, because returning {} let a broken gate silently release the turn."""
    try:
        return _run_record(payload, config)
    except Exception as exc:
        reason = UNDECIDABLE + str(exc)
        session_id = payloads.session_id(payload)
        if session_id:
            root = effective_hook_config(config, payloads.cwd(payload) or None).get("state_root")
            try:
                blocker_state.set_pending(
                    session_id, blocker_state.scope(payload), UNDECIDABLE_KEY, reason, root,
                )
            except Exception as state_exc:
                sys.stderr.write(f"agent-discipline-watcher: blocker state update failed: {state_exc}\n")
        return {"decision": "block", "reason": reason}


if __name__ == "__main__":
    write_payload(claude_feedback_response(run(read_payload()), "PostToolUse"))
