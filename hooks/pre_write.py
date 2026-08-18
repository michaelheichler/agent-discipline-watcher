from __future__ import annotations

import re
import time
from pathlib import Path
from typing import NamedTuple

from lib.baseline import changed_lines, partition, split_committed
from lib.config import effective_hook_config
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.protected import path_findings
from lib.reporting import (
    inherited_advice, record_findings, run_with_ledger, verdict_message,
)
from lib.scanner import scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s+(.+)$", re.MULTILINE)


def _tool_input(payload: dict) -> dict:
    value = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    return value if isinstance(value, dict) else {}


class PendingWrite(NamedTuple):
    """The tool_input shape decoded once, since Write, Edit, MultiEdit, NotebookEdit, and apply_patch each name their content differently."""
    tool_input: dict
    path: str
    is_edit: bool
    edits: list[dict]
    notebook_source: str | None


def _decode(tool_input: dict) -> PendingWrite:
    path = str(
        tool_input.get("file_path") or tool_input.get("path")
        or tool_input.get("notebook_path") or "<pending>"
    )
    is_edit = (
        "new_string" in tool_input or "new_source" in tool_input
        or isinstance(tool_input.get("edits"), list)
    )
    edits: list[dict] = []
    if "new_string" in tool_input:
        edits = [tool_input]
    elif isinstance(tool_input.get("edits"), list):
        edits = [edit for edit in tool_input["edits"] if isinstance(edit, dict)]
    notebook_source = str(tool_input.get("new_source") or "") if "new_source" in tool_input else None
    return PendingWrite(tool_input, path, is_edit, edits, notebook_source)


def pending_writes(decoded: PendingWrite) -> list[tuple[str, str]]:
    tool_input = decoded.tool_input
    if "content" in tool_input:
        return [(decoded.path, str(tool_input.get("content") or ""))]
    if decoded.edits:
        return [(decoded.path, "\n".join(str(edit.get("new_string") or "") for edit in decoded.edits))]
    if decoded.notebook_source is not None:
        return [(decoded.path, decoded.notebook_source)]
    patch = tool_input.get("patch") or tool_input.get("command") or tool_input.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    if isinstance(patch, str) and patch:
        split = split_patch(patch)
        return split if split else [(decoded.path, patch)]
    return []


