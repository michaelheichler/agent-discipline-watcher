"""PostToolUse edit journal and scan gate."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from failure import _config_roots, normalize_payload, record_success
from lib.config import effective_config
from lib.hookio import read_payload, write_payload
from lib.payloads import RecordPayload, exact_string_dict, record_payload
from lib.reporting import append_row, compact_block, now_iso, run_with_ledger
from lib.scanner import read_scannable, scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)


def _edited_paths(payload: RecordPayload) -> list[str]:
    path = payload["file_path"]
    if path:
        return [path]
    return [
        match.strip().strip('"') for match in PATCH_FILE.findall(payload["edit_text"])
    ]


def edited_paths(payload: object) -> list[str]:
    """Return edited paths from the central exact-type event projection."""
    return _edited_paths(record_payload(payload))


def _journal_edits(
    payload: RecordPayload,
    paths: list[str],
    root: str | Path | None,
    turn_id: str = "",
) -> None:
    """Record one journal row per edited path, swallowing write errors."""
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


def _scan_paths(paths: list[str], cwd: Path, cfg: dict) -> list[dict]:
    """Scan each edited path and return findings."""
    findings = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = cwd / path
        if not path.exists() or not path.is_file():
            continue
        text = read_scannable(path, cfg)
        if text is None:
            continue
        for finding in scan_all(str(path), text, cfg):
            item = dict(finding)
            item["path"] = str(path)
            findings.append(item)
    return findings


def _run_record(payload: dict, config: dict | None) -> dict:
    """Run the record hook after its public fail-safe boundary."""
    projected = record_payload(payload)
    identity = normalize_payload(payload)
    projected["session_id"] = identity["session_id"]
    projected["cwd"] = identity["cwd"]
    projected["tool_name"] = identity["tool_name"]
    projected["tool_use_id"] = identity["tool_use_id"]
    trusted_config = exact_string_dict(config)
    state_root, ledger_root = _config_roots(trusted_config)
    scan_config = dict(trusted_config)
    scan_config.pop("state_root", None)
    scan_config.pop("ledger_root", None)
    cwd_text = projected["cwd"]
    try:
        cfg = effective_config(scan_config, cwd_text or None)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError):
        cfg = effective_config(scan_config, None)
    if projected["session_id"]:
        cfg["session_id"] = projected["session_id"]
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
    cwd = Path(cwd_text or ".")
    paths = _edited_paths(projected)

    def gate(turn_id: str) -> dict:
        if projected["session_id"]:
            _journal_edits(projected, paths, ledger_root, turn_id)
        findings = _scan_paths(paths, cwd, cfg)
        if findings:
            reason, _ = compact_block(findings, cfg)
            return {"decision": "block", "reason": reason}
        return {}

    return run_with_ledger(
        hook="record",
        payload=dict(projected),
        gate=gate,
        ledger_root=ledger_root,
        state_root=state_root,
    )


def run(payload: dict, config: dict | None = None) -> dict:
    """Scan edited paths, persisting only for one validated session identity."""
    try:
        return _run_record(payload, config)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: record hook failed: {exc}\n")
        return {}


if __name__ == "__main__":
    payload = read_payload()
    response = run(payload)
    if response.get("decision") == "block":
        sys.stderr.write(response["reason"] + "\n")
        raise SystemExit(2)
    write_payload(response)
