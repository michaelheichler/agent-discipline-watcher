from __future__ import annotations

from pathlib import Path
import os
import time

import session_end
from lib import embedding_lease, embedding_session, session_state


def test_session_end_releases_the_session_lease(tmp_path: Path) -> None:
    config = {"state_root": str(tmp_path / "state")}
    session_state.acquire_session_lease("s1", config["state_root"])

    assert session_end.run({"session_id": "s1"}, config) == {}

    assert session_state.live_session_ids(config["state_root"]) == frozenset()


def test_session_end_releases_embedding_demand_without_stop(tmp_path: Path, monkeypatch) -> None:
    config = {"state_root": str(tmp_path / "state")}
    root = embedding_session.lease_root_for(config)
    embedding_lease.acquire("s1", time.time(), root, os.getpid())
    monkeypatch.setenv(embedding_session.DISABLE_ENV, "1")

    assert session_end.run({"session_id": "s1"}, config) == {}

    assert embedding_lease.live_sessions(time.time(), root) == ()
