"""Run an additive PostToolBatch scan after canonical per-call scans."""

from __future__ import annotations

import json
import math
import operator
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard, TypeVar, cast

import pre_bash

from lib import payloads, reporting
from lib.config import effective_config, resolve_outcome
from lib.hookio import advise, read_payload, write_payload
from lib.reporting import run_with_ledger
from lib.baseline import strip_committed
from lib.scanner import read_scannable, scan_all

BATCH_EVENT = "PostToolBatch"
DEGRADED_RULE = "degraded_cross_file_only"
MIN_DUPLICATE_NONSPACE = 200
PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)
# Mirrors the PostToolUse matcher in hooks/hooks.json, including Bash, because PostToolBatch has no matcher of its own.
WRITE_TOOL_NAMES = frozenset({
    "write", "edit", "multiedit", "notebookedit", "apply_patch", "bash",
})


StatFingerprint = tuple[int, int, int, int, int]
ExactType = TypeVar("ExactType")


def _is_exact_type(value: object, expected: type[ExactType]) -> TypeGuard[ExactType]:
    return operator.is_(type(value), expected)


class _CanonicalNode:

    __slots__ = ("children", "keys", "kind", "scalar", "structural_hash")
    children: tuple[_CanonicalNode, ...]
    keys: tuple[str, ...]
    kind: str
    scalar: object
    structural_hash: int

    def __init__(
        self,
        kind: str,
        *,
        scalar: object = None,
        keys: tuple[str, ...] = (),
        children: tuple[_CanonicalNode, ...] = (),
    ) -> None:
        self.kind = kind
        self.scalar = scalar
        self.keys = keys
        self.children = children
        self.structural_hash = hash(
            (kind, scalar, keys, tuple(child.structural_hash for child in children))
        )

    def __hash__(self) -> int:
        return self.structural_hash

    def __eq__(self, other: object) -> bool:
        if not _is_exact_type(other, _CanonicalNode):
            return NotImplemented
        candidate = other
        if self.structural_hash != candidate.structural_hash:
            return False
        pending = [(self, candidate)]
        compared: set[tuple[int, int]] = set()
        while pending:
            left, right = pending.pop()
            pair = (id(left), id(right))
            if pair in compared:
                continue
            compared.add(pair)
            if (
                left.kind != right.kind
                or left.scalar != right.scalar
                or left.keys != right.keys
                or len(left.children) != len(right.children)
            ):
                return False
            pending.extend(zip(left.children, right.children, strict=True))
        return True


Canonical = _CanonicalNode
CanonicalTask = tuple[str, object, object]


@dataclass(frozen=True, slots=True)
class _CanonicalFrame:
    identity: int
    kind: str
    keys: tuple[str, ...]
    child_count: int


@dataclass(slots=True)
class _CanonicalTraversal:
    tasks: list[CanonicalTask]
    values: list[Canonical]
    active: set[int]
    completed: dict[int, Canonical]


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


_INVALID = object()


def _canonical_atom(value: object) -> Canonical | object:
    if value is None:
        return Canonical("none")
    if _is_exact_type(value, bool):
        return Canonical("bool", scalar=value)
    if _is_exact_type(value, int):
        return Canonical("int", scalar=value)
    if _is_exact_type(value, float):
        return (
            Canonical("float", scalar=value.hex()) if math.isfinite(value) else _INVALID
        )
    if _is_exact_type(value, str):
        return Canonical("str", scalar=value)
    return _INVALID


def _exact_dict_keys(mapping: dict[object, object]) -> tuple[object, ...]:
    return tuple(mapping)


def _validated_mapping(value: object) -> dict[str, object] | None:
    if not _is_exact_type(value, dict):
        return None
    mapping = cast(dict[object, object], value)
    if any(not _is_exact_type(key, str) for key in _exact_dict_keys(mapping)):
        return None
    return cast(dict[str, object], mapping)


def _finish_container(state: _CanonicalTraversal, frame: _CanonicalFrame) -> None:
    child_start = len(state.values) - frame.child_count
    children = tuple(state.values[child_start:])
    del state.values[child_start:]
    state.active.remove(frame.identity)
    node = Canonical(frame.kind, keys=frame.keys, children=children)
    state.completed[frame.identity] = node
    state.values.append(node)


