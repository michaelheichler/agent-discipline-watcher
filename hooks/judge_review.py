"""Runs after the write, because an embedding vote is slow."""
from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from lib import embedding_session, language_route, payloads, pattern_vote
from lib.config import effective_hook_config
from lib.hookio import PARSE_FAILURE, read_payload
from lib.host import CODEX_ENV
from lib.scanner import PROSE_EXTS
from lib.temp_scope import outside_project_temp

HOOK_TIMEOUT_SECONDS = 180.0
CODEX_HOOK_TIMEOUT_SECONDS = 10
CODEX_BUDGET_SECONDS = CODEX_HOOK_TIMEOUT_SECONDS - 1.0
VOTE_SECONDS = 60.0
READY_WAIT_SECONDS = HOOK_TIMEOUT_SECONDS - VOTE_SECONDS
def _prose_paths(payload: object) -> list[Path]:
    cwd = payloads.cwd(payload)
    if not cwd:
        return []
    resolved = (payloads.resolved_path(raw, Path(cwd)) for raw in payloads.edited_paths(payload))
    return [
        path for path in resolved
        if path.suffix.lower() in PROSE_EXTS and not outside_project_temp(path, cwd)
    ]


def _config(payload: object) -> dict | None:
    """None keeps embedding local, because remote needs a boundary."""
    try:
        return effective_hook_config({}, payloads.cwd(payload) or None)
    except (OSError, TypeError, ValueError):
        return None


def run(payload: object, *, voter: pattern_vote.Voter = pattern_vote.Voter()) -> None:
    if payload is PARSE_FAILURE or not embedding_session.enabled():
        return
    paths = _prose_paths(payload) if payloads.session_id(payload) else []
    if not paths:
        return
    turn = pattern_vote.turn_for(payload, _config(payload))
    if not pattern_vote.model_ready(turn, READY_WAIT_SECONDS, voter):
        return
    for path in paths:
        pattern_vote.vote(turn, path, voter)


def classify_languages(payload: object, *, judge: language_route.Judge | None = None) -> None:
    """Before the vote, because a cached verdict costs no call and the vote may wait two minutes."""
    if payload is PARSE_FAILURE:
        return
    config = _config(payload)
    paths = tuple(_prose_paths(payload))
    if config is None or not paths:
        return
    write = language_route.ProseWrite(payloads.session_id(payload), paths, config, bool(os.environ.get(CODEX_ENV)))
    language_route.after_write(write, judge)


def _run_quietly(payload: object, work: Callable[[object], None]) -> None:
    """Swallowed, because a failed vote must never block."""
    try:
        work(payload)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: post-write review skipped: {exc}\n")


def after_write(payload: object) -> None:
    for step in (classify_languages, run):
        _run_quietly(payload, step)


def _budget() -> float:
    """Codex runs this inline, because it ignores async hooks."""
    return CODEX_BUDGET_SECONDS if os.environ.get(CODEX_ENV) else HOOK_TIMEOUT_SECONDS


def main(*, work: Callable[[object], None] = after_write) -> int:
    worker = threading.Thread(target=_run_quietly, args=(read_payload(), work), daemon=True)
    worker.start()
    worker.join(_budget())
    return 0


if __name__ == "__main__":
    sys.exit(main())
