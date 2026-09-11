"""Session-wide setup for every test under hooks/, because it was previously an import-time side effect in test_hooks.py that other test modules silently depended on collection order to get."""
from __future__ import annotations

import os

import pytest

from lib import embedding_client, embedding_server, embedding_session, reporting


def _disable_git_background_tasks() -> None:
    config = {
        "maintenance.auto": "false",
        "gc.auto": "0",
        "core.fsmonitor": "false",
    }
    try:
        offset = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        offset = 0
    for index, (key, value) in enumerate(config.items(), start=offset):
        os.environ[f"GIT_CONFIG_KEY_{index}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{index}"] = value
    os.environ["GIT_CONFIG_COUNT"] = str(offset + len(config))


@pytest.fixture(scope="session", autouse=True)
def _quiet_git_subprocesses() -> None:
    """Session-scoped because the original call ran once at import time, so a per-test fixture would change nothing it is not meant to."""
    _disable_git_background_tasks()


@pytest.fixture(autouse=True)
def _isolated_default_reports(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    original = reporting._reports_dir
    default_directory = original()

    def reports_directory():
        directory = original()
        return tmp_path / "reports" if directory == default_directory else directory

    monkeypatch.setattr(reporting, "_reports_dir", reports_directory)


@pytest.fixture(autouse=True)
def _never_touch_the_real_model(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    root = tmp_path_factory.mktemp("embedding-server")
    monkeypatch.setattr(embedding_server, "default_root", lambda: root)
    monkeypatch.setattr(embedding_client, "default_root", lambda: root)
    monkeypatch.setattr(embedding_session, "default_root", lambda: root)
    monkeypatch.setattr(embedding_session, "start_detached", lambda _root: None)
