"""One heartbeat row per hook and turn, because a row per call made heartbeats 79 percent of a 240,000-row ledger."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from . import session_state
    from .finding_output import safe_component
except ImportError:
    import session_state
    from finding_output import safe_component

HEARTBEAT_DIRNAME = "heartbeats"
SLOW_CALL_MS = 1000


def _first_call(session_id: str, hook: str, turn_id: str, state_root: str | os.PathLike[str] | None) -> bool:
    try:
        directory = session_state.session_directory(session_id, state_root) / HEARTBEAT_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        marker = Path(directory) / f"{safe_component(hook, 'hook')}--{safe_component(turn_id, 'turn')}"
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    except (OSError, ValueError):
        return True
    return True


def worth_a_row(session_id: str, hook: str, turn_id: str, state_root: str | os.PathLike[str] | None, duration_ms: int) -> bool:
    """Slow calls always get a row, so the ledger still shows which hook ate the Stop budget."""
    return duration_ms >= SLOW_CALL_MS or _first_call(session_id, hook, turn_id, state_root)
