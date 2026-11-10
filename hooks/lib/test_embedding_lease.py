import json
import os
import subprocess
import sys
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


def test_canonical_lease_root_registrations_are_deduplicated(tmp_path) -> None:
    server = tmp_path / "server"
    leases = tmp_path / "leases"
    embedding_lease.acquire("alpha", 1000.0, leases, os.getpid())
    embedding_lease.register_root(server, leases)

    embedding_lease.register_root(server, leases / ".")

    assert len(list((server / embedding_lease.ROOTS_DIRECTORY).iterdir())) == 1


def test_idle_lease_directories_remain_discoverable_without_pinning_the_worker(tmp_path) -> None:
    server = tmp_path / "server"
    leases = tmp_path / "leases"
    embedding_lease.acquire("alpha", 1000.0, leases, os.getpid())
    embedding_lease.register_root(server, leases)
    expired = 1000.0 + embedding_lease.LEASE_TTL_SECONDS + 1

    live = embedding_lease.has_live_leases(server, expired)

    assert live is False
    assert len(list((server / embedding_lease.ROOTS_DIRECTORY).iterdir())) == 1
    assert list(leases.iterdir()) == []


def test_a_removed_lease_directory_loses_its_registration(tmp_path) -> None:
    server = tmp_path / "server"
    leases = tmp_path / "leases"
    leases.mkdir()
    embedding_lease.register_root(server, leases)
    leases.rmdir()

    live = embedding_lease.has_live_leases(server, 1001.0)

    assert live is False
    assert list((server / embedding_lease.ROOTS_DIRECTORY).iterdir()) == []


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


def test_a_lease_records_its_owners_process_start(tmp_path) -> None:
    embedding_lease.acquire("identified", 1000.0, tmp_path, os.getpid())

    row = json.loads((tmp_path / ("identified" + embedding_lease.LEASE_SUFFIX)).read_text())
    assert row["process_start"]


def test_a_recycled_live_pid_cannot_preserve_a_stale_lease(tmp_path) -> None:
    embedding_lease.acquire("stale", 1000.0, tmp_path, os.getpid())
    path = tmp_path / ("stale" + embedding_lease.LEASE_SUFFIX)
    row = json.loads(path.read_text())
    row["process_start"] = "previous-process-start"
    path.write_text(json.dumps(row), encoding="utf-8")

    sessions = embedding_lease.live_sessions(1001.0, tmp_path)

    assert sessions == ()
    assert not path.exists()


@pytest.mark.parametrize("token", [None, ""])
def test_an_unknown_process_identity_keeps_an_unexpired_lease(tmp_path, token) -> None:
    embedding_lease.acquire("unknown", 1000.0, tmp_path, os.getpid())
    path = tmp_path / ("unknown" + embedding_lease.LEASE_SUFFIX)
    row = json.loads(path.read_text())
    row["process_start"] = token
    path.write_text(json.dumps(row), encoding="utf-8")

    sessions = embedding_lease.live_sessions(1001.0, tmp_path)

    assert sessions == ("unknown",)
    assert path.exists()


def test_renewal_preserves_the_original_owners_start_identity(tmp_path) -> None:
    embedding_lease.acquire("owned", 1000.0, tmp_path, os.getpid())
    path = tmp_path / ("owned" + embedding_lease.LEASE_SUFFIX)
    row = json.loads(path.read_text())
    row["process_start"] = "another-process-start"
    path.write_text(json.dumps(row), encoding="utf-8")

    renewed = embedding_lease.renew("owned", 1100.0, tmp_path)

    assert renewed is True
    assert json.loads(path.read_text())["process_start"] == row["process_start"]


def test_registered_roots_and_leases_keep_the_original_owner(tmp_path) -> None:
    leases = tmp_path / "leases"
    server = tmp_path / "server"
    embedding_lease.acquire("session", 1000.0, leases, os.getpid())
    embedding_lease.register_root(server, leases)
    [path] = leases.glob("*" + embedding_lease.LEASE_SUFFIX)

    row = embedding_lease.read_lease(path)

    assert embedding_lease.registered_roots(server) == [leases.resolve()]
    assert row["session_id"] == "session"
    assert row["pid"] == os.getpid()
    assert row["renewed_at"] == 1000.0


def test_forged_lease_registration_cannot_authorize_cleanup(tmp_path) -> None:
    leases = tmp_path / "leases"
    server = tmp_path / "server"
    embedding_lease.register_root(server, leases)
    [registration] = (server / embedding_lease.ROOTS_DIRECTORY).glob("*" + embedding_lease.ROOT_SUFFIX)
    registration.rename(registration.with_name("forged" + embedding_lease.ROOT_SUFFIX))

    with pytest.raises(RuntimeError):
        embedding_lease.registered_roots(server)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS batches process identities with ps")
@pytest.mark.parametrize("lookup_fails", [pytest.param(False, id="known-owner"), pytest.param(True, id="unknown-owner")])
def test_one_identity_sweep_preserves_current_leases_and_removes_expired_rows(tmp_path, monkeypatch, lookup_fails) -> None:
    server = tmp_path / "server"
    roots = [tmp_path / "one", tmp_path / "two"]
    for index in range(40):
        root = roots[index % 2]
        embedding_lease.acquire(f"session-{index}", 1000.0, root, os.getpid())
        embedding_lease.register_root(server, root)
    embedding_lease.acquire("expired", 0.0, roots[0], os.getpid())
    run = subprocess.run
    queries = []

    def query(*args, **kwargs):
        queries.append(args[0])
        if lookup_fails:
            raise subprocess.TimeoutExpired(args[0], 1)
        return run(*args, check=kwargs.pop("check"), **kwargs)

    monkeypatch.setattr(subprocess, "run", query)

    assert embedding_lease.has_live_leases(server, 1001.0) is True
    assert queries == [("ps", "-o", "pid=,lstart=", "-p", str(os.getpid()))]
    assert len(list(roots[0].glob("*" + embedding_lease.LEASE_SUFFIX))) == 20
    assert len(list(roots[1].glob("*" + embedding_lease.LEASE_SUFFIX))) == 20
