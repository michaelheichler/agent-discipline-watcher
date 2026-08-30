from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

from lib import blocker_state, document_review, payloads, reporting, session_state
from lib.hookio import PARSE_FAILURE, read_payload
from lib.judge import Verdict, judge
from lib.narration_candidates import candidates
from lib.pattern_semantic import Finding
from lib.pattern_semantic import scan as scan_patterns
from lib.regex_judge import confirm as confirm_judged
from lib.config import effective_hook_config
from lib.scanner import PROSE_EXTS, scan_all

JUDGED_SUFFIXES = (".py",)
# WHY: The route once accepted only .md, so an HTML or text document never reached the meaning layer at all.
PROSE_SUFFIXES = tuple(sorted(PROSE_EXTS))
WAKE_EXIT_CODE = 2
MAX_CANDIDATES = 40
SCRATCH_DIRNAME = "scratchpad"
TEMP_ROOTS = (Path(tempfile.gettempdir()).resolve(), Path("/tmp"), Path("/private/tmp"))


def _is_session_scratch(path: Path) -> bool:
    # WHY: A throwaway file is not worth a judge call.
    if SCRATCH_DIRNAME not in path.parts:
        return False
    return any(str(path).startswith(str(root)) for root in TEMP_ROOTS)


def _target(payload: object, suffixes: tuple[str, ...]) -> Path | None:
    raw = payloads.file_path(payload)
    cwd = payloads.cwd(payload)
    if not raw or not cwd:
        return None
    try:
        root = Path(cwd).expanduser().resolve(strict=True)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=True)
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if path.suffix not in suffixes or _is_session_scratch(path):
        return None
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
    except OSError:
        return None
    return path
def _review_config(payload: object) -> dict | None:
    """Permit model review only when project policy explicitly allows source egress."""
    try:
        config = effective_hook_config({}, payloads.cwd(payload) or None)
    except (OSError, TypeError, ValueError):
        return None
    boundary = config.get("data_boundary")
    return config if isinstance(boundary, dict) and boundary.get("enabled") is True else None


def _read(path: Path, cwd: str) -> str | None:
    root_fd = -1
    descriptor = -1
    try:
        root = Path(cwd).expanduser().resolve(strict=True)
        relative = path.resolve(strict=True).relative_to(root)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(root, directory_flags)
        descriptor = root_fd
        for part in relative.parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            if descriptor != root_fd:
                os.close(descriptor)
            descriptor = child
        leaf = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        try:
            metadata = os.fstat(leaf)
            if not stat.S_ISREG(metadata.st_mode):
                return None
            raw = os.read(leaf, 1_000_001)
            after = os.fstat(leaf)
            if (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino) or len(raw) > 1_000_000:
                return None
            return raw.decode("utf-8")
        finally:
            os.close(leaf)
    except (OSError, UnicodeDecodeError, RuntimeError, ValueError):
        return None
    finally:
        if descriptor >= 0 and descriptor != root_fd:
            os.close(descriptor)
        if root_fd >= 0:
            os.close(root_fd)


def _pattern_message(findings: tuple[Finding, ...]) -> str:
    blocking = [item for item in findings if item.blocking]
    lead = (
        "agent-discipline-watcher blocked findings:" if blocking
        else "agent-discipline-watcher is observing these, not blocking."
    )
    lines = [lead]
    lines.extend(
        f"{reporting._safe_text(item.rule)}:{item.line}: {reporting._safe_text(item.text[:120])}"
        + ("" if item.blocking else " (observed)")
        for item in findings
    )
    return "\n".join(lines)


def _pattern_findings(payload: object) -> tuple[Finding, ...]:
    """Skip model-backed source review when project egress policy is disabled."""
    config = _review_config(payload)
    if config is None:
        return ()
    path = _target(payload, PROSE_SUFFIXES)
    if path is None:
        return ()
    text = _read(path, payloads.cwd(payload))
    if text is None:
        return ()
    try:
        return scan_patterns(str(path), text, config)
    except Exception:
        return ()


def _judged_message(payload: object) -> str:
    """A judged rule never reaches the write path, because only a reader separates an ordinary series from slop cadence."""
    config = _review_config(payload)
    if config is None:
        return ""
    path = _target(payload, PROSE_SUFFIXES)
    if path is None:
        return ""
    text = _read(path, payloads.cwd(payload))
    if text is None:
        return ""
    try:
        confirmed = confirm_judged(str(path), scan_all(str(path), text, config))
    except Exception:
        return ""
    if not confirmed:
        return ""
    lines = ["agent-discipline-watcher is observing these, not blocking."]
    lines.extend(
        f"{reporting._safe_text(item.rule)}:{item.line}: {reporting._safe_text(item.text[:120])} (observed)"
        for item in confirmed
    )
    return "\n".join(lines)


