"""Pin each family name so that old configs keep their rules."""
from __future__ import annotations

import pytest

from lib import config
from lib.scanner import scan_all

APOLOGY = "ha" + "cky"
FIXTURE = {
    "a.py": "def test_nothing():\n    pass\n# return compute(value)\n# " + APOLOGY + " later\n",
    "notes.md": "We utilize this" + chr(0x2014) + "now.\n",
}
LOCKED = frozenset({("a.py", "prose_comment_block"), ("a.py", "what_comment")})
# Pinned before the split so that old configs stay the same.
GOVERNED = {
    "punctuation": frozenset({("notes.md", "banned_dash")}),
    "english": frozenset({("notes.md", "utilize")}),
    "clean_code": frozenset({
        ("a.py", "commented_code"), ("a.py", "apology_comment"),
        ("a.py", "function_too_long"), ("a.py", "hollow_test"),
    }),
}
ALL_RULES = LOCKED.union(*GOVERNED.values())
NEW_NAMES = {
    "prose": GOVERNED["punctuation"] | GOVERNED["english"],
    "comment": frozenset({("a.py", "apology_comment")}),
    "code": GOVERNED["clean_code"] - {("a.py", "apology_comment")},
}


def _fired(settings: dict) -> dict[tuple[str, str], str]:
    cfg = {**settings, "function_block_lines": 1}
    return {
        (path, row["rule"]): str(config.resolve_outcome(row, cfg))
        for path, text in FIXTURE.items()
        for row in scan_all(path, text, cfg)
    }


def _moved(names: frozenset, outcome: str) -> dict[tuple[str, str], str]:
    return {key: outcome if key in names else "block" for key in ALL_RULES}


def test_the_fixture_fires_every_rule_by_default() -> None:
    """Guard the fixture because a silent file proves nothing."""
    assert _fired({}) == dict.fromkeys(ALL_RULES, "block")


@pytest.mark.parametrize("name", sorted(GOVERNED))
@pytest.mark.parametrize("off", ["boolean", "exempt"])
def test_an_old_name_switched_off_drops_the_same_rules(name: str, off: str) -> None:
    settings = {name: False} if off == "boolean" else {"exempt_families": {"*": [name]}}
    assert _fired(settings) == dict.fromkeys(ALL_RULES - GOVERNED[name], "block")


@pytest.mark.parametrize("name", sorted(GOVERNED))
@pytest.mark.parametrize(("state", "outcome"), [("observe", "would_block"), ("off", "release")])
def test_an_old_name_gate_moves_the_same_rules(name: str, state: str, outcome: str) -> None:
    assert _fired({"gates": {name: state}}) == _moved(GOVERNED[name], outcome)


@pytest.mark.parametrize("name", sorted(GOVERNED))
def test_an_old_name_kill_switch_releases_the_same_rules(name: str) -> None:
    assert _fired({"kill_switches": {name: True}}) == _moved(GOVERNED[name], "release")


@pytest.mark.parametrize("name", sorted(NEW_NAMES))
def test_a_new_name_moves_only_its_share_of_the_rules(name: str) -> None:
    """Split clean_code so that code rules move without comments."""
    assert _fired({name: False}) == dict.fromkeys(ALL_RULES - NEW_NAMES[name], "block")
    assert _fired({"gates": {name: "observe"}}) == _moved(NEW_NAMES[name], "would_block")


def test_a_subfamily_gate_beats_the_prose_gate() -> None:
    fired = _fired({"gates": {"prose": "observe", "english": "enforce"}})
    assert fired[("notes.md", "utilize")] == "block"
    assert fired[("notes.md", "banned_dash")] == "would_block"


def test_any_false_name_switches_the_subfamily_off() -> None:
    assert ("notes.md", "utilize") not in _fired({"prose": False, "english": True})
