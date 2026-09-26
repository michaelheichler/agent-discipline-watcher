import json
import os
from pathlib import Path

import pytest

from lib import embedding_lease


def test_a_second_session_prevents_the_first_from_unloading(tmp_path: Path) -> None:
    embedding_lease.acquire("alpha", 1000.0, tmp_path, os.getpid())
    embedding_lease.acquire("beta", 1000.0, tmp_path, os.getpid())

    embedding_lease.release("alpha", tmp_path)
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("beta",)
    embedding_lease.release("beta", tmp_path)
    assert embedding_lease.live_sessions(1002.0, tmp_path) == ()


def test_an_expired_lease_stops_pinning_the_model(tmp_path: Path) -> None:
    embedding_lease.acquire("stale", 1000.0, tmp_path, os.getpid())
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
    embedding_lease.acquire("mine", 1000.0, tmp_path, os.getpid())
    row = json.loads((tmp_path / ("mine" + embedding_lease.LEASE_SUFFIX)).read_text(encoding="utf-8"))

    assert row["pid"] == os.getpid()
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("mine",)


def test_a_traversing_session_id_is_refused(tmp_path: Path) -> None:
    for unsafe in ("../escape", "a/b", ""):
        try:
            embedding_lease.acquire(unsafe, 1000.0, tmp_path, os.getpid())
        except ValueError:
            continue
        raise AssertionError(f"accepted unsafe session id {unsafe!r}")


def test_renewal_keeps_one_lease_per_session(tmp_path: Path) -> None:
    embedding_lease.acquire("solo", 1000.0, tmp_path, os.getpid())
    embedding_lease.acquire("solo", 1500.0, tmp_path, os.getpid())

    assert len(list(tmp_path.glob("*" + embedding_lease.LEASE_SUFFIX))) == 1
    assert embedding_lease.live_sessions(1501.0, tmp_path) == ("solo",)


@pytest.mark.parametrize("renewed_at", [float("nan"), float("inf"), float("-inf"), True, 10 ** 400])
def test_invalid_timestamps_cannot_pin_the_worker_forever(tmp_path, renewed_at) -> None:
    path = tmp_path / ("broken" + embedding_lease.LEASE_SUFFIX)
    path.write_text(json.dumps({"pid": os.getpid(), "renewed_at": renewed_at}), encoding="utf-8")

    assert embedding_lease.live_sessions(1000.0, tmp_path) == ()
    assert not path.exists()


def test_registered_roots_are_deduplicated_and_swept_when_idle(tmp_path) -> None:
    server = tmp_path / "server"
    leases = tmp_path / "leases"
    embedding_lease.acquire("alpha", 1000.0, leases, os.getpid())
    embedding_lease.register_root(server, leases)
    embedding_lease.register_root(server, leases / ".")

    assert len(list((server / embedding_lease.ROOTS_DIRECTORY).iterdir())) == 1
    assert embedding_lease.has_live_leases(server, 1001.0)
    assert not embedding_lease.has_live_leases(server, 1000.0 + embedding_lease.LEASE_TTL_SECONDS + 1)
    assert not list((server / embedding_lease.ROOTS_DIRECTORY).iterdir())


def test_renewal_extends_a_lease_past_its_first_ttl(tmp_path: Path) -> None:
    embedding_lease.acquire("long", 1000.0, tmp_path, os.getpid())
    later = 1000.0 + embedding_lease.LEASE_TTL_SECONDS

    assert embedding_lease.renew("long", later, tmp_path) is True
    assert embedding_lease.live_sessions(later + 10.0, tmp_path) == ("long",)


def test_renewal_keeps_the_original_owner_pid(tmp_path: Path) -> None:
    embedding_lease.acquire("owned", 1000.0, tmp_path, os.getpid())

    embedding_lease.renew("owned", 1100.0, tmp_path)
    row = json.loads((tmp_path / ("owned" + embedding_lease.LEASE_SUFFIX)).read_text(encoding="utf-8"))

    assert row["pid"] == os.getpid()
    assert row["renewed_at"] == 1100.0


def test_renewal_never_creates_a_lease_the_turn_did_not_take(tmp_path: Path) -> None:
    assert embedding_lease.renew("absent", 1000.0, tmp_path) is False
    assert not list(tmp_path.glob("*" + embedding_lease.LEASE_SUFFIX))