def _schedule_list(sequence: list[object], state: _CanonicalTraversal) -> bool:
    identity = id(sequence)
    if identity in state.completed:
        state.values.append(state.completed[identity])
        return True
    if identity in state.active:
        return False
    state.active.add(identity)
    frame = _CanonicalFrame(identity, "list", (), len(sequence))
    state.tasks.append(("finish", sequence, frame))
    state.tasks.extend(("visit", child, None) for child in reversed(sequence))
    return True


def _schedule_dict(mapping: dict[object, object], state: _CanonicalTraversal) -> bool:
    identity = id(mapping)
    if identity in state.completed:
        state.values.append(state.completed[identity])
        return True
    if identity in state.active:
        return False
    state.active.add(identity)
    raw_keys = _exact_dict_keys(mapping)
    if any(not _is_exact_type(key, str) for key in raw_keys):
        return False
    string_keys = tuple(sorted(cast(str, key) for key in raw_keys))
    frame = _CanonicalFrame(identity, "dict", string_keys, len(string_keys))
    state.tasks.append(("finish", mapping, frame))
    state.tasks.extend(("visit", mapping[key], None) for key in reversed(string_keys))
    return True


def _canonical_value(value: object) -> Canonical | object:
    state = _CanonicalTraversal([("visit", value, None)], [], set(), {})
    while state.tasks:
        action, item, metadata = state.tasks.pop()
        if action == "finish":
            _finish_container(state, cast(_CanonicalFrame, metadata))
            continue

        if _is_exact_type(item, list):
            if not _schedule_list(cast(list[object], item), state):
                return _INVALID
        elif _is_exact_type(item, dict):
            if not _schedule_dict(cast(dict[object, object], item), state):
                return _INVALID
        else:
            atom = _canonical_atom(item)
            if atom is _INVALID:
                return _INVALID
            state.values.append(cast(Canonical, atom))
    return state.values[0]


def _is_write_tool(tool_name: str) -> bool:
    """Report whether the call can change a file, so that a file the agent only read is never scanned as an edit."""
    return tool_name.lower() in WRITE_TOOL_NAMES


def _edited_paths(tool_input: dict) -> tuple[str, ...]:
    path = tool_input.get("file_path") or tool_input.get("path")
    if path:
        return (path,) if _is_exact_type(path, str) else ()
    command = tool_input.get("command")
    if command:
        command_text = command if _is_exact_type(command, str) else (
            " ".join(str(part) for part in command) if _is_exact_type(command, list) else None
        )
        if command_text:
            bash_paths = tuple(pre_bash.write_paths(command_text))
            if bash_paths:
                return bash_paths
    patch = (
        tool_input.get("patch")
        or tool_input.get("command")
        or tool_input.get("input")
        or ""
    )
    if _is_exact_type(patch, list):
        if any(not _is_exact_type(part, str) for part in patch):
            return ()
        patch = "\n".join(patch)
    if not _is_exact_type(patch, str):
        return ()
    return tuple(match.strip().strip('"') for match in PATCH_FILE.findall(patch))


def _normalized_path(raw_path: str, cwd: Path) -> str:
    path = Path(raw_path).expanduser()
    try:
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
    raw_paths = _edited_paths(cast(dict, tool_input)) if writes else ()
    signature = (
        call_id,
        tool_name,
        canonical,
        tuple(_normalized_path(path, cwd) for path in raw_paths),
    )
    return _NormalizedCall(signature, raw_paths, valid)


def _call_entries(payload: dict) -> list[tuple[str, str, Path]]:
    cwd = Path(payloads.cwd(payload) or ".")
    calls, _all_valid = _normalized_calls(payload)
    return [
        (
            call_id,
            raw_path,
            Path(raw_path) if Path(raw_path).is_absolute() else cwd / raw_path,
        )
        for call_id, _tool_name, _tool_input, _normalized, raw_paths in calls
        for raw_path in raw_paths
    ]


