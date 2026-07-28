"""Baseline subtraction: an edit answers for what it changed, not for debt already committed."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import baseline

LEGACY = "#!/usr/bin/env python3\n# increments the counter\nx = 1\n"
EXTRA_DEBT = LEGACY + "# resets the counter\ny = 2\n"
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
    def test_it_defaults_to_git(self):
        self.assertEqual(baseline.baseline_mode({}), "git")

    def test_an_unknown_mode_falls_back_to_git(self):
        self.assertEqual(baseline.baseline_mode({"baseline": "sometimes"}), "git")

    def test_none_is_honored(self):
        self.assertEqual(baseline.baseline_mode({"baseline": "none"}), "none")


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

    def _record(self, body: str) -> str:
        import record
        self.path.write_text(body, encoding="utf-8")
        payload = {
            "session_id": "demo", "cwd": str(self.repo), "tool_name": "Edit",
            "tool_use_id": "t1", "tool_input": {"file_path": str(self.path)},
        }
        return record.run(payload, self.cfg).get("decision", "allow")

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

    def test_new_debt_in_the_same_legacy_file_still_blocks(self):
        self.assertEqual(self._record(EXTRA_DEBT), "block")

    def test_the_commit_gate_allows_staged_legacy_debt(self):
        self.assertEqual(self._commit_gate(CLEAN_ADDITION), "allow")

    def test_the_commit_gate_still_blocks_newly_staged_debt(self):
        self.assertEqual(self._commit_gate(EXTRA_DEBT), "block")


if __name__ == "__main__":
    unittest.main()
