from __future__ import annotations

import re
import time
from pathlib import Path

from lib.baseline import split_committed
from lib.config import effective_config
from lib.hookio import advise, allow, deny, read_payload, write_payload
from lib.protected import path_findings
from lib.reporting import inherited_advice, record_findings, run_with_ledger, verdict_message
from lib.scanner import scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this write and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)


def _tool_input(payload: dict) -> dict:
    value = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    return value if isinstance(value, dict) else {}


def pending_writes(payload: dict) -> list[tuple[str, str]]:
    tool_input = _tool_input(payload)
    path = tool_input.get("file_path") or tool_input.get("path") or "<pending>"
    if "content" in tool_input:
        return [(path, str(tool_input.get("content") or ""))]
    if "new_string" in tool_input:
        return [(path, str(tool_input.get("new_string") or ""))]
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return [(path, "\n".join(str(edit.get("new_string", "")) for edit in edits if isinstance(edit, dict)))]
    patch = tool_input.get("patch") or tool_input.get("command") or tool_input.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    if isinstance(patch, str) and patch:
        split = split_patch(patch)
        return split if split else [(path, patch)]
    return []


def split_patch(patch: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    current = ""
    lines: list[str] = []
    for line in patch.splitlines():
        match = PATCH_FILE.match(line)
        if match:
            if current and lines:
                rows.append((current, "\n".join(lines)))
            current = match.group(1).strip().strip('"')
            lines = []
            continue
        if current and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if current and lines:
        rows.append((current, "\n".join(lines)))
    return rows


def run(payload: dict, config: dict | None = None) -> dict:
    """Scan a pending write, blocking rather than passing the call through when the gate itself cannot decide."""
    try:
        return _run(payload, config)
    except Exception as exc:
        return deny(UNDECIDABLE + str(exc))


def _run(payload: dict, config: dict | None) -> dict:
    cfg = effective_config(config, payload.get("cwd") or None)
    return run_with_ledger(
        hook="pre_write",
        payload=payload,
        gate=lambda turn_id: _gate(payload, cfg, turn_id),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _gate(payload: dict, cfg: dict, turn_id: str) -> dict:
    started = time.monotonic()
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    findings, inherited = _pending_findings(payload, cfg)
    if not findings and not inherited:
        return allow()
    decisions = record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_write",
        event="PreToolUse", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=cfg.get("ledger_root"), config=cfg,
    )
    return _verdict(decisions, inherited, cfg)


def _verdict(decisions: list[tuple[dict, str]], inherited: list[dict], cfg: dict) -> dict:
    """Deny on an enforced finding, otherwise report so the agent must weigh the rest before moving on."""
    kind, message = verdict_message(decisions, cfg)
    joined = "\n".join(part for part in (message, inherited_advice(inherited, cfg)) if part)
    if kind == "block":
        return deny(joined)
    return advise(joined, "PreToolUse") if joined else allow()


def _stamped(findings: list[dict], path: str) -> list[dict]:
    """Stamp the target path onto each finding, because the scanner works from text and the report names files."""
    return [{**finding, "path": path} for finding in findings]


def _pending_findings(payload: dict, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Split whole-file content against its committed version, because only Write carries debt the edit did not create."""
    whole_file = "content" in _tool_input(payload)
    owned_rows: list[dict] = []
    inherited_rows: list[dict] = []
    for path, text in pending_writes(payload):
        owned_rows.extend(_stamped(path_findings(path, cfg, content=text), path))
        scanned = _stamped(scan_all(path, text, cfg), path)
        if not whole_file:
            owned_rows.extend(scanned)
            continue
        owned, inherited = split_committed(Path(path), scanned, cfg)
        owned_rows.extend(owned)
        inherited_rows.extend(inherited)
    return owned_rows, inherited_rows


if __name__ == "__main__":
    write_payload(run(read_payload()))
