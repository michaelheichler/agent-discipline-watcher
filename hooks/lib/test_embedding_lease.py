import json
import os
from pathlib import Path

from lib import embedding_lease


def test_a_second_session_prevents_the_first_from_unloading(tmp_path: Path) -> None:
    embedding_lease.acquire("alpha", 1000.0, tmp_path)
    embedding_lease.acquire("beta", 1000.0, tmp_path)

    assert embedding_lease.may_unload("alpha", 1001.0, tmp_path) is False
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("beta",)
    assert embedding_lease.may_unload("beta", 1002.0, tmp_path) is True


def test_an_expired_lease_stops_pinning_the_model(tmp_path: Path) -> None:
    embedding_lease.acquire("stale", 1000.0, tmp_path)
    expired = 1000.0 + embedding_lease.LEASE_TTL_SECONDS + 1

    assert embedding_lease.live_sessions(expired, tmp_path) == ()
    assert not list(tmp_path.glob("*" + embedding_lease.LEASE_SUFFIX))


def test_a_dead_owner_releases_the_model(tmp_path: Path) -> None:
    path = tmp_path / ("ghost" + embedding_lease.LEASE_SUFFIX)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session_id": "ghost", "pid": 2 ** 22, "renewed_at": 1000.0}),
        encoding="utf-8",
    )

    assert embedding_lease.live_sessions(1001.0, tmp_path) == ()


def test_a_live_owner_keeps_the_model(tmp_path: Path) -> None:
    embedding_lease.acquire("mine", 1000.0, tmp_path)
    row = json.loads((tmp_path / ("mine" + embedding_lease.LEASE_SUFFIX)).read_text(encoding="utf-8"))

    assert row["pid"] == os.getpid()
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("mine",)


def test_a_traversing_session_id_is_refused(tmp_path: Path) -> None:
    for unsafe in ("../escape", "a/b", ""):
        try:
            embedding_lease.acquire(unsafe, 1000.0, tmp_path)
        except ValueError:
            continue
        raise AssertionError(f"accepted unsafe session id {unsafe!r}")


def test_renewal_keeps_one_lease_per_session(tmp_path: Path) -> None:
    embedding_lease.acquire("solo", 1000.0, tmp_path)
    embedding_lease.acquire("solo", 1500.0, tmp_path)

    assert len(list(tmp_path.glob("*" + embedding_lease.LEASE_SUFFIX))) == 1
    assert embedding_lease.live_sessions(1501.0, tmp_path) == ("solo",)