def _review_scope(payload: object) -> blocker_state.BlockerScope | None:
    session_id = payloads.session_id(payload) if isinstance(payload, dict) else ""
    if not session_id:
        return None
    return blocker_state.BlockerScope(session_id, blocker_state.scope(payload), None)


class _Review(NamedTuple):
    notes: tuple[document_review.Note, ...]
    read: bool
    release: bool


def _claim_reading(scope: blocker_state.BlockerScope, key: str, fresh: str) -> tuple[str, int]:
    # WHY: A read runs for tens of seconds. Spend the round first.
    before: list[tuple[str, int]] = []

    def mutate(state: dict) -> dict:
        digest, rounds = document_review.previous(state, key)
        before.append((digest, rounds))
        if rounds >= document_review.MAX_REVIEW_ROUNDS or fresh == digest:
            return state
        return document_review.remember(state, key, fresh, rounds + 1)

    session_state.update_state(scope.session_id, mutate, scope.root)
    return before[0]


def _notes_for(scope: blocker_state.BlockerScope, path: Path, text: str, cfg: dict) -> _Review:
    """An unchanged document is left unread, because a second read costs a call and answers the same thing."""
    key = str(path)
    fresh = document_review.digest_of(text)
    digest, rounds = _claim_reading(scope, key, fresh)
    if rounds >= document_review.MAX_REVIEW_ROUNDS:
        return _Review((), False, True)
    if fresh == digest:
        return _Review((), False, False)
    notes = document_review.review(key, text, cfg)
    return _Review(notes, True, not notes)


def _document_message(payload: object) -> str:
    """A whole document is read on the async route because the Stop hook has ten seconds and this call needs more."""
    config = _review_config(payload)
    if config is None:
        return ""
    scope = _review_scope(payload)
    path = _target(payload, PROSE_SUFFIXES)
    if scope is None or path is None:
        return ""
    text = _read(path, payloads.cwd(payload))
    if text is None:
        return ""
    try:
        review = _notes_for(scope, path, text, config)
    except Exception:
        return ""
    key = document_review.BLOCKER_KEY_PREFIX + str(path)
    if review.release:
        blocker_state.clear_pending(scope, key)
    if not review.notes:
        return ""
    reason = document_review.message(str(path), review.notes)
    blocker_state.set_pending(scope, key, reason)
    return reason


def _message(verdicts: tuple[Verdict, ...]) -> str:
    lines = [
        "agent-discipline-watcher: these comments describe the code instead of stating why.",
        "Rewrite each as one short WHY line, or delete it.",
    ]
    lines.extend(
        f"{reporting._safe_text(item.candidate.path).replace(chr(10), ' ')}:{item.candidate.line}: "
        f"{reporting._safe_text(item.candidate.text[:120]).replace(chr(10), ' ')} "
        f"({reporting._safe_text(item.reason).replace(chr(10), ' ')})"
        for item in verdicts
    )
    return "\n".join(lines)


def _comment_message(payload: object) -> str:
    cfg = _review_config(payload)
    if cfg is None:
        return ""
    path = _target(payload, JUDGED_SUFFIXES)
    if path is None:
        return ""
    text = _read(path, payloads.cwd(payload))
    if text is None:
        return ""
    verdicts = judge(candidates(str(path), text)[:MAX_CANDIDATES], cfg.get("adw_model"))
    narrating = tuple(item for item in verdicts if item.narrates) if verdicts else ()
    return _message(narrating) if narrating else ""


def run(payload: object) -> tuple[int, str]:
    if payload is PARSE_FAILURE:
        return 0, ""
    findings = _pattern_findings(payload)
    messages = [
        message
        for message in (_comment_message(payload), _judged_message(payload), _document_message(payload))
        if message
    ]
    if findings:
        messages.append(_pattern_message(findings))
    if not messages:
        return 0, ""
    return WAKE_EXIT_CODE, "\n".join(messages)


if __name__ == "__main__":
    _code, message = run(read_payload())
    if message:
        print(message, file=sys.stderr)
        print(json.dumps({"systemMessage": message}, ensure_ascii=True))
    else:
        print("{}")
    sys.exit(0)
