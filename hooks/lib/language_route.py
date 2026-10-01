"""Kept off the write path, because a Luna call takes longer than a synchronous hook may wait (decision Q17)."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from . import journal, session_state
from .document_review import data_boundary_enabled
from .language_verdict import Judge, StateRoot, Verdicts, cached_language, classify, unresolved
from .luna_runtime import installed
from .prose_language import allowed_languages, paragraph_languages

QUEUE_KEY = "language_queue"
MAX_QUEUED = 64
LUNA_TIMEOUT_SECONDS = 30.0
HOOKS_ROOT = Path(__file__).resolve().parents[1]
Spawner = Callable[[str, StateRoot], None]


def luna_judge() -> Judge | None:
    """Bounded to 30 s, because the same async hook still owes the embedding vote its two minutes."""
    if not installed():
        return None
    from .luna_provider import LunaJudge  # pylint: disable=import-outside-toplevel
    return LunaJudge(timeout_seconds=LUNA_TIMEOUT_SECONDS).judge


def _state_root(config: dict) -> StateRoot:
    root = config.get("state_root")
    return root if isinstance(root, str) and root else None


def pending_paragraphs(paths: Iterable[Path], config: dict) -> list[str]:
    allowed = allowed_languages(config)
    root = _state_root(config)
    texts: list[str] = []
    for path in paths:
        source = journal.current_source(path)
        if source is not None:
            texts.extend(unresolved(paragraph_languages(source[1], allowed), root))
    return list(dict.fromkeys(texts))


class ProseWrite(NamedTuple):
    session_id: str
    paths: tuple[Path, ...]
    config: dict
    codex: bool


def after_write(write: ProseWrite, judge: Judge | None = None) -> None:
    """Codex queues, because its hooks run inline and must never wait on Luna."""
    if not write.session_id or not data_boundary_enabled(write.config):
        return
    pending = pending_paragraphs(write.paths, write.config)
    if not pending:
        return
    root = _state_root(write.config)
    if write.codex:
        enqueue(write.session_id, pending, root)
        return
    chosen = judge or luna_judge()
    if chosen is not None:
        classify(pending, chosen, root)


def _queued(state: dict) -> list[str]:
    queued = state.get(QUEUE_KEY)
    return [text for text in queued if isinstance(text, str)] if isinstance(queued, list) else []


def enqueue(session_id: str, texts: list[str], root: StateRoot) -> None:
    def add(state: dict) -> dict:
        merged = list(dict.fromkeys([*_queued(state), *texts]))[-MAX_QUEUED:]
        return {**state, QUEUE_KEY: merged}
    session_state.update_state(session_id, add, root)


def take_queue(session_id: str, root: StateRoot) -> list[str]:
    taken: list[str] = []

    def drain_state(state: dict) -> dict:
        taken.extend(_queued(state))
        return {key: value for key, value in state.items() if key != QUEUE_KEY}
    session_state.update_state(session_id, drain_state, root)
    return taken


def _spawn(session_id: str, root: StateRoot) -> None:
    """Own session, because the prompt hook exits before Luna answers."""
    arguments = [sys.executable, "-m", "lib.language_route", session_id, *([str(root)] if root else [])]
    environment = {**os.environ, "PYTHONPATH": str(HOOKS_ROOT)}
    subprocess.Popen(  # pylint: disable=consider-using-with
        arguments, cwd=HOOKS_ROOT, env=environment, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def start_drain(session_id: str, config: dict | None, spawn: Spawner = _spawn) -> bool:
    """Swallowed, because a failed spawn must not break the prompt gate."""
    root = _state_root(config or {})
    try:
        if not session_id or not _queued(session_state.read_state(session_id, root)):
            return False
        spawn(session_id, root)
    except (OSError, ValueError):
        return False
    return True


def drain(session_id: str, root: StateRoot, judge: Judge | None = None) -> Verdicts:
    pending = [text for text in take_queue(session_id, root) if cached_language(text, root) is None]
    if not pending:
        return {}
    chosen = judge or luna_judge()
    return classify(pending, chosen, root) if chosen is not None else {}


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        return 2
    drain(arguments[0], arguments[1] if len(arguments) > 1 else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
