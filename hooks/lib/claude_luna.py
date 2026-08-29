"""Run ADW's Luna-backed Claude command handlers."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from . import claude_journal, claude_native, payloads
from .config import effective_hook_config
from .document_review import request_for as document_request
from .hookio import context, read_payload, stop_block, write_payload
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .luna_storage import LunaProviderFailure
from .narration_candidates import candidates


EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "Bash"})
MAX_FEEDBACK_CHARS = 900
MAX_DOCUMENT_CHARS = 24_000
MAX_LIVE_CANDIDATES = claude_journal.MAX_ROWS
MAX_LIVE_PATHS = 32
MAX_LIVE_PATH_CHARS = 4096
MAX_LIVE_FILE_BYTES = 128 * 1024
MAX_LIVE_SCAN_BYTES = 512 * 1024
MAX_LIVE_RAW_EDIT_BYTES = 512 * 1024


def _bounded(value: object) -> str:
    return " ".join(str(value).split())[:MAX_FEEDBACK_CHARS]


def _bounded_file_text(path: Path, limit: int) -> tuple[str, int] | None:
    """Read one regular file through no-follow directory descriptors."""
    descriptor = -1
    try:
        target = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        if not target.is_absolute():
            target = Path.cwd() / target
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in target.parent.parts:
            if part in (target.anchor, ""):
                continue
            if part in (".", ".."):
                raise ValueError("unsafe path component")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    raise ValueError("live candidate parent is not a directory")
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        leaf = os.stat(target.name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(leaf.st_mode):
            return None
        handle = os.open(target.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=descriptor)
        try:
            opened = os.fstat(handle)
            if _file_metadata(opened) != _file_metadata(leaf) or opened.st_size > limit:
                return None
            data = bytearray()
            while len(data) <= limit:
                chunk = os.read(handle, min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > limit:
                return None
            final = os.fstat(handle)
            if _file_metadata(final) != _file_metadata(opened) or len(data) != final.st_size:
                return None
        finally:
            os.close(handle)
        try:
            return bytes(data).decode("utf-8"), len(data)
        except UnicodeDecodeError:
            return None
    except (OSError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _file_metadata(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _byte_size(value: str) -> int:
    # Avoid allocating an encoded copy for obviously huge host payloads.
    if len(value) > MAX_LIVE_RAW_EDIT_BYTES:
        return MAX_LIVE_RAW_EDIT_BYTES + 1
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        # Host JSON may contain lone surrogates; treat them as malformed input.
        return MAX_LIVE_RAW_EDIT_BYTES + 1


def _bounded_raw_edit(payload: object) -> bool:
    """Reject pathological patch/Bash bodies before edited_paths parses them."""
    if type(payload) is not dict:
        return False
    tool = payloads.tool_name(payload)
    if tool not in {"apply_patch", "Bash"}:
        return True
    fields = payloads.exact_string_dict(payload)
    tool_input: dict[str, object] = {}
    for key in ("tool_input", "toolInput", "input"):
        candidate = payloads.exact_string_dict(fields.get(key))
        if candidate:
            tool_input = candidate
            break
    for key in ("patch", "command", "input"):
        value = tool_input.get(key)
        if type(value) is str:
            if _byte_size(value) > MAX_LIVE_RAW_EDIT_BYTES:
                return False
            marker_count = sum(value.count(marker) for marker in (
                "*** Add File:", "*** Update File:", "*** Delete File:", "*** Move to:",
            ))
            if marker_count > MAX_LIVE_PATHS:
                return False
            if tool == "Bash" and value.count("\n") > MAX_LIVE_PATHS * 8:
                return False
            return True
        if type(value) is list:
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


def _read_candidates(payload: object) -> tuple[Candidate, ...]:
    if type(payload) is not dict or payloads.tool_name(payload) not in EDIT_TOOLS:
        return ()
    cwd_text = payloads.cwd(payload)
    if not cwd_text:
        return ()
    cwd = Path(cwd_text)
    found: list[Candidate] = []
    paths = _safe_edited_paths(payload)
    scanned = 0
    for raw_path in paths:
        if scanned >= MAX_LIVE_SCAN_BYTES:
            break
        if not isinstance(raw_path, str) or len(raw_path) > MAX_LIVE_PATH_CHARS:
            continue
        try:
            path = payloads.resolved_path(raw_path, cwd)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if path.suffix.lower() != ".py":
            continue
        limit = min(MAX_LIVE_FILE_BYTES, MAX_LIVE_SCAN_BYTES - scanned)
        bounded = _bounded_file_text(path, limit)
        if bounded is None:
            continue
        text, read_bytes = bounded
        scanned += read_bytes
        for candidate in candidates(str(path), text):
            found.append(Candidate(candidate.path, candidate.line, candidate.text[:claude_journal.MAX_CANDIDATE_CHARS]))
            if len(found) >= MAX_LIVE_CANDIDATES:
                return tuple(found)
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
        return claude_journal.read_for_stop(session_id, state_root=state_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def stop_request(payload: object, state_root: str | Path | None) -> tuple[JudgeRequest, list[dict[str, Any]]] | None:
    rows = _stop_rows(payload, state_root)
    if not rows:
        return None
    documents = [
        f"Path: {row['path']}\n\n{row['source_context']}"
        for row in rows
        if row.get("path") and row.get("source_context")
    ]
    source = "\n\n".join(documents)[:MAX_DOCUMENT_CHARS]
    if not source.strip():
        return None
    return document_request("ADW current-session journal", source), rows


def _comment_feedback(result: JudgeResult, found: tuple[Candidate, ...]) -> str:
    rows = result.payload.get("items")
    if not isinstance(rows, list):
        return ""
    feedback = []
    for row in rows:
        if not isinstance(row, dict) or row.get("verdict") != "describes_code":
            continue
        index = row.get("index")
        if type(index) is not int or not 0 <= index < len(found):
            continue
        feedback.append(f"{found[index].path}:{found[index].line}: {_bounded(row.get('reason', 'Rewrite this comment.'))}")
    return _bounded("ADW Luna comment review: " + " | ".join(feedback)) if feedback else ""


def _document_feedback(result: JudgeResult, rows: list[dict[str, Any]]) -> str:
    notes = result.payload.get("notes")
    if not isinstance(notes, list):
        return ""
    feedback = []
    for row in notes:
        if not isinstance(row, dict) or not row.get("problem"):
            continue
        quote = _bounded(row.get("quote", ""))
        problem = _bounded(row.get("problem", ""))
        fix = _bounded(row.get("fix", "Fix the named document issue."))
        feedback.append(f"{quote}: {problem} Fix: {fix}")
    return _bounded("ADW Luna document review: " + " | ".join(feedback)) if feedback else ""


def _state_root(payload: object, explicit: str | Path | None) -> str | Path | None:
    if explicit is not None:
        return explicit
    cwd = payloads.cwd(payload) if type(payload) is dict else ""
    try:
        return effective_hook_config({}, cwd or None).get("state_root")
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


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


def run(
    payload: object,
    *,
    provider: object | None = None,
    state_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> dict:
    event = payloads.exact_string_dict(payload).get("hook_event_name") if type(payload) is dict else ""
    if event not in {"PostToolUse", "Stop"}:
        return {}
    role = "comment" if event == "PostToolUse" else "document"
    if event == "PostToolUse":
        built = post_request(payload)
    else:
        built = stop_request(payload, _state_root(payload, state_root))
    if built is None:
        return {}
    request = built[0]
    try:
        with claude_native.luna_operation(
            settings_path=settings_path, preset_path=preset_path,
        ) as operation:
            if operation is None:
                return {}
            if provider is None:
                from .luna_provider import LunaJudge
                provider = LunaJudge()
            try:
                result = operation.invoke(provider.judge, request)
                if result is None:
                    return {}
                if not isinstance(result, JudgeResult):
                    raise LunaProviderFailure("Luna handler received an invalid judge result", category="worker_protocol")
            except Exception as exc:
                return _failure(
                    event, role, exc, settings_path=settings_path, preset_path=preset_path,
                )
    except (OSError, ValueError) as exc:
        return _failure(event, role, exc, settings_path=settings_path, preset_path=preset_path)
    if request.review_kind is ReviewKind.COMMENT:
        feedback = _comment_feedback(result, built[1])
        return context(feedback, event) if feedback else {}
    feedback = _document_feedback(result, built[1])
    return stop_block(feedback) if feedback else {}


def main() -> int:
    write_payload(run(read_payload()))
    return 0
