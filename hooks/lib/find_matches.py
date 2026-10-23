"""Because find -delete or -exec rm changes only what its tests match, a bounded walk names those paths."""
from __future__ import annotations

import fnmatch
import os
import re
import shlex
import stat
import time
from collections.abc import Callable
from typing import NamedTuple

from .shell_syntax import _basename, _command_word_index, _without_redirects
from .xargs_feed import FED_VERBS

MAX_ENTRIES = 20_000
MAX_MATCHES = 1_000
MAX_SECONDS = 0.25
NAME_TESTS = {"-name": False, "-iname": True}
PATH_TESTS = {"-path": False, "-ipath": True, "-wholename": False, "-iwholename": True}
TYPE_MODES = {"f": stat.S_ISREG, "d": stat.S_ISDIR, "l": stat.S_ISLNK}
DEPTH_OPTIONS = frozenset({"-maxdepth", "-mindepth"})
TRUE_WORDS = frozenset({"-true", "-print", "-print0", "-depth", "-xdev", "-mount"})
NOT_WORDS = frozenset({"!", "-not"})
AND_WORDS = frozenset({"-a", "-and"})
OR_WORDS = frozenset({"-o", "-or"})
EXEC_WORDS = frozenset({"-exec", "-execdir"})
EXEC_ENDS = frozenset({";", "+"})
PLACEHOLDER = "{}"
STARTING_OPTIONS = frozenset({"-P"})
DELETING_VERBS = frozenset({"rm", "unlink", "shred"})
GLOB_CHARACTERS = frozenset("*?[")
# Because fnmatch reads [[:alpha:]] as a plain set while find reads a class.
POSIX_CLASS_RE = re.compile(r"\[[:=.]")
Resolver = Callable[[str], "str | None"]
Call = tuple[str, ...]


class Unsupported(Exception):
    """Raised, because a test or action outside the known set may match what the walk cannot see."""


class Node(NamedTuple):
    kind: str
    parts: tuple


class Entry(NamedTuple):
    path: str
    name: str
    mode: int
    depth: int
    fired: list[Node]


class Plan(NamedTuple):
    starts: list[str]
    tree: Node
    limits: dict[str, int]


def find_calls(segment: list[str], resolve: Resolver, cwd: str) -> tuple[Call, ...] | None:
    """None on any unknown, overflow, or error, because then the deleted set is not the walked one."""
    index = _command_word_index(segment)
    words = [resolve(token) for token in _without_redirects(segment[index + 1:])]
    if None in words:
        return None
    try:
        plan = _plan([word for word in words if word is not None])
        found = _walk(plan, cwd)
    except (Unsupported, OSError):
        return None
    return None if found is None else _calls(found) + _named_calls(plan)


def _named_calls(plan: Plan) -> tuple[Call, ...]:
    """Because rm -rf .adw is judged by its name whether or not .adw exists, a deleting find is judged by the names it spells."""
    deleting, spelled = _spelled(plan.tree)
    if not deleting:
        return ()
    literal = [pair for pair in spelled if not GLOB_CHARACTERS.intersection(pair[1])]
    named = [os.path.join(start, value) for start in plan.starts for test, value in literal if test in NAME_TESTS]
    named += [value for test, value in literal if test in PATH_TESTS]
    return (("rm", "-rf", "--", *map(shlex.quote, [*plan.starts, *named])),)


def _spelled(node: Node) -> tuple[bool, list[tuple[str, str]]]:
    """Because a pruned or negated name marks what the find leaves alone, only a deleting branch spells targets."""
    if node.kind == "test":
        return False, [node.parts]
    if node.kind in {"-delete", "exec"}:
        return node.kind == "-delete" or _basename(node.parts[0][0]) in DELETING_VERBS, []
    if node.kind not in {"or", "and"}:
        return False, []
    branches = [_spelled(part) for part in node.parts]
    deleting = any(deletes for deletes, _ in branches)
    if node.kind == "or":
        return deleting, [pair for deletes, pairs in branches if deletes for pair in pairs]
    return deleting, [pair for _, pairs in branches for pair in pairs] if deleting else []


