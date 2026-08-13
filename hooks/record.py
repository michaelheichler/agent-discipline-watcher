"""PostToolUse edit journal and scan gate."""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

from failure import _config_roots, normalize_payload, record_success
import pre_bash
from lib import adjudication
from lib.config import effective_config
from lib.hookio import advise, read_payload, write_payload
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

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)


def _edited_paths(payload: RecordPayload) -> list[str]:
    paths: list[str] = []
    path = payload["file_path"]
    if path:
        paths.append(path)
    else:
        paths.extend(
            match.strip().strip('"') for match in PATCH_FILE.findall(payload["edit_text"])
        )
    if payload["tool_name"] == "Bash":
        paths.extend(pre_bash.write_paths(payload["edit_text"]))
    return paths


def edited_paths(payload: object) -> list[str]:
    """Return edited paths from the central exact-type event projection."""
    return _edited_paths(record_payload(payload))


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
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = cwd / path
        if not path.exists() or not path.is_file():
            continue
        text = read_scannable(path, cfg)
        if text is None:
            continue
        owned, inherited = split_committed(path, scan_all(str(path), text, cfg), cfg)
        owned = adjudication.filter_cached_releases(
            owned,
            text,
            str(cfg.get("session_id") or ""),
            cfg.get("state_root"),
        )
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


def _resolved_config(scan_config: dict, cwd_text: str) -> dict:
    """Resolve project config, falling back to defaults so that an unreadable cwd never fails the hook."""
    try:
        return effective_config(scan_config, cwd_text or None)
    except Exception:
        return effective_config(scan_config, None)


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
    decisions: list[tuple[dict, str]],
    inherited: list[dict],
    cfg: dict,
) -> dict:
    """Block enforced findings after a post-write scan without mutating the file."""
    kind, message = verdict_message(decisions, cfg)
    notice = inherited_advice(inherited, cfg)
    content = "\n".join(part for part in (message, notice) if part)
    if kind == "block":
        return {"decision": "block", "reason": content}
    return advise(content, "PostToolUse") if content else {}


def _gate_for(projected: RecordPayload, paths: list[str], cwd: Path, cfg: dict, ledger_root) -> Callable[[str], dict]:

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
        return _response(decisions, inherited, cfg)

    return gate


def _run_record(payload: dict, config: dict | None) -> dict:
    projected = _projected_payload(payload)
    trusted_config = exact_string_dict(config)
    state_root, ledger_root = _config_roots(trusted_config)
    cwd_text = projected["cwd"]
    cfg = _resolved_config(_scan_config(trusted_config), cwd_text)
    cfg["state_root"] = state_root
    if projected["session_id"]:
        cfg["session_id"] = projected["session_id"]
        _note_success(projected, trusted_config)
    cwd = Path(cwd_text or ".")
    paths = _edited_paths(projected)
    return run_with_ledger(
        hook="record",
        payload=dict(projected),
        gate=_gate_for(projected, paths, cwd, cfg, ledger_root),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def run(payload: dict, config: dict | None = None) -> dict:
    """Scan edited paths, swallowing every exception class so that a broken config cannot take the hook process down."""
    try:
        return _run_record(payload, config)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: record hook failed: {exc}\n")
        return {}


if __name__ == "__main__":
    payload = read_payload()
    response = run(payload)
    if response.get("decision") == "block":
        sys.stderr.write(response["reason"] + "\n")
        raise SystemExit(2)
    write_payload(response)
