"""Structural hashing for untrusted JSON-shaped values, moved out of batch.py because it depends on no batch concept."""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from typing import TypeGuard, TypeVar, cast

ExactType = TypeVar("ExactType")


def _is_exact_type(value: object, expected: type[ExactType]) -> TypeGuard[ExactType]:
    return operator.is_(type(value), expected)


_INVALID = object()


@dataclass(frozen=True, slots=True)
class _CanonicalContent:
    kind: str
    scalar: object
    keys: tuple[str, ...]
    children: tuple["_CanonicalNode", ...]

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("canonical node kind must not be empty")


class _CanonicalNode:

    __slots__ = ("children", "keys", "kind", "scalar", "structural_hash")
    children: tuple["_CanonicalNode", ...]
    keys: tuple[str, ...]
    kind: str
    scalar: object
    structural_hash: int

    def __init__(self, content: _CanonicalContent | str, **legacy: object) -> None:
        if isinstance(content, str):
            unexpected = set(legacy) - {"scalar", "keys", "children"}
            if unexpected:
                raise TypeError(f"canonical node got unsupported fields: {sorted(unexpected)!r}")
            content = _CanonicalContent(
                content,
                legacy.get("scalar"),
                cast(tuple[str, ...], legacy.get("keys", ())),
                cast(tuple[_CanonicalNode, ...], legacy.get("children", ())),
            )
        elif legacy:
            raise TypeError("canonical content cannot be combined with legacy fields")
        self.kind = content.kind
        self.scalar = content.scalar
        self.keys = content.keys
        self.children = content.children
        self.structural_hash = hash(
            (
                content.kind,
                content.scalar,
                content.keys,
                tuple(child.structural_hash for child in content.children),
            )
        )

    def __hash__(self) -> int:
        return self.structural_hash

    def __eq__(self, other: object) -> bool:
        if not _is_exact_type(other, _CanonicalNode):
            return NotImplemented
        candidate = other
        if self.structural_hash != candidate.structural_hash:
            return False
        pending = [(self, candidate)]
        compared: set[tuple[int, int]] = set()
        while pending:
            left, right = pending.pop()
            pair = (id(left), id(right))
            if pair in compared:
                continue
            compared.add(pair)
            if (
                left.kind != right.kind
                or left.scalar != right.scalar
                or left.keys != right.keys
                or len(left.children) != len(right.children)
            ):
                return False
            pending.extend(zip(left.children, right.children, strict=True))
        return True


Canonical = _CanonicalNode
CanonicalTask = tuple[str, object, object]


@dataclass(frozen=True, slots=True)
class _CanonicalFrame:
    identity: int
    kind: str
    keys: tuple[str, ...]
    child_count: int


@dataclass(slots=True)
class _CanonicalTraversal:
    tasks: list[CanonicalTask]
    values: list[Canonical]
    active: set[int]
    completed: dict[int, Canonical]


def _canonical_atom(value: object) -> Canonical | object:
    if value is None:
        return Canonical(_CanonicalContent("none", None, (), ()))
    if _is_exact_type(value, bool):
        return Canonical(_CanonicalContent("bool", value, (), ()))
    if _is_exact_type(value, int):
        return Canonical(_CanonicalContent("int", value, (), ()))
    if _is_exact_type(value, float):
        return (
            Canonical(_CanonicalContent("float", value.hex(), (), ()))
            if math.isfinite(value)
            else _INVALID
        )
    if _is_exact_type(value, str):
        return Canonical(_CanonicalContent("str", value, (), ()))
    return _INVALID


def _exact_dict_keys(mapping: dict[object, object]) -> tuple[object, ...]:
    return tuple(mapping)


def _validated_mapping(value: object) -> dict[str, object] | None:
    if not _is_exact_type(value, dict):
        return None
    mapping = cast(dict[object, object], value)
    if any(not _is_exact_type(key, str) for key in _exact_dict_keys(mapping)):
        return None
    return cast(dict[str, object], mapping)


def _finish_container(state: _CanonicalTraversal, frame: _CanonicalFrame) -> None:
    child_start = len(state.values) - frame.child_count
    children = tuple(state.values[child_start:])
    del state.values[child_start:]
    state.active.remove(frame.identity)
    node = Canonical(_CanonicalContent(frame.kind, None, frame.keys, children))
    state.completed[frame.identity] = node
    state.values.append(node)


def _schedule_list(sequence: list[object], state: _CanonicalTraversal) -> bool:
    identity = id(sequence)
    if identity in state.completed:
        state.values.append(state.completed[identity])
        return True
    if identity in state.active:
        return False
    state.active.add(identity)
    frame = _CanonicalFrame(identity, "list", (), len(sequence))
    state.tasks.append(("finish", sequence, frame))
    state.tasks.extend(("visit", child, None) for child in reversed(sequence))
    return True


def _schedule_dict(mapping: dict[object, object], state: _CanonicalTraversal) -> bool:
    identity = id(mapping)
    if identity in state.completed:
        state.values.append(state.completed[identity])
        return True
    if identity in state.active:
        return False
    state.active.add(identity)
    raw_keys = _exact_dict_keys(mapping)
    if any(not _is_exact_type(key, str) for key in raw_keys):
        return False
    string_keys = tuple(sorted(cast(str, key) for key in raw_keys))
    frame = _CanonicalFrame(identity, "dict", string_keys, len(string_keys))
    state.tasks.append(("finish", mapping, frame))
    state.tasks.extend(("visit", mapping[key], None) for key in reversed(string_keys))
    return True


def _process_canonical_task(state: _CanonicalTraversal, task: CanonicalTask) -> bool:
    action, item, metadata = task
    if action == "finish":
        _finish_container(state, cast(_CanonicalFrame, metadata))
        return True
    if _is_exact_type(item, list):
        return _schedule_list(cast(list[object], item), state)
    if _is_exact_type(item, dict):
        return _schedule_dict(cast(dict[object, object], item), state)
    atom = _canonical_atom(item)
    if atom is _INVALID:
        return False
    state.values.append(cast(Canonical, atom))
    return True


def _canonical_value(value: object) -> Canonical | object:
    state = _CanonicalTraversal([("visit", value, None)], [], set(), {})
    while state.tasks:
        if not _process_canonical_task(state, state.tasks.pop()):
            return _INVALID
    return state.values[0]
