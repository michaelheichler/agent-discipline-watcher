"""Test write gate, since only the test writer may add tests."""
from __future__ import annotations

import operator
import re
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import NamedTuple

try:
    from . import host, payloads, test_units
    from .findings import Finding
    from .protected import authorized
except ImportError:
    import host
    import payloads
    import test_units
    from findings import Finding
    from protected import authorized

TEST_WRITER = "adw-test-writer"
RULE = "test_write_gate"
WINDOW_KEY = "tests_allow_until"
WINDOW_HINT = "adw-config tests allow --for 30m"
TEST_DIRS = frozenset({"tests", "__tests__"})
_TEST_NAME_RE = re.compile(
    r"^(?:test_.+\.py|.+_test\.py|.+\.(?:test|spec)\.[cm]?[jt]sx?)$"
)
_RUST_TEST_RE = re.compile(r"#\[\s*(?:cfg\s*\(\s*test\s*\)|(?:tokio\s*::\s*)?test\b)")
AGENT_ACTION = (
    f"Delegate this test change to the {TEST_WRITER} agent. If the user wants it"
    f" done here, ask them to run `{WINDOW_HINT}` in a terminal."
)
OMP_ACTION = (
    "OMP names no agent on tool calls, so only a timed window opens this gate."
    f" Ask the user to run `{WINDOW_HINT}` in a terminal."
)


class PendingChange(NamedTuple):
    """Optional sides, because a delete has no after text."""

    path: str
    before: str | None
    after: str | None


def is_test_path(path: str) -> bool:
    """Match by name, because a new empty file has no test yet."""
    pure = PurePath(path.lower())
    if any(part in TEST_DIRS for part in pure.parts[:-1]):
        return True
    return bool(_TEST_NAME_RE.match(pure.name))


def has_tests(path: str, text: str | None) -> bool:
    """Reuse the extractor, because Code Check must agree."""
    if not text:
        return False
    if test_units.extract(path, text):
        return True
    return test_units.language_of(path) == test_units.RUST and bool(_RUST_TEST_RE.search(text))


def touches_tests(change: PendingChange) -> bool:
    """Check both sides, since deleting a test also changes it."""
    return (
        is_test_path(change.path)
        or has_tests(change.path, change.before)
        or has_tests(change.path, change.after)
    )


def window_until(settings: dict) -> int:
    """Read an exact int, since a bool or string opens nothing."""
    value = settings.get(WINDOW_KEY)
    return value if operator.is_(type(value), int) else 0


def window_seconds_left(settings: dict, now: float) -> int:
    """Take now, because an expiry test must not sleep."""
    return max(0, int(window_until(settings) - now))


class Gate(NamedTuple):
    """Grouped, because every caller holds all three at once."""

    payload: object
    settings: dict
    now: float


def gate_open(gate: Gate) -> bool:
    """Few exits, because each one is a way around the gate."""
    if gate.settings.get("tests") != "deny" or authorized():
        return True
    if payloads.agent_type(gate.payload) == TEST_WRITER:
        return True
    return window_seconds_left(gate.settings, gate.now) > 0


def read_before(path: Path) -> str | None:
    """Treat unreadable as absent, since the path still counts."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _finding(path: str) -> dict:
    action = OMP_ACTION if host.is_omp_host() else AGENT_ACTION
    return Finding(
        family="self_protection", rule=RULE, line=1, detail="Test write in " + path,
        force=True, snippet=path.strip()[:180], action=action,
        path=path, severity=None, tool_use_id=None,
    ).to_dict()


def findings(gate: Gate, changes: Iterable[PendingChange]) -> list[dict]:
    """One row per path, because the user reads which file."""
    if gate_open(gate):
        return []
    return [_finding(change.path) for change in changes if touches_tests(change)]
