"""Session-wide setup for every test under hooks/, because it was previously an import-time side effect in test_hooks.py that other test modules silently depended on collection order to get."""
from __future__ import annotations

import os

import pytest


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
