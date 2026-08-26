"""Keep batch review additive because cross-call patterns cannot be judged by canonical per-call scans."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
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
from lib.findings import Finding
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


@dataclass(frozen=True, slots=True)
class _NormalizedCalls:
    calls: list[NormalizedCall]
    all_valid: bool


@dataclass(frozen=True, slots=True)
class _BatchTurnContext:
    session_id: str
    turn_id: str
    config: dict


@dataclass(frozen=True, slots=True)
class _BatchVerdict:
    entries: list[tuple[str, str, Path]]
    kind: str
    reason: str


@dataclass(frozen=True, slots=True)
class PathBatchScan:
    cwd: str
    paths: list[str]
    config: dict
    source: str


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


def _normalized_calls(payload: dict) -> _NormalizedCalls:
    cwd = Path(payloads.cwd(payload) or ".")
    calls: list[NormalizedCall] = []
    seen: set[NormalizedSignature] = set()
    raw_calls = _exact_calls(payload)
    if raw_calls is None:
        return _NormalizedCalls(calls, False)
    all_valid = True
    for call in raw_calls:
        normalized = _normalized_call(call, cwd)
        all_valid = all_valid and normalized.valid
        if normalized.signature not in seen:
            seen.add(normalized.signature)
            calls.append((*normalized.signature, normalized.raw_paths))
    return _NormalizedCalls(calls, all_valid)


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
    normalized: _NormalizedCalls, turn: _BatchTurnContext
) -> bool:
    ids = [
        call_id
        for call_id, _tool_name, _tool_input, _normalized, _raw_paths in normalized.calls
    ]
    return bool(
        normalized.all_valid
        and turn.session_id
        and turn.turn_id
        and normalized.calls
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
    normalized: _NormalizedCalls, turn: _BatchTurnContext
) -> set[tuple[str, str]]:
    """Read backward and stop at the session's own prior turn, because the ledger is append-only for the install's life and only the current turn's rows matter here."""
    live_ids = {
        call_id
        for call_id, _tool_name, _tool_input, _normalized, _raw_paths in normalized.calls
    }
    reported: set[tuple[str, str]] = set()
    rows = reporting.read_jsonl(
        reporting.LEDGER_FILENAME, turn.config.get("ledger_root")
    )
    for row in reversed(rows):
        if row.get("session_id") != turn.session_id:
            continue
        if row.get("turn_id") != turn.turn_id:
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
    return Finding(
        family="clean_code",
        rule="duplicate_file_content",
        line=1,
        detail="Exact substantive content is duplicated across batch files.",
        force=None,
        snippet=joined[:180],
        action="Keep one implementation and remove or extract the duplicate.",
        path=joined,
        severity=None,
        tool_use_id="",
    ).to_dict()


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
    return [Finding.from_dict(finding).with_path(str(path)).to_dict() for finding in findings]


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
    normalized: _NormalizedCalls,
    entries: list[tuple[str, str, Path]],
    turn: _BatchTurnContext,
) -> list[dict]:
    findings = _duplicate_file_findings(entries, turn.config)
    if not _complete_unique_ids(normalized, turn):
        return findings
    reported = _reported_entries(normalized, turn)
    ordered = sorted(entries, key=lambda item: (str(item[2]), item[0]))
    for call_id, raw_path, path in ordered:
        if (call_id, raw_path) in reported:
            continue
        for finding in _scan_path(path, turn.config):
            findings.append(Finding.from_dict(finding).with_tool_use_id(call_id).to_dict())
    return findings


def findings_for_batch(
    payload: dict,
    config: dict | None = None,
    turn_id: str = "",
) -> list[dict]:
    payload = _sanitized_payload(payload)
    cfg = effective_config(config, payloads.cwd(payload) or None)
    cwd = Path(payloads.cwd(payload) or ".")
    normalized = _normalized_calls(payload)
    entries = _entries_from_calls(normalized.calls, cwd)
    turn = _BatchTurnContext(payloads.session_id(payload), turn_id, cfg)
    return _findings_for_calls(normalized, entries, turn)


def _path_batch_scan(
    value: PathBatchScan | str, arguments: tuple[object, ...]
) -> PathBatchScan:
    if isinstance(value, PathBatchScan):
        if arguments:
            raise TypeError("PathBatchScan cannot be combined with positional scan fields")
        return value
    if len(arguments) != 4:
        raise TypeError("findings_for_paths requires cwd, paths, config, and source")
    cwd, paths, config, source = arguments
    if not isinstance(cwd, str) or not isinstance(source, str):
        raise TypeError("cwd and source must be strings")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise TypeError("paths must be a list of strings")
    if not isinstance(config, dict):
        raise TypeError("config must be a dictionary")
    return PathBatchScan(cwd, paths, config, source)


