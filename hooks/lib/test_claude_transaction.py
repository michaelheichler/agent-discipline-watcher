from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import claude_transaction

PRESETS = ("haiku", "mixed", "luna", "luna-native")
VERSION = 2
HASH = "a" * 64


def _payload(**overrides) -> dict:
    base = {
        "version": VERSION,
        "preset": "haiku",
        "base_preset": None,
        "base_settings_hash": None,
    }
    return {**base, **overrides}


def _validate(payload: dict) -> dict:
    return claude_transaction.validate_payload(json.dumps(payload), PRESETS, VERSION)


def test_a_minimal_transaction_survives_validation() -> None:
    """Accept the required four because a stricter shape would reject every real transaction."""
    assert _validate(_payload())["preset"] == "haiku"


def test_a_transaction_naming_a_retired_preset_is_refused() -> None:
    """Refuse it because a settings file written before the roster shrank still names sonnet."""
    with pytest.raises(ValueError, match="invalid preset transaction"):
        _validate(_payload(preset="sonnet"))


def test_a_transaction_from_another_version_is_refused() -> None:
    """Refuse it because an older writer laid out these fields differently."""
    with pytest.raises(ValueError, match="invalid preset transaction"):
        _validate(_payload(version=1))


def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    """Refuse the extra because a field nobody validates is a field an attacker chooses."""
    with pytest.raises(ValueError, match="invalid preset transaction"):
        _validate(_payload(injected="value"))


def test_a_missing_required_field_is_refused() -> None:
    """Refuse the gap because a half-read transaction rewrites the user's settings."""
    partial = _payload()
    del partial["base_settings_hash"]

    with pytest.raises(ValueError, match="invalid preset transaction"):
        _validate(partial)


@pytest.mark.parametrize("field", ("base_settings_hash", "base_managed_hash"))
def test_a_hash_that_is_not_sixty_four_hex_digits_is_refused(field: str) -> None:
    """Check the shape because a short hash compares equal to nothing and skips the guard."""
    with pytest.raises(ValueError, match="hash in transaction"):
        _validate(_payload(**{field: "abc"}))


@pytest.mark.parametrize("field", ("base_settings_hash", "base_managed_hash"))
def test_a_well_formed_hash_passes(field: str) -> None:
    """Accept the real shape because the guard above must not reject a valid write."""
    assert _validate(_payload(**{field: HASH}))[field] == HASH


@pytest.mark.parametrize("metadata", ([1, 2, 3], [1, 2, 3, 4, 5, -1], [1, 2, 3, 4, 5, "6"]))
def test_malformed_stat_metadata_is_refused(metadata: list) -> None:
    """Require six non-negative integers because this value decides whether the file changed."""
    with pytest.raises(ValueError, match="metadata in transaction"):
        _validate(_payload(base_settings_metadata=metadata))


def test_text_that_is_not_json_names_the_parse_failure() -> None:
    """Name it because a truncated transaction and a hostile one need different answers."""
    with pytest.raises(ValueError, match="could not read preset transaction"):
        claude_transaction.validate_payload("{not json", PRESETS, VERSION)


def test_a_json_array_is_refused_because_a_transaction_is_an_object() -> None:
    """Check the type because indexing a list with a string key raises the wrong error."""
    with pytest.raises(ValueError, match="must be a JSON object"):
        claude_transaction.validate_payload("[]", PRESETS, VERSION)


def _open_parent(path: Path) -> int:
    return os.open(path.parent, os.O_RDONLY)


def test_quarantine_moves_the_bad_leaf_and_leaves_its_neighbour(tmp_path: Path) -> None:
    """Move one name because the settings file sits in the same directory."""
    bad = tmp_path / "settings.json.txn"
    bad.write_text("corrupt", encoding="utf-8")
    neighbour = tmp_path / "settings.json"
    neighbour.write_text("keep me", encoding="utf-8")

    claude_transaction.quarantine(bad, _open_parent, ".corrupt-", 8, 4096)

    assert not bad.exists()
    assert neighbour.read_text(encoding="utf-8") == "keep me"
    assert [path.name for path in tmp_path.iterdir() if ".corrupt-" in path.name]


def test_quarantining_an_absent_leaf_raises_nothing(tmp_path: Path) -> None:
    """Stay quiet because recovery runs on every read and most reads find nothing to move."""
    claude_transaction.quarantine(tmp_path / "gone.txn", _open_parent, ".corrupt-", 8, 4096)

    assert list(tmp_path.iterdir()) == []
