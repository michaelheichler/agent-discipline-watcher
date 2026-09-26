"""Runs after the write, because an embedding vote is slow."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from lib import embedding_session, payloads, pattern_vote
from lib.config import effective_hook_config
from lib.hookio import PARSE_FAILURE, read_payload
from lib.host import CODEX_ENV
from lib.scanner import PROSE_EXTS

HOOK_TIMEOUT_SECONDS = 180.0
CODEX_HOOK_TIMEOUT_SECONDS = 10
CODEX_BUDGET_SECONDS = CODEX_HOOK_TIMEOUT_SECONDS - 1.0
VOTE_SECONDS = 60.0
READY_WAIT_SECONDS = HOOK_TIMEOUT_SECONDS - VOTE_SECONDS
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


def run(payload: object) -> None:
    if payload is PARSE_FAILURE or not embedding_session.enabled():
        return
    paths = _prose_paths(payload) if payloads.session_id(payload) else []
    if not paths:
        return
    turn = pattern_vote.turn_for(payload, _config(payload))
    if not pattern_vote.model_ready(turn, READY_WAIT_SECONDS):
        return
    for path in paths:
        pattern_vote.vote(turn, path)


def _run_quietly(payload: object) -> None:
    """Swallowed, because a failed vote must never block."""
    try:
        run(payload)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: pattern vote skipped: {exc}\n")


def _budget() -> float:
    """Codex runs this inline, because it ignores async hooks."""
    return CODEX_BUDGET_SECONDS if os.environ.get(CODEX_ENV) else HOOK_TIMEOUT_SECONDS


def main() -> int:
    worker = threading.Thread(target=_run_quietly, args=(read_payload(),), daemon=True)
    worker.start()
    worker.join(_budget())
    return 0


if __name__ == "__main__":
    sys.exit(main())
