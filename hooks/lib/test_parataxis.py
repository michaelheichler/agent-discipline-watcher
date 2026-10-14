"""Pinned by behavior, because a parataxis rule that fires on joined prose would teach writers to ignore it."""
from __future__ import annotations

import json

import pytest

from lib import configure_policy
from lib.config import Outcome, load_project_config, resolve_outcome
from lib.finding_output import localized
from lib.scanner import scan_all

PARATAXIS_RULES = {"choppy_sentences", "de_parataxis"}
RETIRED_LENGTH_RULES = {"long_sentence", "de_sentence_length"}
ENGLISH_CHAIN = "The hook reads the file. It checks every rule. It writes a report."
GERMAN_CHAIN = "Wir haben eine Pumpe entwickelt. Sie misst den Druck. Sie speichert jeden Wert."
HUMANIZER_BAD = (
    "Das Team analysierte die Daten. Die Ergebnisse waren eindeutig. "
    "Die Conversion stieg um 25 Prozent. Das Projekt wurde im Budget abgeschlossen."
)
HUMANIZER_GOOD = (
    "Als das Team die Daten analysierte, war das Ergebnis eindeutig: "
    "Die Conversion stieg um 25 Prozent. Das Projekt blieb im Budget."
)


def _rules(text: str, path: str = "doc.md", config: dict | None = None) -> set[str]:
    return {row["rule"] for row in scan_all(path, text + "\n", config)}


def _rows(text: str, rule: str) -> list[dict]:
    return [row for row in scan_all("doc.md", text + "\n") if row["rule"] == rule]


@pytest.mark.parametrize("text,rule", [
    pytest.param(ENGLISH_CHAIN, "choppy_sentences", id="english-pronoun-chain"),
    pytest.param(
        "The installer copies the hooks. The runtime starts on demand. "
        "The ledger keeps every finding. The report lists each row.",
        "choppy_sentences", id="english-four-bare-clauses",
    ),
    pytest.param(GERMAN_CHAIN, "de_parataxis", id="german-sie-chain"),
    pytest.param(HUMANIZER_BAD, "de_parataxis", id="humanizer-de-bad-example"),
])
def test_a_run_of_bare_main_clauses_is_reported_in_its_language(text: str, rule: str) -> None:
    assert _rules(text) & PARATAXIS_RULES == {rule}


def test_the_finding_names_the_run_and_its_first_line() -> None:
    rows = _rows("Intro line.\n\n" + ENGLISH_CHAIN, "choppy_sentences")

    assert [(row["line"], row["snippet"]) for row in rows] == [(3, ENGLISH_CHAIN)]


def test_the_english_fix_joins_sentences_and_keeps_the_dash_ban() -> None:
    action = _rows(ENGLISH_CHAIN, "choppy_sentences")[0]["action"]

    assert "Join the sentences" in action
    assert "semicolons stay banned" in action


def test_the_german_fix_reads_german_with_a_joined_example() -> None:
    row = localized(_rows(GERMAN_CHAIN, "de_parataxis")[0])

    assert "Semikolon bleiben verboten" in row["action"]
    assert "die den Druck misst" in row["action"]


@pytest.mark.parametrize("text", [
    pytest.param(HUMANIZER_GOOD, id="humanizer-de-good-example"),
    pytest.param(
        "The installer copies the hooks into place, and the runtime starts only when a hook first needs it. "
        "Most sessions never notice. When a scan finds a problem, the report names the file and the line "
        "so that the fix stays narrow.",
        id="mixed-lengths-with-joined-clauses",
    ),
    pytest.param("1. Open the file.\n2. It shows the config.\n3. Edit the gate.\n4. Save the file.", id="numbered-steps"),
    pytest.param("- Open the file.\n- It shows the config.\n- Edit the gate.\n- Save the file.", id="bullet-list"),
    pytest.param(f"```\n{ENGLISH_CHAIN}\n```", id="fenced-code"),
    pytest.param(f"> {ENGLISH_CHAIN}", id="block-quote"),
    pytest.param("# The hook reads.\n\n## It checks every rule.\n\n## It writes a report.", id="headings"),
    pytest.param('"I read the file." "It checks every rule." "It writes a report."', id="quoted-dialogue"),
])
def test_joined_or_non_prose_text_raises_no_parataxis_row(text: str) -> None:
    assert _rules(text) & PARATAXIS_RULES == set()


def test_a_code_comment_is_never_held_to_the_prose_rule() -> None:
    source = f"# {ENGLISH_CHAIN}\nVALUE = 1\n"

    assert _rules(source, "tool.py") & PARATAXIS_RULES == set()


@pytest.mark.parametrize("rule", sorted(PARATAXIS_RULES))
def test_each_rule_stays_silent_by_default_because_its_precision_is_under_the_bar(rule: str) -> None:
    assert resolve_outcome({"rule": rule, "family": "english"}) is Outcome.RELEASE


def test_a_project_can_turn_the_rule_on_to_observe() -> None:
    config = {"rule_gates": {"choppy_sentences": "observe"}}

    assert resolve_outcome({"rule": "choppy_sentences", "family": "english"}, config) is Outcome.WOULD_BLOCK


@pytest.mark.parametrize("text", [
    pytest.param("This " + " ".join(["word"] * 60) + ".", id="english-sixty-words"),
    pytest.param(
        "Wir bauen das Haus jetzt neu und planen dafür mit allen Beteiligten zusammen ein ganzes Jahr "
        "an Arbeit ein und hoffen auf gutes Wetter im Sommer.",
        id="german-twenty-six-words",
    ),
])
def test_a_long_prose_sentence_is_no_longer_reported(text: str) -> None:
    assert _rules(text) & RETIRED_LENGTH_RULES == set()


def test_an_old_config_naming_the_retired_keys_still_scans() -> None:
    old = {"sentence_word_cap": 3, "rule_gates": {"long_sentence": "enforce", "de_sentence_length": "enforce"}}

    assert _rules("One two three four five.", config=old) & RETIRED_LENGTH_RULES == set()


def test_an_old_project_file_naming_the_retired_keys_still_loads(tmp_path) -> None:
    target = tmp_path / ".agent-discipline.json"
    target.write_text(json.dumps({"sentence_word_cap": 30, "rule_gates": {"long_sentence": "off"}}), encoding="utf-8")

    assert load_project_config(target).settings["sentence_word_cap"] == 30


def test_the_policy_bridge_accepts_and_drops_the_retired_keys() -> None:
    values = configure_policy.validate_policy_values(
        {"sentence_word_cap": 30, "rule_gates": {"long_sentence": "off", "hedge_stack": "off"}},
    )

    assert values == {"rule_gates": {"hedge_stack": "off"}}
