"""Command handlers, because Luna has no native Claude agent route."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from . import journal, claude_native, payloads
from .config import effective_hook_config
from .document_review import data_boundary_enabled, document_work
from .hookio import context, read_payload, stop_block, write_payload
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .luna_feedback import bounded as _bounded
from .luna_feedback import comment_feedback as _comment_feedback
from .luna_feedback import document_feedback as _document_feedback
from .luna_feedback import pattern_feedback as _pattern_feedback
from .luna_storage import LunaProviderFailure
from .narration_candidates import candidates
from .pattern_judge import PatternCandidate, request_for as pattern_request
from .pattern_semantic import load_exemplars, load_manifest, rule_blocks, rule_prompt


EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "Bash"})
MAX_FEEDBACK_CHARS = 900
MAX_DOCUMENT_CHARS = 24_000
MAX_LIVE_CANDIDATES = journal.MAX_ROWS
MAX_LIVE_PATHS = 32
MAX_LIVE_PATH_CHARS = 4096
MAX_LIVE_FILE_BYTES = 128 * 1024
MAX_LIVE_SCAN_BYTES = 512 * 1024
MAX_LIVE_RAW_EDIT_BYTES = 512 * 1024
STOP_LABEL = "ADW current-session journal"
Work = tuple[JudgeRequest, Any]
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _descend(descriptor: int, part: str) -> int:
    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
    try:
        is_directory = stat.S_ISDIR(os.fstat(child).st_mode)
    except OSError:
        os.close(child)
        raise
    if not is_directory:
        os.close(child)
        raise ValueError("live candidate parent is not a directory")
    os.close(descriptor)
    return child


def _open_parent(target: Path) -> int:
    """One hop at a time, because a swapped symlink must not redirect the read."""
    parts = [part for part in target.parent.parts if part not in (target.anchor, "")]
    if any(part in (".", "..") for part in parts):
        raise ValueError("unsafe path component")
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    for part in parts:
        try:
            descriptor = _descend(descriptor, part)
        except OSError:
            os.close(descriptor)
            raise
    return descriptor


def _read_up_to(handle: int, limit: int) -> bytes | None:
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(handle, min(65536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return None if len(data) > limit else bytes(data)


def _read_leaf(descriptor: int, name: str, limit: int) -> bytes | None:
    """Metadata compared twice, because a file swapped mid-read is not the edit."""
    leaf = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    if not stat.S_ISREG(leaf.st_mode):
        return None
    handle = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=descriptor)
    try:
        opened = os.fstat(handle)
        if _file_metadata(opened) != _file_metadata(leaf) or opened.st_size > limit:
            return None
        data = _read_up_to(handle, limit)
        final = os.fstat(handle)
        if data is None or _file_metadata(final) != _file_metadata(opened) or len(data) != final.st_size:
            return None
        return data
    finally:
        os.close(handle)


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _bounded_file_text(path: Path, limit: int) -> tuple[str, int] | None:
    try:
        target = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        descriptor = _open_parent(target)
    except (OSError, ValueError):
        return None
    try:
        data = _read_leaf(descriptor, target.name, limit)
        return None if data is None else (data.decode("utf-8"), len(data))
    except (OSError, ValueError):
        return None
    finally:
        _close_quietly(descriptor)


def _file_metadata(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _byte_size(value: str) -> int:
    """Over the cap on a lone surrogate, because it is malformed input."""
    if len(value) > MAX_LIVE_RAW_EDIT_BYTES:
        return MAX_LIVE_RAW_EDIT_BYTES + 1
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        return MAX_LIVE_RAW_EDIT_BYTES + 1


def _raw_tool_input(payload: dict) -> dict[str, object]:
    fields = payloads.exact_string_dict(payload)
    for key in ("tool_input", "toolInput", "input"):
        candidate = payloads.exact_string_dict(fields.get(key))
        if candidate:
            return candidate
    return {}


def _raw_text_within_bounds(tool: str, value: str) -> bool:
    if _byte_size(value) > MAX_LIVE_RAW_EDIT_BYTES:
        return False
    marker_count = sum(value.count(marker) for marker in (
        "*** Add File:", "*** Update File:", "*** Delete File:", "*** Move to:",
    ))
    if marker_count > MAX_LIVE_PATHS:
        return False
    return not (tool == "Bash" and value.count("\n") > MAX_LIVE_PATHS * 8)


def _raw_parts_within_bounds(value: list) -> bool:
    if len(value) > MAX_LIVE_PATHS * 8:
        return False
    total = 0
    for part in value:
        if type(part) is not str:
            return False
        total += _byte_size(part)
        if total > MAX_LIVE_RAW_EDIT_BYTES:
            return False
    return True


def _bounded_raw_edit(payload: object) -> bool:
    """Checked first, because edited_paths would parse a huge body."""
    if type(payload) is not dict:
        return False
    tool = payloads.tool_name(payload)
    if tool not in {"apply_patch", "Bash"}:
        return True
    tool_input = _raw_tool_input(payload)
    for key in ("patch", "command", "input"):
        value = tool_input.get(key)
        if type(value) is str:
            return _raw_text_within_bounds(tool, value)
        if type(value) is list:
            return _raw_parts_within_bounds(value)
    return True


def _safe_edited_paths(payload: object) -> tuple[str, ...]:
    if not _bounded_raw_edit(payload):
        return ()
    try:
        paths = payloads.edited_paths(payload)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ()
    if len(paths) > MAX_LIVE_PATHS:
        return ()
    return tuple(paths)


def _live_path(raw_path: object, cwd: Path) -> Path | None:
    if not isinstance(raw_path, str) or len(raw_path) > MAX_LIVE_PATH_CHARS:
        return None
    try:
        return payloads.resolved_path(raw_path, cwd)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _file_candidates(path: Path, text: str) -> list[Candidate]:
    return [
        Candidate(candidate.path, candidate.line, candidate.text[:journal.MAX_CANDIDATE_CHARS])
        for candidate in candidates(str(path), text)
    ]


def _read_candidates(payload: object) -> tuple[Candidate, ...]:
    if type(payload) is not dict or payloads.tool_name(payload) not in EDIT_TOOLS:
        return ()
    cwd_text = payloads.cwd(payload)
    if not cwd_text:
        return ()
    found: list[Candidate] = []
    scanned = 0
    for raw_path in _safe_edited_paths(payload):
        if scanned >= MAX_LIVE_SCAN_BYTES:
            break
        path = _live_path(raw_path, Path(cwd_text))
        bounded = None if path is None else _bounded_file_text(path, min(MAX_LIVE_FILE_BYTES, MAX_LIVE_SCAN_BYTES - scanned))
        if path is None or bounded is None:
            continue
        scanned += bounded[1]
        found.extend(_file_candidates(path, bounded[0]))
        if len(found) >= MAX_LIVE_CANDIDATES:
            return tuple(found[:MAX_LIVE_CANDIDATES])
    return tuple(found)


def post_request(payload: object) -> tuple[JudgeRequest, tuple[Candidate, ...]] | None:
    found = _read_candidates(payload)
    if not found:
        return None
    return comment_request(found), found


def _stop_rows(payload: object, state_root: str | Path | None) -> list[dict[str, Any]]:
    if type(payload) is not dict or payloads.stop_hook_active(payload):
        return []
    session_id = payloads.session_id(payload)
    if not session_id:
        return []
    try:
        return journal.read_for_stop(session_id, state_root=state_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _pattern_candidate(row: dict[str, Any]) -> PatternCandidate:
    line = row.get("line") if isinstance(row.get("line"), int) else 1
    return PatternCandidate(str(row.get("path", ""))[:512], line, str(row.get("text", ""))[:320])


def _pattern_work(rows: list[dict[str, Any]], config: dict | None) -> list[Work]:
    """One request per rule, because each carries its examples."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("role") == "pattern" and row.get("text"):
            grouped.setdefault(str(row.get("rule")), []).append(row)
    if not grouped:
        return []
    exemplars, manifest = load_exemplars(), load_manifest()
    return [
        (pattern_request(rule_prompt(rule, exemplars, manifest), tuple(map(_pattern_candidate, found))), found)
        for rule, found in sorted(grouped.items())
        if rule in manifest["rules"] and rule_blocks(manifest, rule, config)
    ]


