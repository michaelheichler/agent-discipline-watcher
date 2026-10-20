"""Baseline subtraction: an edit answers for what it changed, not for debt already committed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

import pytest

from lib import baseline, config, scanner
from testing import make_repo, run_git as git

LEGACY = "#!/usr/bin/env python3\n# increments the counter\nx = 1\n"
EXTRA_DEBT = LEGACY + "# resets the counter\ny = 2\n"
# Defer the literal because the discipline scanner would otherwise flag this test file.
ENFORCED_DEBT = LEGACY + "# " + ("TO" + "DO") + " later\ny = 2\n"
CLEAN_ADDITION = LEGACY + "z = 3\n"


def commit(repo: Path, name: str, body: str) -> Path:
    path = repo / name
    path.write_text(body, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "seed")
    return path


class BaselineModeTests(unittest.TestCase):
    def test_it_defaults_to_report(self):
        self.assertEqual(baseline.baseline_mode({}), "report")

    def test_an_unknown_mode_falls_back_to_report(self):
        self.assertEqual(baseline.baseline_mode({"baseline": "sometimes"}), "report")

    def test_none_is_honored(self):
        self.assertEqual(baseline.baseline_mode({"baseline": "none"}), "none")

    def test_git_is_honored(self):
        self.assertEqual(baseline.baseline_mode({"baseline": "git"}), "git")

    def test_the_shipped_default_config_selects_report(self):
        self.assertEqual(config.effective_config()["baseline"], "report")


class CommittedTextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_returns_the_committed_body(self):
        repo = make_repo(self.root)
        path = commit(repo, "legacy.py", LEGACY)
        path.write_text(CLEAN_ADDITION, encoding="utf-8")
        self.assertEqual(baseline.committed_text(path), LEGACY)

    def test_an_untracked_file_has_no_baseline(self):
        repo = make_repo(self.root)
        commit(repo, "seed.py", "x = 1\n")
        fresh = repo / "fresh.py"
        fresh.write_text(LEGACY, encoding="utf-8")
        self.assertIsNone(baseline.committed_text(fresh))

    def test_a_path_outside_any_repo_has_no_baseline(self):
        loose = self.root / "loose.py"
        loose.write_text(LEGACY, encoding="utf-8")
        self.assertIsNone(baseline.committed_text(loose))

    def test_a_missing_parent_directory_has_no_baseline(self):
        self.assertIsNone(baseline.committed_text(self.root / "gone" / "x.py"))


class StripCommittedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        self.path = commit(self.repo, "legacy.py", LEGACY)

    def tearDown(self):
        self._tmp.cleanup()

    def _findings(self, body: str, cfg: dict | None = None) -> list[dict]:
        self.path.write_text(body, encoding="utf-8")
        rows = scanner.scan_all(str(self.path), body, cfg or {})
        return baseline.strip_committed(self.path, rows, cfg or {})

    def test_committed_debt_alone_reports_nothing(self):
        self.assertEqual(self._findings(LEGACY), [])

    def test_an_unrelated_clean_addition_reports_nothing(self):
        self.assertEqual(self._findings(CLEAN_ADDITION), [])

    def test_debt_the_edit_introduced_still_reports(self):
        rules = [item["rule"] for item in self._findings(EXTRA_DEBT)]
        self.assertIn("what_comment", rules)

    def test_baseline_none_restores_whole_file_scanning(self):
        rules = [item["rule"] for item in self._findings(LEGACY, {"baseline": "none"})]
        self.assertIn("what_comment", rules)

    def _split(self, body: str, cfg: dict) -> tuple[list[dict], list[dict]]:
        self.path.write_text(body, encoding="utf-8")
        return baseline.split_committed(
            self.path, scanner.scan_all(str(self.path), body, cfg), cfg
        )

    def test_report_mode_hands_back_the_inherited_half(self):
        owned, inherited = self._split(EXTRA_DEBT, {"baseline": "report"})
        self.assertEqual([item["rule"] for item in owned], ["what_comment"])
        self.assertEqual([item["snippet"] for item in inherited], ["# increments the counter"])

    def test_git_mode_hands_back_nothing_inherited(self):
        owned, inherited = self._split(EXTRA_DEBT, {"baseline": "git"})
        self.assertEqual([item["rule"] for item in owned], ["what_comment"])
        self.assertEqual(inherited, [])

    def test_none_mode_judges_everything_and_inherits_nothing(self):
        owned, inherited = self._split(EXTRA_DEBT, {"baseline": "none"})
        self.assertEqual(len(owned), 2)
        self.assertEqual(inherited, [])

    def test_the_two_halves_never_overlap(self):
        owned, inherited = self._split(EXTRA_DEBT, {"baseline": "report"})
        self.assertEqual({id(row) for row in owned} & {id(row) for row in inherited}, set())

    def test_an_untracked_file_owns_everything(self):
        fresh = self.repo / "fresh.py"
        fresh.write_text(EXTRA_DEBT, encoding="utf-8")
        cfg = {"baseline": "report"}
        owned, inherited = baseline.split_committed(
            fresh, scanner.scan_all(str(fresh), EXTRA_DEBT, cfg), cfg
        )
        self.assertEqual(len(owned), 2)
        self.assertEqual(inherited, [])

    def test_strip_committed_still_returns_the_owned_half_alone(self):
        self.path.write_text(EXTRA_DEBT, encoding="utf-8")
        cfg = {"baseline": "report"}
        rows = scanner.scan_all(str(self.path), EXTRA_DEBT, cfg)
        self.assertEqual(
            baseline.strip_committed(self.path, rows, cfg),
            baseline.split_committed(self.path, rows, cfg)[0],
        )

    def test_a_finding_any_previous_text_carries_is_inherited(self):
        cfg = {"baseline": "report"}
        rows = scanner.scan_all("legacy.py", EXTRA_DEBT, cfg)
        owned, inherited = baseline.split_against([None, LEGACY, EXTRA_DEBT], "legacy.py", rows, cfg, EXTRA_DEBT)
        self.assertEqual(owned, [])
        self.assertEqual(len(inherited), 2)

    def test_split_against_owns_everything_when_no_previous_text_exists(self):
        cfg = {"baseline": "report"}
        rows = scanner.scan_all("legacy.py", EXTRA_DEBT, cfg)
        self.assertEqual(baseline.split_against([None, None], "legacy.py", rows, cfg, EXTRA_DEBT), (rows, []))
        self.assertEqual(baseline.split_against([], "legacy.py", rows, cfg, EXTRA_DEBT), (rows, []))

    def test_strip_against_still_returns_the_owned_half_alone(self):
        cfg = {"baseline": "report"}
        rows = scanner.scan_all("legacy.py", EXTRA_DEBT, cfg)
        self.assertEqual(
            [item["snippet"] for item in baseline.strip_against([LEGACY], "legacy.py", rows, cfg, EXTRA_DEBT)],
            ["# resets the counter"],
        )


class BaselineRuntimeTests(unittest.TestCase):
    """The reported case end to end: editing a legacy file must not block on its committed debt."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        self.path = commit(self.repo, "legacy.sh", LEGACY)
        self.cfg = {
            "ledger_root": str(self.root / "l"), "state_root": str(self.root / "s"),
            "rule_gates": {"deferred_work_comment": "enforce"},
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _record_response(self, body: str, extra: dict | None = None) -> dict:
        import record
        self.path.write_text(body, encoding="utf-8")
        payload = {
            "session_id": "demo", "cwd": str(self.repo), "tool_name": "Edit",
            "tool_use_id": "t1", "tool_input": {"file_path": str(self.path)},
        }
        return record.run(payload, {**self.cfg, **(extra or {})})

    def _record(self, body: str) -> str:
        return self._record_response(body).get("decision", "allow")

    def _commit_gate_response(self, body: str) -> dict:
        import pre_commit
        self.path.write_text(body, encoding="utf-8")
        git(self.repo, "add", "-A")
        payload = {
            "hook_event_name": "PreToolUse", "session_id": "demo", "cwd": str(self.repo),
            "tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
        }
        return pre_commit.run(payload, self.cfg, self.cfg["ledger_root"], self.cfg["state_root"])

    def _commit_gate(self, body: str) -> str:
        return self._commit_gate_response(body).get("decision", "allow")

    def test_a_clean_edit_to_a_legacy_file_is_allowed(self):
        self.assertEqual(self._record(CLEAN_ADDITION), "allow")

    def test_new_enforced_debt_in_the_same_legacy_file_advises(self):
        response = self._record_response(ENFORCED_DEBT)
        self.assertEqual(response["decision"], "block")
        self.assertIn("legacy.sh:4 Deferred work comment", response["reason"])

    def test_new_what_comment_debt_advises_by_default(self):
        response = self._record_response(EXTRA_DEBT)
        self.assertEqual(response["decision"], "block")
        self.assertIn("legacy.sh:4 Comment restates the code", response["reason"])

    def test_post_write_leaves_inherited_debt_untouched(self):
        import record
        first = "# " + ("TO" + "DO") + " first\nx = 1\n"
        path = commit(self.repo, "todo.py", first)
        updated = first + "# " + ("TO" + "DO") + " second\n"
        path.write_text(updated, encoding="utf-8")
        payload = {
            "session_id": "demo", "cwd": str(self.repo), "tool_name": "Edit",
            "tool_use_id": "t2", "tool_input": {"file_path": str(path)},
        }
        response = record.run(payload, self.cfg)
        message = response["reason"]
        self.assertEqual(path.read_text(encoding="utf-8"), updated)
        self.assertIn(":3 Deferred work comment", message)
        self.assertNotIn("[flagged]", message)
        self.assertIn("already carried 1 findings you did not write", message)

    def test_report_mode_names_the_inherited_debt_in_the_advisory(self):
        message = self._record_response(CLEAN_ADDITION)["systemMessage"]
        self.assertIn("already carried 1 findings you did not write", message)
        self.assertIn("legacy.sh:2 Comment restates the code", message)

    def test_git_mode_stays_silent_about_inherited_debt(self):
        self.assertEqual(self._record_response(CLEAN_ADDITION, {"baseline": "git"}), {})

    def test_inherited_debt_alone_never_blocks(self):
        self.assertNotIn("decision", self._record_response(CLEAN_ADDITION))

    def test_the_commit_gate_allows_staged_legacy_debt(self):
        self.assertEqual(self._commit_gate(CLEAN_ADDITION), "allow")

    def test_the_commit_gate_advises_newly_staged_enforced_debt(self):
        response = self._commit_gate_response(ENFORCED_DEBT)
        self.assertEqual(response["decision"], "block")
        self.assertIn("legacy.sh:4 Deferred work comment", response["reason"])

    def test_the_commit_gate_never_subtracts_a_committed_suppression_marker(self):
        marker = "# craftsman" + "-ignore: PY002\n"
        path = commit(self.repo, "marker.py", marker)
        path.write_text(marker + "value = 1\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        import pre_commit
        response = pre_commit.run(
            {
                "session_id": "demo", "cwd": str(self.repo),
                "tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
            },
            self.cfg,
            self.cfg["ledger_root"], self.cfg["state_root"],
        )

        self.assertEqual(response["decision"], "block")
        self.assertIn("Suppression marker added", response["reason"])


ENGLISH = {"prose_languages": ["en"]}
LONG_FUNCTION = {"function_block_lines": 80}
INTRO = "Intro line here.\n\n"
WRITTEN = INTRO + "The report was written by the team.\n"
FIRST_PARAGRAPH = "The report was written by the team before lunch."
SECOND_PARAGRAPH = "Our second paragraph talks about something else."
THIRD_PARAGRAPH = "A third paragraph closes the short document here."
FIVE_WORD_SENTENCES = (
    "The hook reads each file.",
    "The scan checks every rule.",
    "The gate blocks bad writes.",
    "The ledger keeps each row.",
)
COUNTER = "def count():\n    total = 0\n    # increments the counter\n    total += 1\n    return total\n"
MOVED_COUNTER = "def count():\n    total = 0\n    total += 1\n    # increments the counter\n    return total\n"
REWORDED_TEST_COMMENT = "#!/usr/bin/env python3\n# Test 10: post-{} cleanup\nx = 1\n"
LONG_SOURCE = "".join(f"value_{number} = {number}\n" for number in range(1200))
GENERATED = "# Code generated by protoc. DO NOT EDIT.\n"
GROWN = "extra = 1\n"


class Change(NamedTuple):
    path: str
    before: str
    after: str
    config: dict


def _paragraphs(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs) + "\n"


def _long_function(*extra: str) -> str:
    body = "".join(f"    v{number} = {number}\n" for number in range(90))
    return "import os\n\ndef big():\n" + body + "".join(extra) + "    return v0\n"


class Case(NamedTuple):
    change: Change
    rule: str
    expected: list[tuple[int, bool]]


def _verdicts(rows: list[dict], owned: list[dict], rule: str) -> list[tuple[int, bool]]:
    return [(item["line"], item in owned) for item in rows if item["rule"] == rule]


def _committed_verdicts(root: Path, change: Change, rule: str) -> list[tuple[int, bool]]:
    path = commit(make_repo(root), change.path, change.before)
    path.write_text(change.after, encoding="utf-8")
    rows = scanner.scan_all(str(path), change.after, change.config)
    owned, _inherited = baseline.split_committed(path, rows, {**change.config, "baseline": "report"}, change.after)
    return _verdicts(rows, owned, rule)


def _prose(before: str, after: str) -> Change:
    return Change("doc.md", before, after, ENGLISH)


def _code(before: str, after: str, cfg: dict | None = None) -> Change:
    return Change("mod.py", before, after, cfg or {})


@pytest.mark.parametrize("case", [
    pytest.param(Case(_prose(WRITTEN, WRITTEN), "passive_voice", [(3, False)]), id="unchanged-file"),
    pytest.param(Case(
        _prose(
            INTRO + "The report was written by the team before\nthe meeting began today.\n",
            INTRO + "The report was written\nby the team before the meeting began today.\n"),
        "passive_voice", [(3, False)]), id="reflowed-paragraph"),
    pytest.param(Case(
        _prose(WRITTEN, INTRO + "The plan was drafted by the team.\n"),
        "passive_voice", [(3, True)]), id="new-passive-replacing-an-old-one"),
    pytest.param(Case(
        _prose(
            INTRO + "The report was written by the team. The plan got drafted today.\n",
            INTRO + "The report was written by the team. The plan got approved today.\n"),
        "passive_voice", [(3, False)]), id="match-in-the-unchanged-sentence-of-a-shared-line"),
    pytest.param(Case(
        _prose(
            INTRO + "The plan was drafted by the board. The report goes to the team.\n",
            INTRO + "The plan was approved by the board. The report goes to the team.\n"),
        "passive_voice", [(3, True)]), id="match-in-the-changed-sentence-of-a-shared-line"),
    pytest.param(Case(
        _prose(
            INTRO + "\n".join(FIVE_WORD_SENTENCES) + "\n",
            INTRO + "\n".join(FIVE_WORD_SENTENCES).replace("blocks bad", "stops bad") + "\n"),
        "low_sentence_variance", [(3, True)]), id="third-sentence-of-a-low-variance-paragraph-edited"),
    pytest.param(Case(
        _prose(
            _paragraphs(FIRST_PARAGRAPH, SECOND_PARAGRAPH, THIRD_PARAGRAPH),
            _paragraphs(SECOND_PARAGRAPH, THIRD_PARAGRAPH, FIRST_PARAGRAPH)),
        "passive_voice", [(5, False)]), id="moved-paragraph"),
    pytest.param(Case(
        _prose(
            _paragraphs(FIRST_PARAGRAPH, SECOND_PARAGRAPH, THIRD_PARAGRAPH),
            _paragraphs(FIRST_PARAGRAPH, SECOND_PARAGRAPH, THIRD_PARAGRAPH, FIRST_PARAGRAPH)),
        "passive_voice", [(1, False), (7, True)]), id="extra-copy-of-a-paragraph"),
])
def test_split_committed_owns_a_prose_finding_only_where_a_sentence_changed(tmp_path: Path, case: Case) -> None:
    assert _committed_verdicts(tmp_path, case.change, case.rule) == case.expected


@pytest.mark.parametrize("case", [
    pytest.param(Case(
        _code(LEGACY, LEGACY.replace("\n", "\nimport os\n", 1)), "what_comment", [(3, False)]),
        id="shifted-down-by-an-inserted-line"),
    pytest.param(Case(_code(COUNTER, COUNTER.replace("    ", "  ")), "what_comment", [(3, False)]), id="reindented-block"),
    pytest.param(Case(
        _code(REWORDED_TEST_COMMENT.format("TeamDelete"), REWORDED_TEST_COMMENT.format("shutdown residual")),
        "what_comment", [(2, True)]), id="reworded-offender"),
    pytest.param(Case(
        _code(EXTRA_DEBT, EXTRA_DEBT.replace("resets the counter", "resets the total")),
        "what_comment", [(2, False), (4, True)]), id="reworded-beside-an-unchanged-offender"),
    pytest.param(Case(
        _code(LEGACY, LEGACY.replace("counter", "total") + "# resets the counter\ny = 2\n"),
        "what_comment", [(2, True), (4, True)]), id="added-beside-a-reworded-offender"),
    pytest.param(Case(_code(COUNTER, MOVED_COUNTER), "what_comment", [(4, False)]), id="moved-line"),
    pytest.param(Case(
        _code(LEGACY, LEGACY + "# increments the counter\n"), "what_comment", [(2, False), (4, True)]),
        id="extra-copy-of-a-line"),
    pytest.param(Case(_code("", LEGACY), "what_comment", [(2, True)]), id="empty-committed-file"),
    pytest.param(Case(
        _code(_long_function(), _long_function().replace("    v5 = 5\n", "    v5 = 55\n"), LONG_FUNCTION),
        "function_too_long", [(3, False)]), id="long-function-edited-in-place"),
    pytest.param(Case(
        _code(_long_function(), _long_function("    extra = 1\n"), LONG_FUNCTION),
        "function_too_long", [(3, True)]), id="long-function-grown"),
])
def test_split_committed_owns_a_code_finding_only_where_the_edit_added_it(tmp_path: Path, case: Case) -> None:
    assert _committed_verdicts(tmp_path, case.change, case.rule) == case.expected


@pytest.mark.parametrize(("body", "rule"), [
    pytest.param("# craftsman" + "-ignore: PY002\nvalue = 1\n", "suppression_escape_hatch", id="suppression-marker"),
    pytest.param(LONG_SOURCE[:LONG_SOURCE.index("value_500 ")], "file_length_warning", id="file-length-warning"),
])
def test_a_rule_that_always_reports_stays_owned_in_an_unchanged_file(tmp_path: Path, body: str, rule: str) -> None:
    assert _committed_verdicts(tmp_path, _code(body, body), rule) == [(1, True)]


@pytest.mark.parametrize(("change", "expected"), [
    pytest.param(_code(LONG_SOURCE, LONG_SOURCE.replace("value_5 = 5", "value_5 = 6")), [(1, False)], id="edited-in-place"),
    pytest.param(_code(LONG_SOURCE, LONG_SOURCE + GROWN), [(1, True)], id="grown"),
    pytest.param(_code(GENERATED + LONG_SOURCE, GENERATED + LONG_SOURCE + GROWN), [(1, False)], id="grown-generated-file"),
    pytest.param(_code(LONG_SOURCE, GENERATED + LONG_SOURCE), [(1, True)], id="marker-added-by-the-edit"),
])
def test_file_too_long_is_owned_only_when_the_file_grew(tmp_path: Path, change: Change, expected: list) -> None:
    assert _committed_verdicts(tmp_path, change, "file_too_long") == expected


def test_split_against_owns_a_finding_that_no_previous_text_has() -> None:
    cfg = {"baseline": "report"}
    text = EXTRA_DEBT + "# clears the cache\nz = 3\n"
    rows = scanner.scan_all("legacy.py", text, cfg)

    owned, _inherited = baseline.split_against([LEGACY, EXTRA_DEBT], "legacy.py", rows, cfg, text)

    assert _verdicts(rows, owned, "what_comment") == [(2, False), (4, False), (6, True)]


@pytest.mark.parametrize(("text", "expected"), [
    pytest.param(LONG_SOURCE, [(1, False)], id="taken-whole-from-the-merge-parent"),
    pytest.param(LONG_SOURCE + GROWN, [(1, True)], id="longer-than-every-parent"),
])
def test_a_long_file_keeps_its_length_inherited_when_some_parent_was_as_long(text: str, expected: list) -> None:
    cfg = {"baseline": "report"}
    rows = scanner.scan_all("long.py", text, cfg)

    owned, _inherited = baseline.split_against(["x = 1\n", LONG_SOURCE], "long.py", rows, cfg, text)

    assert _verdicts(rows, owned, "file_too_long") == expected


def test_split_committed_without_text_owns_every_finding_of_a_file_it_cannot_read(tmp_path: Path) -> None:
    path = commit(make_repo(tmp_path), "legacy.py", LEGACY)
    rows = scanner.scan_all(str(path), LEGACY, {})
    path.unlink()

    assert baseline.split_committed(path, rows, {"baseline": "report"}) == (rows, [])

if __name__ == "__main__":
    unittest.main()
