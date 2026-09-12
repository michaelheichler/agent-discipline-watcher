from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pre_commit
from testing import init_repo, make_repo, run_git as git

ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "hooks" / "run.sh"
DIRTY = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
CLEAN = "This sentence is plain and blocks nothing.\n"


def stage(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", name)


def ledger_rows(ledger_root: Path) -> list[dict]:
    path = ledger_root / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CommitGateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.ledger = self.root / "ledger"
        self.state = self.root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, command: str | list[str]) -> dict:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "commit-gate-session",
            "tool_name": "Bash",
            "tool_use_id": "toolu_commit",
            "tool_input": {"command": command},
            "cwd": str(self.repo),
        }
        return pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

    def test_staged_finding_blocks_the_commit(self):
        stage(self.repo, "notes.md", DIRTY)
        result = self.gate('git commit -m "docs(x): add notes"')

        self.assertEqual(result["decision"], "block")
        self.assertIn("notes.md:1 punctuation/banned_dash", result["reason"])

    def test_clean_staged_tree_is_allowed(self):
        stage(self.repo, "notes.md", CLEAN)
        self.assertEqual(self.gate('git commit -m "docs(x): add notes"'), {})

    def test_block_writes_a_pre_commit_ledger_row(self):
        stage(self.repo, "notes.md", DIRTY)
        self.gate('git commit -m "docs(x): add notes"')
        decisions = [row for row in ledger_rows(self.ledger) if row.get("event") == "PreCommit"]

        self.assertEqual(len(decisions), 1, ledger_rows(self.ledger))
        self.assertEqual(decisions[0]["outcome"], "block")
        self.assertEqual(decisions[0]["hook"], "pre_commit")
        self.assertEqual(decisions[0]["path"], "notes.md")

    def test_sessionless_invocation_still_blocks_without_ledger(self):
        stage(self.repo, "notes.md", DIRTY)
        result = pre_commit.run(
            {"tool_input": {"command": "git commit -m msg"}, "cwd": str(self.repo)},
            None,
            ledger_root=self.ledger,
            state_root=self.state,
        )

        self.assertEqual(result["decision"], "block")
        self.assertEqual(ledger_rows(self.ledger), [])

    def test_commit_message_violation_blocks_without_rewriting_command(self):
        command = 'git commit -m "we ship it; it works"'
        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/prose_semicolon", result["reason"])
        self.assertNotIn("updatedInput", result["hookSpecificOutput"])
        self.assertEqual(pre_commit._commit_messages(command), ["we ship it; it works"])

    def test_conventional_subject_prefix_is_metadata(self):
        subjects = (
            "fix: preserve metadata",
            "fix(parser): preserve metadata",
            "fix!: preserve metadata",
            "fix(parser)!: preserve metadata",
        )

        for subject in subjects:
            with self.subTest(subject=subject):
                findings = pre_commit._message_findings(["git", "commit", "-m", subject], {})
                self.assertNotIn("prose_colon", {row["rule"] for row in findings})

        scoped = pre_commit._message_findings(
            ["git", "commit", "-m", "fix(utilize): preserve metadata"], {}
        )
        self.assertNotIn("utilize", {row["rule"] for row in scoped})

    def test_conventional_subject_description_remains_scanned(self):
        findings = pre_commit._message_findings(
            ["git", "commit", "-m", "fix(parser): preserve this: it matters; it works"], {}
        )

        self.assertEqual(
            {(row["rule"], row["line"]) for row in findings if row["family"] == "punctuation"},
            {("prose_colon", 1), ("prose_semicolon", 1)},
        )

    def test_terminal_trailer_prefix_is_metadata_but_its_value_is_prose(self):
        command = [
            "git", "commit",
            "-m", "fix: preserve metadata",
            "-m", "Body label: still prose.",
            "-m", "Co-authored-by: Reason: we ship it; it works",
        ]

        findings = pre_commit._message_findings(command, {})
        punctuation = [row for row in findings if row["family"] == "punctuation"]

        self.assertEqual(
            {(row["rule"], row["line"]) for row in punctuation},
            {("prose_colon", 3), ("prose_colon", 5), ("prose_semicolon", 5)},
        )
        semicolon = next(row for row in punctuation if row["rule"] == "prose_semicolon")
        self.assertEqual(
            semicolon["snippet"], "Co-authored-by: Reason: we ship it; it works"
        )

    def test_trailer_continuation_remains_scanned_on_its_original_line(self):
        message = "Subject\n\nSigned-off-by: A Person\n  We ship it; it works"

        findings = pre_commit._message_findings(["git", "commit", "-m", message], {})

        self.assertIn(
            ("prose_semicolon", 4),
            {(row["rule"], row["line"]) for row in findings},
        )
        self.assertNotIn(
            ("prose_colon", 3),
            {(row["rule"], row["line"]) for row in findings},
        )

    def test_breaking_change_prefix_is_metadata_but_its_value_is_prose(self):
        message = "fix!: update the API\n\nBREAKING CHANGE: Clients stop here; they must update"

        findings = pre_commit._message_findings(["git", "commit", "-m", message], {})
        punctuation = {(row["rule"], row["line"]) for row in findings if row["family"] == "punctuation"}

        self.assertEqual(punctuation, {("prose_semicolon", 3)})

    def test_only_unambiguous_terminal_trailer_blocks_are_metadata(self):
        messages = (
            "Subject\nCo-authored-by: A Person",
            "Subject\n\nNot A Trailer: plain value",
            "Subject\n\nCo-authored-by: A Person\nplain body text",
        )

        for message in messages:
            with self.subTest(message=message):
                findings = pre_commit._message_findings(["git", "commit", "-m", message], {})
                self.assertIn("prose_colon", {row["rule"] for row in findings})

    def test_ansi_c_commit_message_with_escaped_apostrophe_is_scanned(self):
        command = r"git commit -m $'we can\'t; it works'"

        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/prose_semicolon", result["reason"])
        self.assertEqual(pre_commit._commit_messages(command), ["we can't; it works"])

    def test_list_ansi_c_commit_message_with_escaped_apostrophe_is_scanned(self):
        command = ["git", "commit", "-m", "$'your" + "\\'" + "s'"]

        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/pronoun_apostrophe", result["reason"])
        self.assertEqual(pre_commit._commit_messages(command), ["your" + "'" + "s"])

    def test_git_off_path_fails_closed_instead_of_allowing(self):
        stage(self.repo, "notes.md", DIRTY)
        with mock.patch.dict(os.environ, {"PATH": ""}):
            result = self.gate('git commit -m "docs(x): add notes"')

        self.assertEqual(result["decision"], "block")
        self.assertIn("Cause:", result["reason"])

    def test_git_dir_override_fails_closed_instead_of_silently_passing(self):
        non_repo = self.root / "non_repo"
        non_repo.mkdir()
        payload = {
            "tool_input": {"command": "GIT_DIR=/nowhere GIT_WORK_TREE=/nowhere git commit -m x"},
            "cwd": str(non_repo),
        }
        result = pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

        self.assertEqual(result["decision"], "block")
        self.assertIn("Cause:", result["reason"])
        self.assertIn("GIT_DIR", result["reason"])

    def test_env_dash_dash_git_dir_override_fails_closed(self):
        non_repo = self.root / "non_repo_env"
        non_repo.mkdir()
        payload = {
            "tool_input": {"command": "env -- GIT_DIR=/nowhere git commit -m x"},
            "cwd": str(non_repo),
        }
        result = pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

        self.assertEqual(result["decision"], "block")
        self.assertIn("Cause:", result["reason"])
        self.assertIn("GIT_DIR", result["reason"])

    def test_a_fatal_error_other_than_missing_repository_is_not_swallowed(self):
        with mock.patch(
            "pre_commit.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, ["git"], stderr="fatal: bad revision 'x'\n"),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                pre_commit._repo_root(self.repo)

    def test_missing_repository_message_still_reads_as_no_repository(self):
        with mock.patch(
            "pre_commit.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                128, ["git"], stderr="fatal: not a git repository (or any of the parent directories): .git\n",
            ),
        ):
            self.assertIsNone(pre_commit._repo_root(self.repo))

    def test_two_repos_are_each_adjudicated_under_their_own_config(self):
        other = self.root / "other"
        other.mkdir()
        init_repo(other)
        (other / ".agent-discipline.json").write_text(
            json.dumps({"gates": {"punctuation": "off"}}), encoding="utf-8",
        )
        stage(other, "notes.md", DIRTY)
        command = f"git -C {self.repo} commit --allow-empty -m empty && git -C {other} commit -m test"
        result = pre_commit.run(
            {"tool_input": {"command": command}, "cwd": str(self.root)},
            None,
            ledger_root=self.ledger, state_root=self.state,
        )

        self.assertEqual(result, {})

    def test_run_sh_pretooluse_route_blocks_a_commit_end_to_end(self):
        stage(self.repo, "notes.md", DIRTY)
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs(x): y"'},
            "cwd": str(self.repo),
        })
        env = dict(os.environ, HOME=str(self.root))
        result = subprocess.run(
            [str(RUN_SH), "PreToolUse"], input=payload, text=True,
            capture_output=True, check=False, env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertNotIn("decision", response)
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("banned_dash", response["hookSpecificOutput"]["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