def stop_request(payload: object, state_root: str | Path | None, config: dict | None = None) -> list[Work] | None:
    """Split across requests, because a cut document reads as reviewed."""
    rows = _stop_rows(payload, state_root)
    return document_work(rows, MAX_DOCUMENT_CHARS, STOP_LABEL) + _pattern_work(rows, config) or None


def _hook_config(payload: object) -> dict:
    cwd = payloads.cwd(payload) if type(payload) is dict else ""
    try:
        return effective_hook_config({}, cwd or None)
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}


def _failure(
    event: str,
    role: str,
    exc: Exception,
    *,
    settings_path: str | Path | None,
    preset_path: str | Path | None,
    locked_paths: tuple[Path, Path] | None = None,
) -> dict:
    reason = _bounded(f"{type(exc).__name__}: {exc}")
    try:
        if locked_paths is None:
            transition = claude_native.fallback_after_luna_failure(
                role, reason, settings_path=settings_path, preset_path=preset_path,
            )
        else:
            transition = claude_native._fallback_after_luna_failure_unlocked(
                role, reason, settings_path=locked_paths[0], preset_path=locked_paths[1],
            )
        message = _bounded(transition["message"])
    except (OSError, ValueError) as fallback_error:
        message = _bounded(f"Luna {role} review unavailable: {reason}. Repair the ADW preset configuration: {fallback_error}")
    if event == "PostToolUse":
        return context(message, event)
    return stop_block(message)


