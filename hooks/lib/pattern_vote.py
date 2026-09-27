"""Shared, because JudgeReview and OMP journal one vote."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from . import embedding_session, journal, payloads, session_state
from .embedding_client import probe
from .pattern_semantic import candidates

embedding_session.CONSUMER_REGISTERED = True

READY_POLL_SECONDS = 1.0


class VoteTurn(NamedTuple):
    session_id: str
    turn_id: str
    config: dict | None


class Voter(NamedTuple):
    open_turn: Callable[[str, str | None], str | None] = embedding_session.open_turn
    renew_turn: Callable[[str, str | None], bool] = embedding_session.renew_turn
    probe: Callable[[], str | None] = probe
    candidates: Callable[..., dict] = candidates


def _state_root(config: dict | None) -> str | None:
    root = (config or {}).get("state_root")
    return root if isinstance(root, str) else None


def turn_for(payload: object, config: dict | None) -> VoteTurn:
    """Host turn first, because record.py stamps rows the same way."""
    session_id = payloads.session_id(payload)
    stored = session_state.read_state(session_id, _state_root(config)).get("turn_id")
    turn_id = payloads.turn_id(payload) or (stored if isinstance(stored, str) else "")
    return VoteTurn(session_id, turn_id, config)


def warm(session_id: str, config: dict | None, voter: Voter = Voter()) -> None:
    """Early, because a Codex vote gets 9 s and a load takes more."""
    if not session_id or not embedding_session.enabled() or not embedding_session.provisioned():
        return
    voter.open_turn(session_id, embedding_session.lease_root_for(config or {}))


def model_ready(turn: VoteTurn, wait_seconds: float, voter: Voter = Voter()) -> bool:
    """Waits, because Stop unloads the model every turn."""
    deadline = time.monotonic() + wait_seconds
    lease_root = embedding_session.lease_root_for(turn.config or {})
    answered = voter.open_turn(turn.session_id, lease_root)
    voter.renew_turn(turn.session_id, lease_root)
    while answered is None:
        if time.monotonic() + READY_POLL_SECONDS > deadline:
            return False
        time.sleep(READY_POLL_SECONDS)
        answered = voter.probe()
    return True


def vote(turn: VoteTurn, path: Path, voter: Voter = Voter()) -> list[dict]:
    source = journal.current_source(path)
    if source is None:
        return []
    digest, text = source
    rows = [
        {"rule": rule, "line": found.line, "text": found.text}
        for rule, voted in sorted(voter.candidates(str(path), text, turn.config).items())
        for found in voted
    ]
    if not rows:
        return []
    return journal.record_patterns(
        turn.session_id, turn.turn_id, path, rows, content_hash=digest, state_root=_state_root(turn.config),
    )
