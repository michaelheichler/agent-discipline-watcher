"""Run an additive PostToolBatch scan after canonical per-call scans."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lib import blocker_state, payloads, reporting
from lib.canonical import (
    _INVALID,
    Canonical,
    _canonical_value,
    _is_exact_type,
    _validated_mapping,
)
from lib.config import effective_config, effective_hook_config, resolve_outcome
from lib.hookio import advise, read_payload, write_payload
from lib.reporting import run_with_ledger
from lib.baseline import strip_committed
from lib.scanner import read_scannable, scan_all

BATCH_EVENT = "PostToolBatch"
UNDECIDABLE_KEY = "<batch-error>"
DEGRADED_RULE = "degraded_cross_file_only"
MIN_DUPLICATE_NONSPACE = 200
# Mirrors the PostToolUse matcher in hooks/hooks.json, including Bash, because PostToolBatch has no matcher of its own.
WRITE_TOOL_NAMES = frozenset({
    "write", "edit", "multiedit", "notebookedit", "apply_patch", "bash",
})


StatFingerprint = tuple[int, int, int, int, int]

NormalizedSignature = tuple[str, str, Canonical | None, tuple[str, ...]]
NormalizedCall = tuple[str, str, Canonical | None, tuple[str, ...], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _NormalizedCall:
    signature: NormalizedSignature
    raw_paths: tuple[str, ...]
    valid: bool


def _selected_tool_input(call: dict) -> object:
    selected: object = _INVALID
    for key in ("tool_input", "toolInput", "input"):
        if key not in call:
            continue
        value = call[key]
        if not _is_exact_type(value, dict):
            return value
        selected = value
        if value:
            return value
    return selected


def _is_write_tool(tool_name: str) -> bool:
    """Report whether the call can change a file, so that a file the agent only read is never scanned as an edit."""
    return tool_name.lower() in WRITE_TOOL_NAMES


def _normalized_path(raw_path: str, cwd: Path) -> str:
    try:
        path = Path(raw_path).expanduser()
        return str((path if path.is_absolute() else cwd / path).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return raw_path


def _normalized_calls(
    payload: dict,
) -> tuple[list[NormalizedCall], bool]:
    cwd = Path(payloads.cwd(payload) or ".")
    calls: list[NormalizedCall] = []
    seen: set[NormalizedSignature] = set()
    raw_calls = _exact_calls(payload)
    if raw_calls is None:
        return calls, False
    all_valid = True
    for call in raw_calls:
        normalized = _normalized_call(call, cwd)
        all_valid = all_valid and normalized.valid
        if normalized.signature not in seen:
            seen.add(normalized.signature)
            calls.append((*normalized.signature, normalized.raw_paths))
    return calls, all_valid


def _normalized_call(call: dict, cwd: Path) -> _NormalizedCall:
    raw_call_id = call.get("tool_use_id", "")
    raw_tool_name = call.get("tool_name", "")
    tool_input = _selected_tool_input(call)
    call_id = raw_call_id if _is_exact_type(raw_call_id, str) else ""
    tool_name = raw_tool_name if _is_exact_type(raw_tool_name, str) else ""
    canonical_value = (
        _canonical_value(tool_input) if _is_exact_type(tool_input, dict) else _INVALID
    )
    valid = (
        _is_exact_type(raw_call_id, str)
        and _is_exact_type(raw_tool_name, str)
        and canonical_value is not _INVALID
    )
    canonical = cast(Canonical, canonical_value) if valid else None
    writes = valid and _is_write_tool(tool_name)
    raw_paths = payloads.edited_paths(call) if writes else ()
    signature = (
        call_id,
        tool_name,
        canonical,
        tuple(_normalized_path(path, cwd) for path in raw_paths),
    )
    return _NormalizedCall(signature, raw_paths, valid)


def _entries_from_calls(
    calls: list[NormalizedCall], cwd: Path
) -> list[tuple[str, str, Path]]:
    return [
        (call_id, raw_path, payloads.resolved_path(raw_path, cwd))
        for call_id, _tool_name, _tool_input, _normalized, raw_paths in calls
        for raw_path in raw_paths
    ]


def _complete_unique_ids(
    calls: list[NormalizedCall], all_valid: bool, session_id: str, turn_id: str
) -> bool:
    ids = [
        call_id for call_id, _tool_name, _tool_input, _normalized, _raw_paths in calls
    ]
    return bool(
        all_valid
        and session_id
        and turn_id
        and calls
        and all(ids)
        and len(ids) == len(set(ids))
    )


def _has_nonempty_raw_batch(payload: dict) -> bool:
    if "tool_calls" not in payload:
        return False
    raw_calls = payload["tool_calls"]
    return bool(raw_calls) if _is_exact_type(raw_calls, list) else True


def _exact_calls(payload: dict) -> list[dict] | None:
    raw_calls = payload.get("tool_calls")
    if not _is_exact_type(raw_calls, list):
        return None
    calls = []
    for call in raw_calls:
        validated = _validated_mapping(call)
        if validated is None:
            return None
        calls.append(validated)
    return calls


def _is_reported_edit_row(row: dict, live_ids: set[str]) -> bool:
    return (
        row.get("hook") == "record"
        and row.get("event") == "edit"
        and isinstance(row.get("tool_use_id"), str)
        and row.get("tool_use_id") in live_ids
        and isinstance(row.get("path"), str)
        and bool(row.get("path"))
    )


def _reported_entries(
    calls: list[NormalizedCall], cfg: dict, session_id: str, turn_id: str
) -> set[tuple[str, str]]:
    """Read backward and stop at the session's own prior turn, because the ledger is append-only for the install's life and only the current turn's rows matter here."""
    live_ids = {
        call_id for call_id, _tool_name, _tool_input, _normalized, _raw_paths in calls
    }
    reported: set[tuple[str, str]] = set()
    rows = reporting.read_jsonl(reporting.LEDGER_FILENAME, cfg.get("ledger_root"))
    for row in reversed(rows):
        if row.get("session_id") != session_id:
            continue
        if row.get("turn_id") != turn_id:
            break
        if _is_reported_edit_row(row, live_ids):
            reported.add((row["tool_use_id"], row["path"]))
    return reported


