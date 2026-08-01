"""Baseline subtraction: an edit answers for what it changed, not for debt already committed."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import baseline

LEGACY = "#!/usr/bin/env python3\n# increments the counter\nx = 1\n"
EXTRA_DEBT = LEGACY + "# resets the counter\ny = 2\n"
# Defer the literal because the discipline scanner would otherwise flag this test file.
ENFORCED_DEBT = LEGACY + "# " + ("TO" + "DO") + " later\ny = 2\n"
CLEAN_ADDITION = LEGACY + "z = 3\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "baseline@example.test")
    git(repo, "config", "user.name", "Baseline Test")
    return repo


def commit(repo: Path, name: str, body: str) -> Path:
    path = repo / name
    path.write_text(body, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "seed")
    return path


def row(rule: str, snippet: str, line: int = 1) -> dict:
    return {"family": "clean_code", "rule": rule, "snippet": snippet, "line": line}


class FindingKeyTests(unittest.TestCase):
    def test_the_key_ignores_the_line_number(self):
        self.assertEqual(baseline.finding_key(row("a", "s", 1)), baseline.finding_key(row("a", "s", 90)))

    def test_the_key_separates_different_rules_and_snippets(self):
        self.assertNotEqual(baseline.finding_key(row("a", "s")), baseline.finding_key(row("b", "s")))
        self.assertNotEqual(baseline.finding_key(row("a", "s")), baseline.finding_key(row("a", "t")))


class SubtractTests(unittest.TestCase):
    def test_a_finding_the_baseline_already_had_is_dropped(self):
        self.assertEqual(baseline.subtract([row("a", "s")], [row("a", "s", 40)]), [])

    def test_an_extra_copy_of_a_repeated_finding_survives(self):
        current = [row("a", "s"), row("a", "s"), row("a", "s")]
        self.assertEqual(len(baseline.subtract(current, [row("a", "s"), row("a", "s")])), 1)

    def test_a_finding_absent_from_the_baseline_survives(self):
        self.assertEqual(baseline.subtract([row("b", "t")], [row("a", "s")]), [row("b", "t")])

    def test_an_empty_baseline_keeps_everything(self):
        self.assertEqual(baseline.subtract([row("a", "s")], []), [row("a", "s")])


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
        import config
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
        from scanner import scan_all
        self.path.write_text(body, encoding="utf-8")
        rows = scan_all(str(self.path), body, cfg or {})
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
        from scanner import scan_all
        self.path.write_text(body, encoding="utf-8")
        return baseline.split_committed(self.path, scan_all(str(self.path), body, cfg), cfg)

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
        from scanner import scan_all
        fresh = self.repo / "fresh.py"
        fresh.write_text(EXTRA_DEBT, encoding="utf-8")
        cfg = {"baseline": "report"}
        owned, inherited = baseline.split_committed(fresh, scan_all(str(fresh), EXTRA_DEBT, cfg), cfg)
        self.assertEqual(len(owned), 2)
        self.assertEqual(inherited, [])

    def test_strip_committed_still_returns_the_owned_half_alone(self):
        from scanner import scan_all
        self.path.write_text(EXTRA_DEBT, encoding="utf-8")
        cfg = {"baseline": "report"}
        rows = scan_all(str(self.path), EXTRA_DEBT, cfg)
        self.assertEqual(
            baseline.strip_committed(self.path, rows, cfg),
            baseline.split_committed(self.path, rows, cfg)[0],
        )

    def test_strip_against_still_returns_the_owned_half_alone(self):
        from scanner import scan_all
        cfg = {"baseline": "report"}
        rows = scan_all("legacy.py", EXTRA_DEBT, cfg)
        self.assertEqual(
            [item["snippet"] for item in baseline.strip_against(LEGACY, "legacy.py", rows, cfg)],
            ["# resets the counter"],
        )


class BaselineRuntimeTests(unittest.TestCase):
    """The reported case end to end: editing a legacy file must not block on its committed debt."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        self.path = commit(self.repo, "legacy.sh", LEGACY)
        self.cfg = {"ledger_root": str(self.root / "l"), "state_root": str(self.root / "s")}

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

    def _commit_gate(self, body: str) -> str:
        import pre_commit
        self.path.write_text(body, encoding="utf-8")
        git(self.repo, "add", "-A")
        payload = {
            "hook_event_name": "PreToolUse", "session_id": "demo", "cwd": str(self.repo),
            "tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
        }
        response = pre_commit.run(payload, self.cfg, self.cfg["ledger_root"], self.cfg["state_root"])
        return response.get("decision", "allow")

    def test_a_clean_edit_to_a_legacy_file_is_allowed(self):
        self.assertEqual(self._record(CLEAN_ADDITION), "allow")

    def test_new_enforced_debt_in_the_same_legacy_file_still_blocks(self):
        self.assertEqual(self._record(ENFORCED_DEBT), "block")

    def test_new_what_comment_debt_is_blocked_by_default(self):
        response = self._record_response(EXTRA_DEBT)
        self.assertEqual(response["decision"], "block")
        self.assertIn("legacy.sh:4 clean_code/what_comment", response["reason"])

    def test_report_mode_names_the_inherited_debt_in_the_advisory(self):
        message = self._record_response(CLEAN_ADDITION)["systemMessage"]
        self.assertIn("already carried 1 findings you did not write", message)
        self.assertIn("legacy.sh:2 clean_code/what_comment", message)

    def test_git_mode_stays_silent_about_inherited_debt(self):
        self.assertEqual(self._record_response(CLEAN_ADDITION, {"baseline": "git"}), {})

    def test_inherited_debt_alone_never_blocks(self):
        self.assertNotIn("decision", self._record_response(CLEAN_ADDITION))

    def test_the_commit_gate_allows_staged_legacy_debt(self):
        self.assertEqual(self._commit_gate(CLEAN_ADDITION), "allow")

    def test_the_commit_gate_still_blocks_newly_staged_enforced_debt(self):
        self.assertEqual(self._commit_gate(ENFORCED_DEBT), "block")


class RewordedFindingTests(unittest.TestCase):
    """Renaming the text of a line that already broke the same rule adds no debt."""

    def test_a_reworded_offender_is_not_new_debt(self):
        before = [row("what_comment", "# Test 10: post-TeamDelete cleanup")]
        after = [row("what_comment", "# Test 10: post-shutdown residual cleanup")]
        self.assertEqual(baseline.subtract(after, before), [])

    def test_an_added_offender_still_reports_alongside_a_reworded_one(self):
        before = [row("what_comment", "# old one")]
        after = [row("what_comment", "# reworded one"), row("what_comment", "# a brand new one")]
        self.assertEqual(len(baseline.subtract(after, before)), 1)

    def test_a_different_rule_is_never_covered_by_the_loose_pass(self):
        before = [row("what_comment", "# old one")]
        after = [row("banned_dash", "some other line")]
        self.assertEqual(len(baseline.subtract(after, before)), 1)

    def test_the_exact_pass_still_runs_first(self):
        shared = row("what_comment", "# identical")
        before = [shared, row("what_comment", "# other")]
        after = [shared, row("what_comment", "# reworded other")]
        self.assertEqual(baseline.subtract(after, before), [])


if __name__ == "__main__":
    unittest.main()
