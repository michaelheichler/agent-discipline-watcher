from __future__ import annotations

import fcntl
import json
import os
import threading

from lib import embedding_worker_watch as watch

PERIOD = 0.02


def _record(root, pid: int) -> None:
    (root / watch.RECORD_NAME).write_text(json.dumps({"pid": pid}), encoding="utf-8")


def _hold_supervisor_lock(root):
    handle = (root / watch.SUPERVISOR_LOCK_NAME).open("a", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _watch_in_background(root) -> threading.Event:
    stopped = threading.Event()
    threading.Thread(target=watch.watch, args=(root, stopped.set, PERIOD), daemon=True).start()
    return stopped


def test_a_record_naming_this_pid_is_recognised(tmp_path) -> None:
    _record(tmp_path, os.getpid())

    assert watch.named_in_record(tmp_path, os.getpid())


def test_a_missing_or_foreign_record_is_not_ownership(tmp_path) -> None:
    assert not watch.named_in_record(tmp_path, os.getpid())
    _record(tmp_path, os.getpid() + 1)
    assert not watch.named_in_record(tmp_path, os.getpid())
    (tmp_path / watch.RECORD_NAME).write_text("{", encoding="utf-8")
    assert not watch.named_in_record(tmp_path, os.getpid())


def test_a_held_supervisor_lock_counts_as_supervised(tmp_path) -> None:
    handle = _hold_supervisor_lock(tmp_path)
    try:
        assert watch.supervised(tmp_path)
    finally:
        handle.close()


def test_a_free_supervisor_lock_means_nobody_supervises(tmp_path) -> None:
    assert not watch.supervised(tmp_path)


def test_a_forgotten_worker_stops_itself(tmp_path) -> None:
    handle = _hold_supervisor_lock(tmp_path)
    _record(tmp_path, os.getpid() + 1)
    try:
        assert _watch_in_background(tmp_path).wait(timeout=5)
    finally:
        handle.close()


def test_a_worker_without_a_supervisor_stops_itself(tmp_path) -> None:
    _record(tmp_path, os.getpid())

    assert _watch_in_background(tmp_path).wait(timeout=5)


def test_an_owned_and_supervised_worker_keeps_running(tmp_path) -> None:
    handle = _hold_supervisor_lock(tmp_path)
    _record(tmp_path, os.getpid())
    try:
        assert not _watch_in_background(tmp_path).wait(timeout=PERIOD * 10)
    finally:
        handle.close()


def test_one_missed_check_is_forgiven(tmp_path, monkeypatch) -> None:
    answers = iter([False, True, False, True])
    monkeypatch.setattr(watch, "still_owned", lambda _root, _pid: next(answers, True))

    assert not _watch_in_background(tmp_path).wait(timeout=PERIOD * 10)
