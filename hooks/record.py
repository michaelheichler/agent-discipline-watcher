"""PostToolUse edit journal and scan gate."""

from __future__ import annotations

import ast
import difflib
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

from failure import _config_roots, normalize_payload, record_success
import pre_bash
from lib import reporting
import lib.rewrite as rewrite
from lib.config import effective_config, resolve_outcome
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


WRITEBACK_LEAD = (
    "agent-discipline-watcher corrected this file after your write landed. "
    "This correction was not part of your tool call. The file on disk has changed:"
)


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
        owned_rows.extend(_stamped(owned, path))
        inherited_rows.extend(_stamped(inherited, path))
    return owned_rows, inherited_rows


def _writeback_line_map(
    before_lines: list[str], after_lines: list[str]
) -> dict[int, int | None]:
    line_map: dict[int, int | None] = {}
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "insert":
            continue
        for offset, old_index in enumerate(range(old_start, old_end)):
            if new_start == new_end:
                line_map[old_index] = None
            else:
                line_map[old_index] = min(new_start + offset, new_end - 1)
    return line_map


def _writeback_change_row(
    change: dict, before_lines: list[str], after_lines: list[str],
    line_map: dict[int, int | None], path: Path, families: dict[str, str],
) -> dict:
    row = {
        **change,
        "path": str(path),
        "family": families.get(str(change.get("rule") or ""), ""),
    }
    line = row.get("line")
    if isinstance(line, int) and 0 < line <= len(before_lines):
        old = before_lines[line - 1]
        if row.get("status") == "removed":
            new = "<removed>"
        else:
            after_index = line_map.get(line - 1)
            new = after_lines[after_index] if after_index is not None else "<not present>"
        action = str(row.get("action") or "Changed this line.")
        row["action"] = f"{action} Before: {old!r}; after: {new!r}."
    return row


def _writeback_change_rows(
    changes: list[dict], before: str, after: str, path: Path,
    families: dict[str, str] | None = None,
) -> list[dict]:
    """Attach the target and a small before/after audit trail to each applied change."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    line_map = _writeback_line_map(before_lines, after_lines)
    family_map = families or {}
    return [
        _writeback_change_row(change, before_lines, after_lines, line_map, path, family_map)
        for change in changes
    ]


def _original_changed_lines(before: str, after: str) -> set[int]:
    """Return original 1-based lines covered by non-equal rewrite opcodes."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    changed: set[int] = set()
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    for tag, old_start, old_end, _new_start, _new_end in matcher.get_opcodes():
        if tag != "equal":
            changed.update(index + 1 for index in range(old_start, old_end))
    return changed


def _inherited_line_numbers(inherited: list[dict], path_text: str) -> set[int]:
    lines: set[int] = set()
    for finding in inherited:
        if finding.get("path") != path_text:
            continue
        line = finding.get("line")
        if isinstance(line, int) and line > 0:
            lines.add(line)
    return lines


def _read_correction_text(
    path: Path, cfg: dict
) -> tuple[bool, str] | None:
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False, ""
    except OSError:
        return None
    text = read_scannable(path, cfg)
    return None if text is None else (True, text)


def _rewrite_and_validate(
    path_text: str, path: Path, text: str, cfg: dict
) -> rewrite.TextRewrite | None:
    try:
        rewritten = rewrite.rewrite_text(path_text, text, cfg)
    except Exception:
        return None
    if path.suffix.lower() == ".py":
        try:
            ast.parse(rewritten.text)
        except SyntaxError:
            return None
    return rewritten


def _writeback_content(
    text: str, rewritten: rewrite.TextRewrite, inherited_lines: set[int]
) -> str | None:
    if rewritten.text == text:
        return None
    if inherited_lines & _original_changed_lines(text, rewritten.text):
        return None
    return rewritten.text


