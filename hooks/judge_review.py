"""Runs after the write, because an embedding vote is slow."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from lib import embedding_session, journal, payloads, session_state
from lib.config import effective_hook_config
from lib.embedding_client import probe
from lib.hookio import PARSE_FAILURE, read_payload
from lib.pattern_semantic import candidates
from lib.scanner import PROSE_EXTS

embedding_session.CONSUMER_REGISTERED = True

HOOK_TIMEOUT_SECONDS = 180.0
VOTE_SECONDS = 60.0
READY_WAIT_SECONDS = HOOK_TIMEOUT_SECONDS - VOTE_SECONDS
READY_POLL_SECONDS = 1.0
SCRATCH_DIRNAME = "scratchpad"
TEMP_ROOTS = (Path(tempfile.gettempdir()).resolve(), Path("/tmp"), Path("/private/tmp"))


def _is_session_scratch(path: Path) -> bool:
    if SCRATCH_DIRNAME not in path.parts:
        return False
    return any(str(path).startswith(str(root)) for root in TEMP_ROOTS)


def _prose_paths(payload: object) -> list[Path]:
    cwd = payloads.cwd(payload)
    if not cwd:
        return []
    resolved = (payloads.resolved_path(raw, Path(cwd)) for raw in payloads.edited_paths(payload))
    return [path for path in resolved if path.suffix.lower() in PROSE_EXTS and not _is_session_scratch(path)]


def _config(payload: object) -> dict | None:
    """None keeps embedding local, because remote needs a boundary."""
    try:
        return effective_hook_config({}, payloads.cwd(payload) or None)
    except (OSError, TypeError, ValueError):
        return None


def _turn_id(payload: object, session_id: str) -> str:
    """Host turn first, because record.py stamps rows the same way."""
    stored = session_state.read_state(session_id, None).get("turn_id")
    return payloads.turn_id(payload) or (stored if isinstance(stored, str) else "")


class _Turn(NamedTuple):
    session_id: str
    turn_id: str
    config: dict | None


def _vote(turn: _Turn, path: Path) -> None:
    source = journal.current_source(path)
    if source is None:
        return
    digest, text = source
    rows = [
        {"rule": rule, "line": found.line, "text": found.text}
        for rule, voted in sorted(candidates(str(path), text, turn.config).items())
        for found in voted
    ]
    if rows:
        journal.record_patterns(turn.session_id, turn.turn_id, path, rows, content_hash=digest)


def _model_ready(session_id: str, lease_root: str | None) -> bool:
    """Waits, because Stop unloads the model every turn."""
    deadline = time.monotonic() + READY_WAIT_SECONDS
    answered = embedding_session.open_turn(session_id, lease_root)
    embedding_session.renew_turn(session_id, lease_root)
    while answered is None:
        if time.monotonic() + READY_POLL_SECONDS > deadline:
            return False
        time.sleep(READY_POLL_SECONDS)
        answered = probe()
    return True


def run(payload: object) -> None:
    if payload is PARSE_FAILURE or not embedding_session.enabled():
        return
    session_id = payloads.session_id(payload)
    paths = _prose_paths(payload) if session_id else []
    if not paths:
        return
    config = _config(payload)
    if not _model_ready(session_id, embedding_session.lease_root_for(config or {})):
        return
    turn = _Turn(session_id, _turn_id(payload, session_id), config)
    for path in paths:
        _vote(turn, path)


def main() -> int:
    """Always 0, because a failed vote must never block."""
    try:
        run(read_payload())
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: pattern vote skipped: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
