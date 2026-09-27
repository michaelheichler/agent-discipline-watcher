"""Declared as the only seam into a host, because a shared entry script that imports an adapter makes that host mandatory everywhere."""
from __future__ import annotations

from typing import Any, Callable, NamedTuple

try:
    from . import host
except ImportError:
    import host


class TurnAdapter(NamedTuple):
    """Pair the call with its flag because a caller must not learn which host answered."""

    review: Callable[..., dict]
    reviews_turns: bool


def _no_review(_payload: object, **_options: Any) -> dict:
    return {}


NULL = TurnAdapter(review=_no_review, reviews_turns=False)


def _codex() -> TurnAdapter:
    """Imported inside the call because a host absent from this machine must not break the shared script."""
    try:
        from . import codex_luna
    except ImportError:
        import codex_luna
    return TurnAdapter(review=codex_luna.review, reviews_turns=True)


def _on_claude(environment: Any) -> bool:
    """Gated, because only Claude reads Claude settings."""
    try:
        return host.current_host(environment) == host.CLAUDE
    except host.UnknownHostError:
        return False


def _claude_default() -> Any:
    try:
        from . import claude_default
    except ImportError:
        import claude_default
    return claude_default


def prepare_session(environment: Any = None) -> None:
    """Tolerant, because a vendored Codex tree lacks the adapter."""
    if not _on_claude(environment):
        return
    try:
        adapter = _claude_default()
    except ImportError:
        return
    adapter.ensure_with_notice()


def for_turn(environment: Any = None, *, injected_provider: bool = False) -> TurnAdapter:
    """Honour an injected provider because a caller supplying one has already chosen the reviewer."""
    if injected_provider or host.is_codex_host(environment):
        return _codex()
    return NULL
