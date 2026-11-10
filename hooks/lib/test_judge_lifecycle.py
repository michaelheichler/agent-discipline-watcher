"""Because providers wait, settings changes must invalidate reservations without blocking."""

from collections.abc import Iterator
import json
from pathlib import Path
from queue import Queue
from threading import Event, Thread

import pytest

from lib import claude_native


@pytest.fixture
def luna_paths(tmp_path: Path) -> dict:
    paths = {"settings_path": tmp_path / "settings.json", "preset_path": tmp_path / "preset"}
    claude_native.set_preset("luna", **paths)
    return paths


def test_unchanged_settings_invoke_the_reserved_provider_once(luna_paths: dict) -> None:
    calls = []

    with claude_native.luna_operation(**luna_paths) as operation:
        assert operation is not None
        result = operation.invoke(lambda request: calls.append(request) or "reviewed", "source")

    assert result == "reviewed"
    assert calls == ["source"]


def test_changed_settings_generation_cannot_invoke_a_stale_reservation(luna_paths: dict) -> None:
    calls = []
    with claude_native.luna_operation(**luna_paths) as operation:
        assert operation is not None
        settings = luna_paths["settings_path"]
        value = json.loads(settings.read_text(encoding="utf-8"))
        value["model"] = "changed-selection"
        settings.write_text(json.dumps(value), encoding="utf-8")

        result = operation.invoke(lambda request: calls.append(request), "source")

    assert result is None
    assert calls == []


def test_an_overlapping_reservation_cannot_start_a_second_review(luna_paths: dict) -> None:
    with claude_native.luna_operation(**luna_paths) as first:
        assert first is not None

        with claude_native.luna_operation(**luna_paths) as overlapping:
            assert overlapping is None


def failed_provider(_request: object) -> None:
    raise RuntimeError("offline")


@pytest.fixture
def paths_after_provider_failure(luna_paths: dict) -> dict:
    with pytest.raises(RuntimeError):
        with claude_native.luna_operation(**luna_paths) as operation:
            assert operation is not None
            operation.invoke(failed_provider, "source")
    return luna_paths


def test_a_provider_exception_releases_the_reservation(paths_after_provider_failure: dict) -> None:
    with claude_native.luna_operation(**paths_after_provider_failure) as operation:
        assert operation is not None

        result = operation.invoke(lambda request: request, "recovered")

    assert result == "recovered"


@pytest.fixture
def waiting_provider(luna_paths: dict) -> Iterator[dict]:
    started, release = Event(), Event()

    def provider(request: object) -> object:
        started.set()
        assert release.wait(5)
        return request

    def review() -> None:
        with claude_native.luna_operation(**luna_paths) as operation:
            assert operation is not None
            operation.invoke(provider, "source")

    worker = Thread(target=review, daemon=True)
    worker.start()
    assert started.wait(2)
    try:
        yield luna_paths
    finally:
        release.set()
        worker.join(3)
        assert not worker.is_alive()


@pytest.mark.parametrize("operation", ["status", "preset"])
def test_status_and_preset_updates_finish_before_the_waiting_provider(
    waiting_provider: dict, operation: str,
) -> None:
    results = Queue()
    updates = {"status": lambda: claude_native.status(**waiting_provider)["preset"],
               "preset": lambda: claude_native.set_preset("luna", **waiting_provider)}
    worker = Thread(target=lambda: results.put(updates[operation]()), daemon=True)

    worker.start()

    assert results.get(timeout=2) == "luna"
    worker.join(1)
    assert not worker.is_alive()
