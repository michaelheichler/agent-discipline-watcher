"""Test write gate, since only the test writer may add tests."""
from __future__ import annotations

import operator
import os
import re
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import NamedTuple

try:
    from . import host, payloads, test_units
    from .findings import Finding
    from .markup import MARKDOWN_EXTS
    from .protected import authorized
except ImportError:
    import host
    import payloads
    import test_units
    from findings import Finding
    from markup import MARKDOWN_EXTS
    from protected import authorized

TEST_WRITER = "adw-test-writer"
# Both, because Claude Code scopes a plugin agent by its plugin name.
TEST_WRITER_TYPES = frozenset({TEST_WRITER, "agent-discipline-watcher:" + TEST_WRITER})
RULE = "test_write_gate"
WINDOW_KEY = "tests_allow_until"
WINDOW_HINT = "adw-config tests allow --for 30m"
TEST_DIRS = frozenset({"tests", "__tests__", "test", "spec"})
# Exempt, because docs/spec/design.md is a document, not a test.
DOC_EXTS = MARKDOWN_EXTS | {".rst", ".txt", ".adoc"}
PROJECT_MARKER = ".git"
UNRESOLVED_DETAIL = "Shell command may change tests it does not name: "
_TEST_NAME_RE = re.compile(
    r"^(?:test_.+\.py|.+_test\.py|conftest\.py|.+_test\.go|.+_spec\.rb"
    r"|.+\.(?:test|spec)\.[cm]?[jt]sx?)$"
)
_JAVA_TEST_RE = re.compile(r"^.+Tests?\.java$")
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


def project_root(cwd: str) -> str:
    """Walk up, because cwd may itself sit inside a test dir."""
    start = Path(os.path.abspath(cwd or "."))
    for directory in (start, *start.parents):
        if (directory / PROJECT_MARKER).exists():
            return str(directory)
    return str(start)


def _judged_parts(path: str, root: str | None) -> tuple[str, ...]:
    """Drop the root, because a folder above the project is no test."""
    pure = PurePath(os.path.normpath(path.lower()))
    base = PurePath(os.path.normpath(root.lower())) if root else None
    if base is not None and pure.is_absolute() and pure.is_relative_to(base):
        return pure.relative_to(base).parts
    return pure.parts


def is_test_path(path: str, root: str | None = None) -> bool:
    """Match by name, because a new empty file has no test yet."""
    name = PurePath(path).name
    in_test_dir = any(part in TEST_DIRS for part in _judged_parts(path, root))
    if in_test_dir and PurePath(name.lower()).suffix not in DOC_EXTS:
        return True
    return bool(_TEST_NAME_RE.match(name.lower()) or _JAVA_TEST_RE.match(name))


def inline_test_bodies(path: str, text: str | None) -> tuple[str, ...]:
    """Bodies without lines, because a shifted test is unchanged."""
    if not text:
        return ()
    bodies = [unit.attributes + unit.body for unit in test_units.extract(path, text)]
    if test_units.language_of(path) == test_units.RUST:
        bodies += test_units.rust_cfg_test_blocks(text)
    return tuple(bodies)


def touches_tests(change: PendingChange, root: str | None = None) -> bool:
    """Compare both sides, since deleting a test also changes it."""
    if is_test_path(change.path, root):
        return True
    before = inline_test_bodies(change.path, change.before)
    return before != inline_test_bodies(change.path, change.after)


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
    if payloads.agent_type(gate.payload) in TEST_WRITER_TYPES:
        return True
    return window_seconds_left(gate.settings, gate.now) > 0


def read_before(path: Path) -> str | None:
    """Treat unreadable as absent, since the path still counts."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _finding(path: str, detail: str = "Test write in ") -> dict:
    action = OMP_ACTION if host.is_omp_host() else AGENT_ACTION
    return Finding(
        family="self_protection", rule=RULE, line=1, detail=detail + path,
        force=True, snippet=path.strip()[:180], action=action,
        path=path, severity=None, tool_use_id=None,
    ).to_dict()


def findings(gate: Gate, changes: Iterable[PendingChange], unresolved: Iterable[str] = ()) -> list[dict]:
    """One row per path, because the user reads which file."""
    if gate_open(gate):
        return []
    cwd = Path(payloads.cwd(gate.payload) or ".")
    root = project_root(str(cwd))
    rows = [
        _finding(change.path) for change in changes
        if touches_tests(change._replace(path=str(payloads.resolved_path(change.path, cwd))), root)
    ]
    return rows + [_finding(command, UNRESOLVED_DETAIL) for command in unresolved]