def _duplicate_file_findings(
    entries: list[tuple[str, str, Path]], cfg: dict
) -> list[dict]:
    contents: dict[str, dict[tuple[int, int], str]] = {}
    for _call_id, _raw_path, path in sorted(entries, key=lambda item: str(item[2])):
        read = _stable_read(path, cfg)
        if read is None:
            continue
        file_id, text = read
        contents.setdefault(text, {}).setdefault(file_id, str(path))
    groups = (sorted(group.values()) for group in contents.values() if len(group) > 1)
    return [_duplicate_row(paths) for paths in sorted(groups)]


def _stable_read(path: Path, cfg: dict) -> tuple[tuple[int, int], str] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        fingerprint = _stat_fingerprint(path.stat())
    except (OSError, ValueError):
        return None
    text = _read_path(path, cfg)
    try:
        if _stat_fingerprint(path.stat()) != fingerprint:
            return None
    except OSError:
        return None
    if text is None or len("".join(text.split())) < MIN_DUPLICATE_NONSPACE:
        return None
    return fingerprint[:2], text


def _duplicate_row(paths: list[str]) -> dict:
    joined = ", ".join(paths)
    return {
        "family": "clean_code",
        "rule": "duplicate_file_content",
        "line": 1,
        "detail": "Exact substantive content is duplicated across batch files.",
        "snippet": joined[:180],
        "action": "Keep one implementation and remove or extract the duplicate.",
        "path": joined,
        "_tool_use_id": "",
    }


def _stat_fingerprint(file_stat: os.stat_result) -> StatFingerprint:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _scan_path(path: Path, cfg: dict) -> list[dict]:
    text = _read_path(path, cfg)
    if text is None:
        return []
    findings = strip_committed(path, scan_all(str(path), text, cfg), cfg)
    return [{**finding, "path": str(path)} for finding in findings]


def _read_path(path: Path, cfg: dict) -> str | None:
    try:
        return read_scannable(path, cfg)
    except (OSError, ValueError):
        return None


def _sanitized_payload(payload: object) -> dict:
    validated = _validated_mapping(payload)
    if validated is None:
        return {}
    source = dict.copy(validated)
    raw_session_id = source.get("session_id")
    raw_cwd = source.get("cwd")
    raw_agent_id = source.get("agent_id")
    raw_calls = source.get("tool_calls", _INVALID)
    sanitized: dict[str, object] = {
        "session_id": raw_session_id if _is_exact_type(raw_session_id, str) else "",
        "cwd": raw_cwd if _is_exact_type(raw_cwd, str) else "",
    }
    if _is_exact_type(raw_agent_id, str) and raw_agent_id:
        sanitized["agent_id"] = raw_agent_id
    if raw_calls is not _INVALID:
        sanitized["tool_calls"] = (
            list.copy(raw_calls) if _is_exact_type(raw_calls, list) else raw_calls
        )
    return sanitized


def _findings_for_calls(
    calls: list[NormalizedCall],
    all_valid: bool,
    entries: list[tuple[str, str, Path]],
    cfg: dict,
    session_id: str,
    turn_id: str,
) -> list[dict]:
    findings = _duplicate_file_findings(entries, cfg)
    if not _complete_unique_ids(calls, all_valid, session_id, turn_id):
        return findings
    reported = _reported_entries(calls, cfg, session_id, turn_id)
    ordered = sorted(entries, key=lambda item: (str(item[2]), item[0]))
    for call_id, raw_path, path in ordered:
        if (call_id, raw_path) in reported:
            continue
        for finding in _scan_path(path, cfg):
            finding["_tool_use_id"] = call_id
            findings.append(finding)
    return findings


def findings_for_batch(
    payload: dict,
    config: dict | None = None,
    turn_id: str = "",
) -> list[dict]:
    payload = _sanitized_payload(payload)
    cfg = effective_config(config, payloads.cwd(payload) or None)
    cwd = Path(payloads.cwd(payload) or ".")
    calls, all_valid = _normalized_calls(payload)
    entries = _entries_from_calls(calls, cwd)
    return _findings_for_calls(
        calls, all_valid, entries, cfg, payloads.session_id(payload), turn_id
    )