def _built(event: str, payload: object, state_root: str | Path | None, config: dict) -> list[Work] | None:
    if event == "PostToolUse":
        built = post_request(payload)
        return [built] if built else None
    return stop_request(payload, state_root, config)


def _invoke(operation: Any, provider: object | None, request: JudgeRequest) -> JudgeResult | None:
    if provider is None:
        from .luna_provider import LunaJudge
        provider = LunaJudge()
    result = operation.invoke(provider.judge, request)
    if result is not None and not isinstance(result, JudgeResult):
        raise LunaProviderFailure("Luna handler received an invalid judge result", category="worker_protocol")
    return result


def _feedback(request: JudgeRequest, result: JudgeResult, sources: Any) -> str:
    if request.review_kind is ReviewKind.COMMENT:
        return _comment_feedback(result, sources)
    if request.review_kind is ReviewKind.PATTERN:
        found = tuple(map(_pattern_candidate, sources))
        return _pattern_feedback(result, found, request.rule_action, rule=request.rule_name)
    return _document_feedback(result, sources)


def _judge_all(operation: Any, provider: object | None, work: list[Work]) -> list[str] | None:
    """None when Luna is no longer selected, because another preset owns the turn."""
    feedback = []
    for request, sources in work:
        result = _invoke(operation, provider, request)
        if result is None:
            return None
        feedback.append(_feedback(request, result, sources))
    return [text for text in feedback if text]


def _judged(event: str, work: list[Work], provider: object | None, paths: dict[str, Any]) -> list[str] | dict:
    role = "comment" if event == "PostToolUse" else "document"
    try:
        with claude_native.luna_operation(**paths) as operation:
            if operation is None:
                return {}
            try:
                feedback = _judge_all(operation, provider, work)
                return {} if feedback is None else feedback
            except Exception as exc:
                return _failure(event, role, exc, **paths)
    except (OSError, ValueError) as exc:
        return _failure(event, role, exc, **paths)


def _mark_reviewed(payload: object, work: list[Work], state_root: str | Path | None) -> None:
    """Best effort, because a lost mark only costs one more review."""
    rows = [row for _request, sources in work for row in sources]
    try:
        journal.mark_reviewed(payloads.session_id(payload), rows, state_root=state_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def run(
    payload: object,
    *,
    provider: object | None = None,
    state_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> dict:
    event = payloads.exact_string_dict(payload).get("hook_event_name") if type(payload) is dict else ""
    cfg = _hook_config(payload)
    if event not in {"PostToolUse", "Stop"} or not data_boundary_enabled(cfg):
        return {}
    root = state_root if state_root is not None else cfg.get("state_root")
    work = _built(event, payload, root, cfg)
    if work is None:
        return {}
    outcome = _judged(event, work, provider, {"settings_path": settings_path, "preset_path": preset_path})
    if isinstance(outcome, dict):
        return outcome
    if event == "PostToolUse":
        return context(_bounded("\n\n".join(outcome)), event) if outcome else {}
    _mark_reviewed(payload, work, root)
    return stop_block(_bounded("\n\n".join(outcome))) if outcome else {}


def main() -> int:
    write_payload(run(read_payload()))
    return 0
