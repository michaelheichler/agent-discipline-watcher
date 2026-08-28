from __future__ import annotations

from pathlib import Path

import session_end
from lib import session_state


def test_session_end_releases_the_session_lease(tmp_path: Path) -> None:
    config = {"state_root": str(tmp_path / "state")}
    session_state.acquire_session_lease("s1", config["state_root"])

    assert session_end.run({"session_id": "s1"}, config) == {}

    assert session_state.live_session_ids(config["state_root"]) == frozenset()