def findings_for_paths(
    scan: PathBatchScan | str, *arguments: object
) -> list[dict]:
    return _findings_for_path_scan(_path_batch_scan(scan, arguments))


def _findings_for_path_scan(scan: PathBatchScan) -> list[dict]:
    base = Path(scan.cwd or ".")
    entries = [
        (scan.source, raw_path, payloads.resolved_path(raw_path, base))
        for raw_path in scan.paths
    ]
    findings = _duplicate_file_findings(entries, scan.config)
    for call_id, _raw_path, path in entries:
        for finding in _scan_path(path, scan.config):
            findings.append(
                Finding.from_dict(finding).with_tool_use_id(call_id).to_dict()
            )
    return findings


def _record_batch_row(
    turn: _BatchTurnContext, duration_ms: int, **fields: object
) -> None:
    reporting.record_decision(
        session_id=turn.session_id, hook="batch", event=BATCH_EVENT,
        duration_ms=duration_ms, turn_id=turn.turn_id,
        root=turn.config.get("ledger_root"),
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
    turn = _BatchTurnContext(session_id, turn_id, cfg)
    normalized = _NormalizedCalls(calls, all_valid)
    for finding, outcome in decisions:
        _record_batch_row(
            turn, duration_ms,
            family=finding["family"], rule=finding["rule"], path=finding["path"],
            tool_use_id=finding.get("_tool_use_id", ""), outcome=outcome,
        )
    if _has_nonempty_raw_batch(payload) and not _complete_unique_ids(normalized, turn):
        _record_batch_row(
            turn, duration_ms,
            family="", rule=DEGRADED_RULE, path="", tool_use_id="", outcome="release",
        )


def _update_blocker_state(
    scope: blocker_state.BlockerScope, verdict: _BatchVerdict
) -> None:
    paths = [str(path) for _call, _raw, path in verdict.entries]
    blocker_state.touch_paths(scope, paths)
    if verdict.kind == "block":
        blocker_state.set_pending(scope, "<batch>", verdict.reason)
    else:
        blocker_state.clear_pending(scope, "<batch>")
    blocker_state.clear_pending(scope, UNDECIDABLE_KEY)


def _batch_gate(payload: dict, cfg: dict, session_id: str) -> Callable[[str], dict[str, object]]:
    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        cwd = Path(payloads.cwd(payload) or ".")
        normalized = _normalized_calls(payload)
        entries = _entries_from_calls(normalized.calls, cwd)
        turn = _BatchTurnContext(session_id, turn_id, cfg)
        findings = _findings_for_calls(normalized, entries, turn)
        decisions = [(finding, resolve_outcome(finding, cfg)) for finding in findings]
        duration_ms = int((time.monotonic() - started) * 1000)
        if session_id:
            _record_decisions(
                session_id, cfg, turn_id, duration_ms, decisions, payload,
                normalized.calls, normalized.all_valid,
            )
        report_cfg = {**cfg, "session_id": session_id, "turn_id": turn_id}
        kind, reason = reporting.verdict_message(decisions, report_cfg)
        if session_id:
            _update_blocker_state(
                blocker_state.BlockerScope(
                    session_id, blocker_state.scope(payload), cfg.get("state_root")
                ),
                _BatchVerdict(entries, kind, reason),
            )
        return _batch_response(kind, reason)

    return gate


def _batch_response(kind: str, reason: str) -> dict:
    if kind == "block":
        return {"decision": "block", "reason": reason}
    if kind == "observe":
        return advise(reason, BATCH_EVENT)
    return {}


UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this batch. Treat the turn as unscanned and rerun the check "
    "after repairing the gate config. Cause: "
)


def _record_undecidable_blocker(
    payload: dict, config: dict | None, reason: str
) -> None:
    sanitized = _sanitized_payload(payload)
    session_id = payloads.session_id(sanitized)
    if not session_id:
        return
    root = effective_hook_config(config, payloads.cwd(sanitized) or None).get("state_root")
    try:
        blocker_state.set_pending(
            session_id, blocker_state.scope(sanitized), UNDECIDABLE_KEY, reason, root,
        )
    except Exception as state_exc:
        import sys
        sys.stderr.write(f"agent-discipline-watcher: blocker state update failed: {state_exc}\n")


def run(payload: dict, config: dict | None = None) -> dict:
    """Fail closed because an undecidable batch must not silently release the turn."""
    try:
        return _run(payload, config)
    except Exception as exc:
        reason = UNDECIDABLE + str(exc)
        _record_undecidable_blocker(payload, config, reason)
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
