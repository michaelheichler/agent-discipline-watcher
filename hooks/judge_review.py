from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

from lib import blocker_state, document_review, payloads, session_state
from lib.hookio import PARSE_FAILURE, read_payload
from lib.judge import Verdict, judge
from lib.narration_candidates import candidates
from lib.pattern_semantic import Finding
from lib.pattern_semantic import scan as scan_patterns
from lib.regex_judge import confirm as confirm_judged
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
    if not raw:
        return None
    path = Path(raw)
    if path.suffix not in suffixes or not path.is_file() or _is_session_scratch(path):
        return None
    return path


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _pattern_message(findings: tuple[Finding, ...]) -> str:
    blocking = [item for item in findings if item.blocking]
    lead = (
        "agent-discipline-watcher blocked findings:" if blocking
        else "agent-discipline-watcher is observing these, not blocking."
    )
    lines = [lead]
    lines.extend(
        f"{item.rule}:{item.line}: {item.text[:120]}" + ("" if item.blocking else " (observed)")
        for item in findings
    )
    return "\n".join(lines)


def _pattern_findings(payload: object) -> tuple[Finding, ...]:
    """An absent model server must cost the write nothing at all, because this route runs after the file already landed."""
    path = _target(payload, PROSE_SUFFIXES)
    if path is None:
        return ()
    text = _read(path)
    if text is None:
        return ()
    try:
        return scan_patterns(str(path), text)
    except Exception:
        return ()


def _judged_message(payload: object) -> str:
    """A judged rule never reaches the write path, because only a reader separates an ordinary series from slop cadence."""
    path = _target(payload, PROSE_SUFFIXES)
    if path is None:
        return ""
    text = _read(path)
    if text is None:
        return ""
    try:
        confirmed = confirm_judged(str(path), scan_all(str(path), text))
    except Exception:
        return ""
    if not confirmed:
        return ""
    lines = ["agent-discipline-watcher is observing these, not blocking."]
    lines.extend(f"{item.rule}:{item.line}: {item.text[:120]} (observed)" for item in confirmed)
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


def _notes_for(scope: blocker_state.BlockerScope, path: Path, text: str) -> _Review:
    """An unchanged document is left unread, because a second read costs a call and answers the same thing."""
    key = str(path)
    state = session_state.read_state(scope.session_id, scope.root)
    digest, rounds = document_review.previous(state, key)
    fresh = document_review.digest_of(text)
    if rounds >= document_review.MAX_REVIEW_ROUNDS:
        return _Review((), False, True)
    if fresh == digest:
        return _Review((), False, False)
    notes = document_review.review(key, text)
    session_state.update_state(
        scope.session_id,
        lambda current: document_review.remember(current, key, fresh, rounds + bool(notes)),
        scope.root,
    )
    return _Review(notes, True, not notes)


def _document_message(payload: object) -> str:
    """A whole document is read on the async route because the Stop hook has ten seconds and this call needs more."""
    scope = _review_scope(payload)
    path = _target(payload, PROSE_SUFFIXES)
    if scope is None or path is None:
        return ""
    text = _read(path)
    if text is None:
        return ""
    try:
        review = _notes_for(scope, path, text)
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
        f"{item.candidate.path}:{item.candidate.line}: {item.candidate.text[:120]} ({item.reason})"
        for item in verdicts
    )
    return "\n".join(lines)


def _comment_message(payload: object) -> str:
    path = _target(payload, JUDGED_SUFFIXES)
    if path is None:
        return ""
    text = _read(path)
    if text is None:
        return ""
    verdicts = judge(candidates(str(path), text)[:MAX_CANDIDATES])
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
    code, message = run(read_payload())
    if message:
        print(message, file=sys.stderr)
    sys.exit(code)