def split_patch(patch: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    current = ""
    lines: list[str] = []
    for line in patch.splitlines():
        match = PATCH_FILE.match(line)
        if match:
            if current:
                rows.append((current, "\n".join(lines)))
            current = match.group(1).strip().strip('"')
            lines = []
            continue
        if current and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if current:
        rows.append((current, "\n".join(lines)))
    return rows


def run(payload: dict, config: dict | None = None) -> dict:
    """Blocks rather than passes a pending write through on error, because a gate that cannot decide must fail closed, not silently allow."""
    return fail_closed("write", lambda: _checked_run(payload, config))


def _checked_run(payload: dict, config: dict | None) -> dict:
    if payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    return _run(payload, config)


def _run(payload: dict, config: dict | None) -> dict:
    cfg = effective_hook_config(config, payload.get("cwd") or None)
    return run_with_ledger(
        hook="pre_write",
        payload=payload,
        gate=lambda turn_id: _gate(payload, cfg, turn_id),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _unique_findings(findings: list[dict]) -> list[dict]:
    seen: set[tuple[object, ...]] = set()
    result: list[dict] = []
    for finding in findings:
        key = (finding.get("rule"), finding.get("path"), finding.get("line"))
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def _record(payload: dict, cfg: dict, turn_id: str, findings: list[dict], started: float):
    return record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_write",
        event="PreToolUse", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=cfg.get("ledger_root"), config=cfg,
    )


def _gate(payload: dict, cfg: dict, turn_id: str) -> dict:
    started = time.monotonic()
    decoded = _decode(_tool_input(payload))
    cwd = Path(payload.get("cwd") or ".")
    findings, inherited = _pending_findings(decoded, cwd, cfg)
    findings = _unique_findings(findings)
    decisions = _record(payload, cfg, turn_id, findings, started) if findings else []
    kind, message = verdict_message(decisions, cfg)
    if kind == "block":
        return deny(message)
    notice = inherited_advice(inherited, cfg)
    if kind == "observe":
        return advise("\n".join(part for part in (message, notice) if part), "PreToolUse")
    return {"systemMessage": notice} if notice else allow()


def _stamped(findings: list[dict], path: str) -> list[dict]:
    """Stamp the target path onto each finding, because the scanner works from text and the report names files."""
    return [{**finding, "path": path} for finding in findings]


def _label_pending_text(findings: list[dict]) -> list[dict]:
    return [
        {**finding, "detail": finding["detail"] + " (line " + str(finding["line"]) + " of pending edit text)"}
        for finding in findings
    ]


def _pending_edit_text(decoded: PendingWrite) -> str:
    if decoded.notebook_source is not None:
        return decoded.notebook_source
    return "\n".join(str(edit.get("new_string") or "") for edit in decoded.edits)


def _apply_edits(decoded: PendingWrite, path: str) -> tuple[str, str] | None:
    if not decoded.edits:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    try:
        before = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    after = before
    for edit in decoded.edits:
        old = str(edit.get("old_string") or "")
        new = str(edit.get("new_string") or "")
        if not old or old not in after:
            return None
        count = -1 if edit.get("replace_all") else 1
        after = after.replace(old, new, count)
    return before, after


def _edit_findings(decoded: PendingWrite, resolved_path: Path, cfg: dict) -> list[dict]:
    scan_path = str(resolved_path)
    applied = _apply_edits(decoded, scan_path)
    if applied is None:
        pending = _pending_edit_text(decoded)
        return _label_pending_text(_stamped(scan_all(decoded.path, pending, cfg), decoded.path))
    before, after = applied
    changed = changed_lines(before, after)
    findings = scan_all(scan_path, after, cfg)
    inherited = scan_all(scan_path, before, cfg)
    owned, _ = partition(findings, inherited)
    owned_ids = {id(finding) for finding in owned}
    return _stamped(
        [finding for finding in findings if finding.get("line") in changed or id(finding) in owned_ids],
        decoded.path,
    )


def _edit_shape_findings(decoded: PendingWrite, cwd: Path, cfg: dict) -> list[dict]:
    resolved_path = _resolved_path(decoded.path, cwd)
    protected = _stamped(
        path_findings(str(resolved_path), cfg, content=_pending_edit_text(decoded)), decoded.path
    )
    return protected + _edit_findings(decoded, resolved_path, cfg)


def _write_shape_findings(decoded: PendingWrite, cwd: Path, cfg: dict) -> tuple[list[dict], list[dict]]:
    whole_file = "content" in decoded.tool_input
    owned_rows: list[dict] = []
    inherited_rows: list[dict] = []
    for path, text in pending_writes(decoded):
        owned_rows.extend(_stamped(path_findings(path, cfg, content=text), path))
        scanned = _stamped(scan_all(path, text, cfg), path)
        if not whole_file:
            owned_rows.extend(_label_pending_text(scanned))
            continue
        resolved_path = _resolved_path(path, cwd)
        owned, inherited = split_committed(resolved_path, scanned, cfg)
        owned_rows.extend(owned)
        inherited_rows.extend(inherited)
    return owned_rows, inherited_rows


def _pending_findings(decoded: PendingWrite, cwd: Path, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Split whole-file content against its committed version, because only Write carries debt the edit did not create."""
    if decoded.is_edit:
        return _edit_shape_findings(decoded, cwd, cfg), []
    return _write_shape_findings(decoded, cwd, cfg)


def _resolved_path(path: str, cwd: Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else cwd / candidate


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
