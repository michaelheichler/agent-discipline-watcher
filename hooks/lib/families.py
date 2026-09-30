"""One family map so that config and readers agree."""
from __future__ import annotations

from collections.abc import Iterable

FAMILIES = ("prose", "comment", "code")
LEGACY_FAMILIES = ("punctuation", "english", "clean_code")
NAMES = FAMILIES + LEGACY_FAMILIES
# Most specific first because a subfamily beats prose.
SCOPES: dict[str, tuple[str, ...]] = {
    "punctuation": ("punctuation", "prose"),
    "english": ("english", "prose"),
    "comment": ("comment", "clean_code"),
    "code": ("code", "clean_code"),
}
LEAVES = tuple(SCOPES)


def scope(family: str) -> tuple[str, ...]:
    """Fall back to the name because stored rows predate it."""
    return SCOPES.get(family, (family,))


def leaves_of(names: Iterable[str]) -> frozenset[str]:
    """Expand aliases so that clean_code drops comment and code."""
    listed = set(names)
    return frozenset(leaf for leaf, scoped in SCOPES.items() if listed.intersection(scoped))


def covered(name: str) -> frozenset[str]:
    """Widen the match because old ledger rows keep their name."""
    return frozenset((name, *(leaf for leaf, scoped in SCOPES.items() if name in scoped)))