def _plan(words: list[str]) -> Plan:
    position = 1 if words[:1] and words[0] in STARTING_OPTIONS else 0
    starts = []
    while position < len(words) and not (words[position].startswith("-") or words[position] in {"(", "!"}):
        starts.append(words[position])
        position += 1
    limits: dict[str, int] = {}
    stream = _Stream(words[position:], limits)
    tree = stream.disjunction() if stream.words else Node("true", ())
    if stream.position != len(stream.words):
        raise Unsupported(stream.words[stream.position])
    return Plan(starts or ["."], tree, limits)


class _Stream:
    """Because ! binds tighter than the implied -a, and -a tighter than -o, each level has its own reader."""

    def __init__(self, words: list[str], limits: dict[str, int]) -> None:
        self.words = words
        self.limits = limits
        self.position = 0

    def peek(self) -> str | None:
        return self.words[self.position] if self.position < len(self.words) else None

    def take(self) -> str:
        word = self.peek()
        if word is None:
            raise Unsupported("missing operand")
        self.position += 1
        return word

    def disjunction(self) -> Node:
        node = self.conjunction()
        while self.peek() in OR_WORDS:
            self.take()
            node = Node("or", (node, self.conjunction()))
        return node

    def conjunction(self) -> Node:
        node = self.negation()
        while self.peek() is not None and self.peek() not in OR_WORDS and self.peek() != ")":
            if self.peek() in AND_WORDS:
                self.take()
            node = Node("and", (node, self.negation()))
        return node

    def negation(self) -> Node:
        if self.peek() in NOT_WORDS:
            self.take()
            return Node("not", (self.negation(),))
        return self.primary()

    def primary(self) -> Node:
        word = self.take()
        if word == "(":
            node = self.disjunction()
            if self.take() != ")":
                raise Unsupported("unclosed group")
            return node
        return _primary(self, word)


def _primary(stream: _Stream, word: str) -> Node:
    if word in NAME_TESTS or word in PATH_TESTS or word == "-type":
        return Node("test", (word, stream.take()))
    if word in DEPTH_OPTIONS:
        stream.limits[word] = _depth(stream.take())
        return Node("true", ())
    if word in TRUE_WORDS or word in {"-delete", "-prune", "-false", "-empty"}:
        return Node(word, ())
    if word in EXEC_WORDS:
        return _exec(stream)
    raise Unsupported(word)


def _depth(value: str) -> int:
    if not value.isdigit():
        raise Unsupported(value)
    return int(value)


def _exec(stream: _Stream) -> Node:
    call: list[str] = []
    while stream.peek() not in EXEC_ENDS:
        call.append(stream.take())
    batched = stream.take() == "+"
    if not call or _basename(call[0]) not in FED_VERBS or (batched and call[-1:] != [PLACEHOLDER]):
        raise Unsupported(" ".join(call))
    return Node("exec", (tuple(call), batched))


class _Walk(NamedTuple):
    """Because -delete implies -depth in GNU find, -prune stops nothing when it is present."""

    plan: Plan
    cwd: str
    deadline: float
    visited: list[int]
    pruning: bool
    found: list[Entry]


def _walk(plan: Plan, cwd: str) -> list[Entry] | None:
    walk = _Walk(plan, cwd, time.monotonic() + MAX_SECONDS, [0], not _has(plan.tree, "-delete"), [])
    for start in plan.starts:
        if not _visit(walk, Entry(start, os.path.basename(start.rstrip("/")) or start, _mode(cwd, start), 0, [])):
            return None
    return walk.found