def _has_complete_unique_ids(payload: dict, turn_id: str) -> bool:
    calls, all_valid = _normalized_calls(payload)
    ids = [
        call_id for call_id, _tool_name, _tool_input, _normalized, _raw_paths in calls
    ]
    return bool(
        all_valid
        and payloads.session_id(payload)
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


def _reported_entries(payload: dict, cfg: dict, turn_id: str) -> set[tuple[str, str]]:
    session_id = payloads.session_id(payload)
    calls, _all_valid = _normalized_calls(payload)
    live_ids = {
        call_id for call_id, _tool_name, _tool_input, _normalized, _raw_paths in calls
    }
    return {
        (row["tool_use_id"], row["path"])
        for row in _ledger_rows(cfg.get("ledger_root"))
        if row.get("session_id") == session_id
        and row.get("turn_id") == turn_id
        and row.get("hook") == "record"
        and row.get("event") == "edit"
        and isinstance(row.get("tool_use_id"), str)
        and row.get("tool_use_id") in live_ids
        and isinstance(row.get("path"), str)
        and row.get("path")
    }


def _ledger_rows(root: object) -> list[dict]:
    directory = (
        Path(root)
        if isinstance(root, (str, Path))
        else Path.home() / ".agent-discipline" / "ledger"
    )
    try:
        lines = (
            (directory / reporting.LEDGER_FILENAME)
            .read_text(encoding="utf-8")
            .splitlines()
        )
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


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
        "force": True,
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


def _scan_path(path: Path, cfg: dict, session_id: str) -> list[dict]:
    text = _read_path(path, cfg)
    if text is None:
        return []
    findings = []
    findings = strip_committed(path, scan_all(str(path), text, cfg), cfg)
    stamped = []
    for finding in findings:
        item = dict(finding)
        item["path"] = str(path)
        stamped.append(item)
    return stamped


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
    raw_calls = source.get("tool_calls", _INVALID)
    sanitized: dict[str, object] = {
        "session_id": raw_session_id if _is_exact_type(raw_session_id, str) else "",
        "cwd": raw_cwd if _is_exact_type(raw_cwd, str) else "",
    }
    if raw_calls is not _INVALID:
        sanitized["tool_calls"] = (
            list.copy(raw_calls) if _is_exact_type(raw_calls, list) else raw_calls
        )
    return sanitized


def findings_for_batch(
    payload: dict,
    config: dict | None = None,
    turn_id: str = "",
) -> list[dict]:
    payload = _sanitized_payload(payload)
    cfg = effective_config(config, payloads.cwd(payload) or None)
    entries = _call_entries(payload)
    findings = _duplicate_file_findings(entries, cfg)
    if not _has_complete_unique_ids(payload, turn_id):
        return findings
    reported = _reported_entries(payload, cfg, turn_id)
    ordered = sorted(entries, key=lambda item: (str(item[2]), item[0]))
    for call_id, raw_path, path in ordered:
        if (call_id, raw_path) in reported:
            continue
        for finding in _scan_path(path, cfg, payloads.session_id(payload)):
            finding["_tool_use_id"] = call_id
            findings.append(finding)
    return findings


def _record_batch_row(session_id: str, cfg: dict, turn_id: str, duration_ms: int, **fields) -> None:
    reporting.record_decision(
        session_id=session_id, hook="batch", event=BATCH_EVENT,
        duration_ms=duration_ms, turn_id=turn_id, root=cfg.get("ledger_root"),
        **fields,
    )


def _record_decisions(session_id, cfg, turn_id, duration_ms, decisions, payload) -> None:
    for finding, outcome in decisions:
        _record_batch_row(
            session_id, cfg, turn_id, duration_ms,
            family=finding["family"], rule=finding["rule"], path=finding["path"],
            tool_use_id=finding.get("_tool_use_id", ""), outcome=outcome,
        )
    if _has_nonempty_raw_batch(payload) and not _has_complete_unique_ids(payload, turn_id):
        _record_batch_row(
            session_id, cfg, turn_id, duration_ms,
            family="", rule=DEGRADED_RULE, path="", tool_use_id="", outcome="release",
        )


def _batch_gate(payload: dict, cfg: dict, session_id: str):
    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        findings = findings_for_batch(payload, cfg, turn_id)
        decisions = [(finding, resolve_outcome(finding, cfg)) for finding in findings]
        duration_ms = int((time.monotonic() - started) * 1000)
        if session_id:
            _record_decisions(session_id, cfg, turn_id, duration_ms, decisions, payload)
        kind, reason = reporting.verdict_message(decisions, cfg)
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
        return {"decision": "block", "reason": UNDECIDABLE + str(exc)}


def _run(payload: dict, config: dict | None) -> dict:
    payload = _sanitized_payload(payload)
    cfg = effective_config(config, payloads.cwd(payload) or None)
    return run_with_ledger(
        hook="batch",
        payload=payload,
        gate=_batch_gate(payload, cfg, payloads.session_id(payload)),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def cli_response(response: dict) -> dict:
    return response


if __name__ == "__main__":
    response = cli_response(run(read_payload()))
    if response.get("decision") == "block":
        import sys
        sys.stderr.write(str(response.get("reason", "PostToolBatch blocked findings")) + "\n")
        raise SystemExit(2)
    write_payload(response)