def _write_path(path: Path, text: str) -> bool:
    try:
        path.write_text(text, encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return True


def _writeback_result(
    path: Path, text: str, rewritten: rewrite.TextRewrite,
    owned_path: list[dict], inherited_lines: set[int],
) -> tuple[list[dict], bool] | None:
    writeback_text = _writeback_content(text, rewritten, inherited_lines)
    if writeback_text is None:
        return [], False
    if not _write_path(path, writeback_text):
        return None
    families = {
        str(row.get("rule") or ""): str(row.get("family") or "")
        for row in owned_path
    }
    changes = _writeback_change_rows(
        rewritten.changes, text, writeback_text, path, families
    )
    return changes, True


def _declined_correction(flagged: list[dict]) -> dict:
    return {"changes": [], "flagged": flagged, "writeback": False}


def _must_fix_findings(findings: list[dict], path_text: str, cfg: dict) -> list[dict]:
    return [
        {**finding, "path": path_text}
        for finding in findings
        if resolve_outcome(finding, cfg) == "must_fix"
    ]


def _correct_path(
    path: Path, cfg: dict, owned_path: list[dict], inherited_lines: set[int]
) -> dict | None:
    path_text = str(path)
    owned_must_fix = _must_fix_findings(owned_path, path_text, cfg)
    if not owned_must_fix:
        return None
    source = _read_correction_text(path, cfg)
    if source is None:
        return None
    utf8, text = source
    if not utf8:
        return _declined_correction(owned_must_fix)
    rewritten = _rewrite_and_validate(path_text, path, text, cfg)
    if rewritten is None:
        return _declined_correction(owned_must_fix)
    result = _writeback_result(path, text, rewritten, owned_path, inherited_lines)
    if result is None:
        return _declined_correction(owned_must_fix)
    changes, writeback = result
    flagged = _must_fix_findings(rewritten.unresolved, path_text, cfg)
    if changes or flagged:
        return {"changes": changes, "flagged": flagged, "writeback": writeback}
    return None


def _correct_paths(
    paths: list[str], cwd: Path, cfg: dict, owned: list[dict], inherited: list[dict]
) -> list[dict]:
    """Apply safe second-tier cleanup to style findings that survived the write."""
    corrections: list[dict] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = cwd / path
        path_text = str(path)
        if path_text in seen:
            continue
        seen.add(path_text)
        owned_path = [row for row in owned if row.get("path") == path_text]
        inherited_lines = _inherited_line_numbers(inherited, path_text)
        correction = _correct_path(path, cfg, owned_path, inherited_lines)
        if correction is not None:
            corrections.append(correction)
    return corrections


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


def _joined(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def _correction_notice(
    corrections: list[dict], cfg: dict, decisions: list[tuple[dict, str]] | None = None
) -> str:
    changes = [row for correction in corrections for row in correction.get("changes", [])]
    flagged = [row for correction in corrections for row in correction.get("flagged", [])]
    covered = {
        (row.get("path"), row.get("line"), row.get("rule"))
        for row in [*changes, *flagged]
    }
    for finding, outcome in decisions or []:
        key = (finding.get("path"), finding.get("line"), finding.get("rule"))
        if outcome == "must_fix" and key not in covered:
            flagged.append(finding)
            covered.add(key)
    if not changes and not flagged:
        return ""
    itemized = reporting.correction_notice(changes, flagged, cfg)
    writeback = any(correction.get("writeback") for correction in corrections)
    return _joined(WRITEBACK_LEAD if writeback else "", itemized)


def _response_decision(
    kind: str, message: str, correction: str, notice: str
) -> tuple[str, str]:
    if kind == "block":
        return "block", _joined(message, correction, notice)
    if kind == "must_fix" and correction:
        return "advise", _joined(correction, notice)
    return "advise", _joined(message, notice)


def _response(
    decisions: list[tuple[dict, str]],
    inherited: list[dict],
    cfg: dict,
    corrections: list[dict] | None = None,
) -> dict:
    """Block only on a security finding, and report any post-write correction explicitly."""
    kind, message = verdict_message(decisions, cfg)
    correction = _correction_notice(corrections or [], cfg, decisions)
    notice = inherited_advice(inherited, cfg)
    branch, content = _response_decision(kind, message, correction, notice)
    if branch == "block":
        return {"decision": "block", "reason": content}
    return advise(content, "PostToolUse") if content else {}


def _gate_for(projected: RecordPayload, paths: list[str], cwd: Path, cfg: dict, ledger_root) -> Callable[[str], dict]:

    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        if projected["session_id"]:
            _journal_edits(projected, paths, ledger_root, turn_id)
        owned, inherited = _scan_paths(paths, cwd, cfg)
        corrections = _correct_paths(paths, cwd, cfg, owned, inherited)
        decisions = record_findings(
            session_id=projected["session_id"], hook="record",
            event="PostToolUse", findings=owned, turn_id=turn_id,
            tool_use_id=projected["tool_use_id"],
            duration_ms=int((time.monotonic() - started) * 1000),
            root=ledger_root, config=cfg,
        )
        return _response(decisions, inherited, cfg, corrections)

    return gate


def _run_record(payload: dict, config: dict | None) -> dict:
    projected = _projected_payload(payload)
    trusted_config = exact_string_dict(config)
    state_root, ledger_root = _config_roots(trusted_config)
    cwd_text = projected["cwd"]
    cfg = _resolved_config(_scan_config(trusted_config), cwd_text)
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