def _visit(walk: _Walk, entry: Entry) -> bool:
    walk.visited[0] += 1
    if walk.visited[0] > MAX_ENTRIES or time.monotonic() > walk.deadline:
        return False
    if entry.depth >= walk.plan.limits.get("-mindepth", 0):
        _holds(walk.plan.tree, entry, walk.cwd)
    walk.found.extend([entry] if entry.fired else [])
    if len(walk.found) > MAX_MATCHES:
        return False
    pruned = walk.pruning and any(node.kind == "-prune" for node in entry.fired)
    if not stat.S_ISDIR(entry.mode) or pruned or entry.depth >= walk.plan.limits.get("-maxdepth", 1 << 30):
        return True
    with os.scandir(_located(walk.cwd, entry.path)) as children:
        names = sorted(child.name for child in children)
    return all(_visit(walk, _child(entry, name, walk.cwd)) for name in names)


def _child(entry: Entry, name: str, cwd: str) -> Entry:
    path = os.path.join(entry.path, name)
    return Entry(path, name, _mode(cwd, path), entry.depth + 1, [])


def _mode(cwd: str, path: str) -> int:
    return os.lstat(_located(cwd, path)).st_mode


def _located(cwd: str, path: str) -> str:
    """Home expanded here only, because the printed path keeps ~ so the gates join home themselves."""
    return os.path.join(cwd, os.path.expanduser(path))


def _holds(node: Node, entry: Entry, cwd: str) -> bool:
    if node.kind in {"or", "and"}:
        first = _holds(node.parts[0], entry, cwd)
        return (first or _holds(node.parts[1], entry, cwd)) if node.kind == "or" else (first and _holds(node.parts[1], entry, cwd))
    if node.kind == "not":
        return not _holds(node.parts[0], entry, cwd)
    if node.kind == "test":
        return _tests(node.parts[0], node.parts[1], entry)
    if node.kind in {"-false", "-empty"}:
        return node.kind == "-empty" and _empty(entry, cwd)
    if node.kind in {"-delete", "-prune", "exec"}:
        entry.fired.append(node)
    return True


def _tests(name: str, value: str, entry: Entry) -> bool:
    if name == "-type":
        kinds = value.split(",")
        if not set(kinds) <= set(TYPE_MODES):
            raise Unsupported(value)
        return any(TYPE_MODES[kind](entry.mode) for kind in kinds)
    folded = NAME_TESTS.get(name, PATH_TESTS.get(name))
    subject = entry.name if name in NAME_TESTS else entry.path
    if "\\" in value or POSIX_CLASS_RE.search(value):
        raise Unsupported(value)
    pattern = value.replace("[^", "[!")
    return fnmatch.fnmatchcase(subject.lower(), pattern.lower()) if folded else fnmatch.fnmatchcase(subject, pattern)


def _empty(entry: Entry, cwd: str) -> bool:
    full = _located(cwd, entry.path)
    if stat.S_ISDIR(entry.mode):
        with os.scandir(full) as children:
            return next(children, None) is None
    return stat.S_ISREG(entry.mode) and os.lstat(full).st_size == 0


def _has(node: Node, kind: str) -> bool:
    return node.kind == kind or (node.kind in {"or", "and", "not"} and any(_has(part, kind) for part in node.parts))


def _calls(found: list[Entry]) -> tuple[Call, ...]:
    """rm for -delete, because both remove the matched path and nothing the walk did not name."""
    deleted = [entry.path for entry in found if any(node.kind == "-delete" for node in entry.fired)]
    calls = [("rm", "-f", "--", *map(shlex.quote, deleted))] if deleted else []
    for node in {node for entry in found for node in entry.fired if node.kind == "exec"}:
        calls.extend(_exec_calls(node, [entry.path for entry in found if node in entry.fired]))
    return tuple(calls)


def _exec_calls(node: Node, paths: list[str]) -> list[Call]:
    words, batched = node.parts
    if batched:
        return [(*map(shlex.quote, words[:-1]), *map(shlex.quote, paths))]
    return [tuple(shlex.quote(word.replace(PLACEHOLDER, path)) for word in words) for path in paths]