def findings_for_paths(
    session_id: str,
    cwd: str,
    paths: list[str],
    cfg: dict,
    source: str,
) -> list[dict]:
    """Exists because end_turn used to fabricate a whole batch payload just to reach this same duplicate-and-scan logic."""
    base = Path(cwd or ".")
    entries = [(source, raw_path, payloads.resolved_path(raw_path, base)) for raw_path in paths]
    findings = _duplicate_file_findings(entries, cfg)
    for call_id, _raw_path, path in entries:
        for finding in _scan_path(path, cfg):
            finding["_tool_use_id"] = call_id
            findings.append(finding)
    return findings


def _record_batch_row(session_id: str, cfg: dict, turn_id: str, duration_ms: int, **fields) -> None:
    reporting.record_decision(
        session_id=session_id, hook="batch", event=BATCH_EVENT,
        duration_ms=duration_ms, turn_id=turn_id, root=cfg.get("ledger_root"),
        **fields,
    )


def _record_decisions(
    session_id: str,
    cfg: dict,
    turn_id: str,
    duration_ms: int,
    decisions: list[tuple[dict, str]],
    payload: dict,
    calls: list[NormalizedCall],
    all_valid: bool,
) -> None:
    for finding, outcome in decisions:
        _record_batch_row(
            session_id, cfg, turn_id, duration_ms,
            family=finding["family"], rule=finding["rule"], path=finding["path"],
            tool_use_id=finding.get("_tool_use_id", ""), outcome=outcome,
        )
    if _has_nonempty_raw_batch(payload) and not _complete_unique_ids(calls, all_valid, session_id, turn_id):
        _record_batch_row(
            session_id, cfg, turn_id, duration_ms,
            family="", rule=DEGRADED_RULE, path="", tool_use_id="", outcome="release",
        )


def _update_blocker_state(
    session_id: str,
    agent_id: str,
    cfg: dict,
    entries: list[tuple[str, str, Path]],
    kind: str,
    reason: str,
) -> None:
    blocker_state.touch_paths(
        session_id, agent_id, [str(path) for _call, _raw, path in entries], cfg.get("state_root"),
    )
    if kind == "block":
        blocker_state.set_pending(session_id, agent_id, "<batch>", reason, cfg.get("state_root"))
    else:
        blocker_state.clear_pending(session_id, agent_id, "<batch>", cfg.get("state_root"))
    blocker_state.clear_pending(session_id, agent_id, UNDECIDABLE_KEY, cfg.get("state_root"))


def _batch_gate(payload: dict, cfg: dict, session_id: str):
    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        cwd = Path(payloads.cwd(payload) or ".")
        calls, all_valid = _normalized_calls(payload)
        entries = _entries_from_calls(calls, cwd)
        findings = _findings_for_calls(calls, all_valid, entries, cfg, session_id, turn_id)
        decisions = [(finding, resolve_outcome(finding, cfg)) for finding in findings]
        duration_ms = int((time.monotonic() - started) * 1000)
        if session_id:
            _record_decisions(session_id, cfg, turn_id, duration_ms, decisions, payload, calls, all_valid)
        report_cfg = {**cfg, "session_id": session_id, "turn_id": turn_id}
        kind, reason = reporting.verdict_message(decisions, report_cfg)
        if session_id:
            _update_blocker_state(session_id, blocker_state.scope(payload), cfg, entries, kind, reason)
        if kind == "block":
            return {"decision": "block", "reason": reason}
        if kind == "observe":
            return advise(reason, BATCH_EVENT)
        return {}

    return gate


UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this batch. Treat the turn as unscanned and rerun the check "
    "after repairing the gate config. Cause: "
)


def run(payload: dict, config: dict | None = None) -> dict:
    """Judge a finished batch, reporting rather than dying when the gate itself cannot decide."""
    try:
        return _run(payload, config)
    except Exception as exc:
        reason = UNDECIDABLE + str(exc)
        sanitized = _sanitized_payload(payload)
        session_id = payloads.session_id(sanitized)
        if session_id:
            root = effective_hook_config(config, payloads.cwd(sanitized) or None).get("state_root")
            try:
                blocker_state.set_pending(
                    session_id, blocker_state.scope(sanitized), UNDECIDABLE_KEY, reason, root,
                )
            except Exception as state_exc:
                import sys
                sys.stderr.write(f"agent-discipline-watcher: blocker state update failed: {state_exc}\n")
        return {"decision": "block", "reason": reason}


def _run(payload: dict, config: dict | None) -> dict:
    payload = _sanitized_payload(payload)
    cfg = effective_hook_config(config, payloads.cwd(payload) or None)
    return run_with_ledger(
        hook="batch",
        payload=payload,
        gate=_batch_gate(payload, cfg, payloads.session_id(payload)),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def cli_response(response: dict) -> dict:
    if response.get("decision") != "block":
        return response
    return advise(str(response.get("reason") or "PostToolBatch blocked findings"), BATCH_EVENT)


if __name__ == "__main__":
    write_payload(cli_response(run(read_payload())))
