import sqlite3
from functools import partial
from pathlib import Path

from lib import principle_kb, reporting, session_state
from lib.finding_output import Explainer

LOOP_TEXT = "One case per test keeps each failure visible. A loop stops at the first bad case."
LONG_TEXT = " ".join(["Split the work so each part reads alone."] * 20) + " See https://example.org/x here."


def _finding(rule: str = "assert_in_loop", line: int = 4) -> dict:
    return {
        "path": "tests/test_x.py", "line": line, "family": "code", "rule": rule,
        "action": "Split the loop into one test per case.", "snippet": "for case in cases:",
    }


def _row(text: str = LOOP_TEXT, title: str = "arrange-act-assert") -> principle_kb.Row:
    return principle_kb.Row("deviq", "testing/aaa", title, text)


def _explainer(state_root: Path, lookup=lambda _entry: _row()) -> Explainer:
    claim = partial(session_state.claim_explained, "s1", root=state_root)
    return Explainer(lookup, claim, {"assert_in_loop": "testing/aaa"})


def _body(findings: list[dict], explainer: Explainer | None) -> str:
    reason, _ = reporting.compact_block(findings, {}, explainer=explainer)
    return reason.rsplit("\n", 1)[0]


def test_first_finding_of_a_rule_carries_the_labeled_principle(tmp_path: Path) -> None:
    body = _body([_finding()], _explainer(tmp_path))
    assert body.splitlines()[2] == f"   Principle (DevIQ, Arrange Act Assert): {LOOP_TEXT}"


def test_second_finding_of_the_rule_in_the_session_shows_the_row_only(tmp_path: Path) -> None:
    explainer = _explainer(tmp_path)
    _body([_finding()], explainer)
    assert _body([_finding(line=9)], explainer) == _body([_finding(line=9)], None)


def test_repeated_rule_in_one_block_is_explained_once(tmp_path: Path) -> None:
    body = _body([_finding(line=4), _finding(line=9)], _explainer(tmp_path))
    assert body.count("Principle (") == 1


def test_unmapped_rule_renders_unchanged(tmp_path: Path) -> None:
    findings = [_finding(rule="function_too_long")]
    assert _body(findings, _explainer(tmp_path)) == _body(findings, None)


def test_missing_database_leaves_the_finding_unchanged(tmp_path: Path) -> None:
    explainer = _explainer(tmp_path, partial(principle_kb.entry, root=tmp_path / "absent"))
    assert _body([_finding()], explainer) == _body([_finding()], None)


def test_failing_lookup_leaves_the_finding_unchanged(tmp_path: Path) -> None:
    def broken(_entry: str) -> principle_kb.Row:
        raise sqlite3.OperationalError("disk I/O error")

    assert _body([_finding()], _explainer(tmp_path, broken)) == _body([_finding()], None)


def test_failed_lookup_leaves_the_rule_unclaimed(tmp_path: Path) -> None:
    _body([_finding()], _explainer(tmp_path, lambda _entry: None))
    assert "Principle (" in _body([_finding()], _explainer(tmp_path))


def test_long_text_is_cut_at_a_sentence_end_without_links(tmp_path: Path) -> None:
    body = _body([_finding()], _explainer(tmp_path, lambda _entry: _row(LONG_TEXT, "Small Parts")))
    text = body.splitlines()[2].split("): ", 1)[1]
    assert (len(text.split()) <= 80, text.endswith("."), "http" in text) == (True, True, False)


def test_front_matter_is_dropped_from_the_text(tmp_path: Path) -> None:
    stored = "--- title: Small Parts weight: 3 --- Keep each part small. It reads alone."
    body = _body([_finding()], _explainer(tmp_path, lambda _entry: _row(stored, "Small Parts")))
    assert body.splitlines()[2] == "   Principle (DevIQ, Small Parts): Keep each part small. It reads alone."


def test_entry_reads_source_title_and_text_from_the_cache(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / principle_kb.DB_NAME)
    connection.execute("CREATE TABLE principle (source TEXT, entry_id TEXT, title TEXT, text TEXT)")
    connection.execute("INSERT INTO principle VALUES ('deviq', 'testing/aaa', 'AAA', 'Act once.')")
    connection.commit()
    connection.close()
    assert principle_kb.entry("testing/aaa", root=tmp_path) == principle_kb.Row("deviq", "testing/aaa", "AAA", "Act once.")
