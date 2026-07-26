import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / "hooks" / "merge-claude-settings.py"
CODEX = ROOT / "hooks" / "merge-codex-config.py"
PI = ROOT / "hooks" / "merge-pi-settings.py"

CLAUDE_SETTINGS = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {"type": "command", "command": "python punctuation-discipline/hooks/stop.py"},
                    {"type": "command", "command": "python /x/unrelated-stop.py"},
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {"type": "command", "command": "python english-for-agents/hooks/post.py"},
                    {
                        "type": "command",
                        "command": "python /x/knowledge-based-search/hooks/method_inject.py",
                    },
                ]
            }
        ],
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py",
                    }
                ]
            }
        ],
    }
}

UNCLE_BOBS_CC_SETTINGS = {
    "model": "claude-opus-4",
    "env": {"SOME_FLAG": "1"},
    "statusLine": {"type": "command", "command": "echo hi"},
    "permissions": {"allow": ["Bash(ls:*)"], "deny": []},
    "hooks": {
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/session_start.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/punct_session_start.py"
                        ),
                    },
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/punct_gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/record.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/punct_record.py"
                        ),
                    },
                    {"type": "command", "command": "python /x/unrelated-stop.py"},
                ]
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit|NotebookEdit|apply_patch",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/pre_write.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": "/stale/agent-discipline-watcher/hooks/run.sh PreToolUse",
                    },
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh "
                            "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/pre_commit_hook.py"
                        ),
                    }
                ],
            },
        ],
    },
}

CODEX_CONFIG = """
[hooks]
Stop = [{ command = "python professional-agent-helper/hooks/stop.py" }, { command = "python /x/unrelated-inline.py" }]
SessionStart = [{ command = "python punctuation-discipline/hooks/start.py" }]
UserPromptSubmit = [{ command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py" }]

[[hooks.UserPromptSubmit]]

[[hooks.UserPromptSubmit]]

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "python /x/knowledge-based-search/hooks/prompt_inject.py"

# >>> agent-discipline-watcher >>>
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/tmp/agent-discipline-watcher/hooks/run.sh Stop"

[mcp_servers.knowledge-based-search]
command = "/x/skill-model-loader/.venv/bin/python"
args = ["/x/knowledge-based-search/server/mcp_server.py"]

[mcp_servers.lean-ctx]
command = "/x/lean-ctx/bin/lean-ctx"
args = ["serve", "--config", "/x/lean-ctx/config.toml"]
# <<< agent-discipline-watcher <<<

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "python /x/unrelated-stop.py"
"""

CODEX_CONFIG_UNCLE_BOBS_CC = """
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh /home/user/Development/skill-repos/uncle-bobs-cc/hooks/session_start.py"
[[hooks.SessionStart.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh /home/user/Development/skill-repos/uncle-bobs-cc/hooks/punct_session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh /home/user/Development/skill-repos/uncle-bobs-cc/hooks/gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/uncle-bobs-cc/hooks/run.sh /home/user/Development/skill-repos/uncle-bobs-cc/hooks/punct_gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "python /x/unrelated-stop.py"
"""

# Keep this regression case because trailing tables after legacy hooks caused config loss.
CODEX_CONFIG_TRAILING_TABLES = """
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/professional-agent-helper/hooks/run.sh /home/user/Development/skill-repos/professional-agent-helper/hooks/session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/professional-agent-helper/hooks/run.sh /home/user/Development/skill-repos/professional-agent-helper/hooks/gate.py"

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "/home/user/Development/skill-repos/professional-agent-helper/hooks/run.sh /home/user/Development/skill-repos/professional-agent-helper/hooks/prompt_inject.py"

[[hooks.state.trusted_projects]]
path = "/home/user/project1"
trust = "trusted"

[[hooks.state.trusted_projects]]
path = "/home/user/project2"
trust = "trusted"

[projects."/home/user/project1"]
trust_level = "trusted"

[tui.model_availability_nux]
shown = true

[mcp_servers.alpha]
command = "alpha-bin"
args = ["serve"]

[mcp_servers.alpha.http_headers]
Authorization = "Bearer alpha"

[mcp_servers.beta]
command = "beta-bin"

[mcp_servers.gamma]
command = "gamma-bin"
"""

PI_SETTINGS = {
    "extensions": [
        "/x/punctuation-discipline/pi/extensions/punctuation-discipline/index.ts",
        "/x/english-for-agents/pi/extensions/english-for-agents/index.ts",
        "/x/professional-agent-helper/pi/extensions/professional-agent-helper/index.ts",
        "/x/unrelated",
    ]
}


def run_merge(script: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script), *args], check=True)


def load_codex_merger():
    spec = importlib.util.spec_from_file_location("agent_discipline_codex_merge", CODEX)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def assert_no_stale_hooks(text: str) -> None:
    assert "punctuation-discipline" not in text
    assert "english-for-agents" not in text
    assert "knowledge-based-search/hooks" not in text
    assert "professional-agent-helper" not in text


def assert_watcher_hook_family(text: str, stop_wired: bool = False) -> None:
    for event in ("PreToolUse", "PostToolUse", "SessionStart"):
        assert event in text
    for event in ("PreToolUse", "PreCommit", "PostToolUse", "SessionStart"):
        assert f"run.sh {event}" in text
    assert ("run.sh Stop" in text) is stop_wired
    assert "run.sh UserPromptSubmit" not in text


class MergeConfigTests(unittest.TestCase):
    def test_claude_removes_legacy_hooks_and_adds_watcher_family(self):
        assert CLAUDE.exists()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(CLAUDE_SETTINGS))
            run_merge(CLAUDE, "--settings", str(settings), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = json.loads(settings.read_text())
        assert_claude_merge(merged)

    def test_claude_strips_uncle_bobs_cc_and_preserves_unrelated_top_level_keys(self):
        assert CLAUDE.exists()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(UNCLE_BOBS_CC_SETTINGS))
            run_merge(CLAUDE, "--settings", str(settings), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = json.loads(settings.read_text())
        assert_uncle_bobs_cc_merge(merged)

    def test_claude_if_filter_and_async_convention_survive_double_merge(self):
        assert CLAUDE.exists()
        merge_args = ("--skill-dir", "/tmp/agent-discipline-watcher")  # noqa: S108 (placeholder path, never created)
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(CLAUDE_SETTINGS))
            run_merge(CLAUDE, "--settings", str(settings), *merge_args)
            run_merge(CLAUDE, "--settings", str(settings), *merge_args)
            merged = json.loads(settings.read_text())
        assert_claude_bash_if_filter(merged)
        assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])
        assert_claude_stop_entry(merged)
        assert_no_async_flags(merged)

    def test_codex_removes_legacy_hooks_and_adds_watcher_family(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG)
            run_merge(CODEX, "--config", str(config), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = config.read_text()
        assert_codex_merge(merged)

    def test_codex_strips_uncle_bobs_cc(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG_UNCLE_BOBS_CC)
            run_merge(CODEX, "--config", str(config), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = config.read_text()
        assert "uncle-bobs-cc" not in merged
        assert "unrelated-stop.py" in merged
        assert_watcher_hook_family(merged)

    def test_codex_preserves_tables_after_last_legacy_hooks_block(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG_TRAILING_TABLES)
            run_merge(CODEX, "--config", str(config), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = config.read_text()
        assert_trailing_tables_survive(merged)

    def test_codex_rejects_unrelated_section_loss(self):
        merger = load_codex_merger()
        before = '[projects."/work"]\ntrust_level = "trusted"\n\n[mcp_servers.library]\nurl = "http://library/mcp"\n'
        after = '[projects."/work"]\ntrust_level = "trusted"\n'
        with self.assertRaisesRegex(ValueError, "mcp_servers"):
            merger.validate_preserved_sections(before, after)

    def test_codex_failed_atomic_replace_leaves_original_unchanged(self):
        merger = load_codex_merger()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            original = 'model = "gpt-5.6-sol"\n'
            config.write_text(original)
            with mock.patch.object(merger.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    merger.atomic_write(config, original + 'model_verbosity = "low"\n')
            self.assertEqual(config.read_text(), original)
            self.assertEqual(list(config.parent.glob(f".{config.name}.*.tmp")), [])

    def test_codex_atomic_write_preserves_mode_and_secures_new_files(self):
        merger = load_codex_merger()
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.toml"
            existing.write_text('model = "old"\n')
            existing.chmod(0o640)
            merger.atomic_write(existing, 'model = "new"\n')
            self.assertEqual(existing.stat().st_mode & 0o777, 0o640)

            created = Path(tmp) / "created.toml"
            merger.atomic_write(created, 'model = "new"\n')
            self.assertEqual(created.stat().st_mode & 0o777, 0o600)

    def test_pi_removes_legacy_extensions_and_adds_one_watcher_extension(self):
        assert PI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(PI_SETTINGS))
            run_merge(PI, "--settings", str(settings), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = json.loads(settings.read_text())
        assert_pi_merge(merged)


def assert_claude_merge(merged: dict) -> None:
    text = json.dumps(merged)
    assert_no_stale_hooks(text)
    assert "unrelated-stop.py" in text
    assert_watcher_hook_family(text, stop_wired=True)
    assert_claude_stop_entry(merged)
    assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])
    assert "compact" in merged["hooks"]["SessionStart"][0]["matcher"]
    assert "run.sh UserPromptSubmit" not in text


def assert_claude_stop_entry(merged: dict) -> None:
    entries = merged["hooks"]["Stop"]
    watcher = [entry for entry in entries if "agent-discipline-watcher" in json.dumps(entry)]
    assert len(watcher) == 1, "Stop must merge to exactly one watcher entry, re-running install must not stack"
    assert "matcher" not in watcher[0], "Stop carries no matcher, an unknown key can break config parsing"
    assert watcher[0]["hooks"] == [
        {"type": "command", "command": "/tmp/agent-discipline-watcher/hooks/run.sh Stop"}
    ]
    assert "unrelated-stop.py" in json.dumps(entries)


def assert_claude_bash_if_filter(merged: dict) -> None:
    bash_entries = [
        entry for entry in merged["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Bash"
    ]
    assert len(bash_entries) == 1, "Bash matcher must be unique after merge"
    commands = bash_entries[0]["hooks"]
    assert len(commands) == 1, "Bash matcher must own exactly one watcher command"
    assert commands[0].get("if") == "Bash(git commit *)", (
        "if filter must use the documented word-boundary form so it matches git commit "
        "with args but not git commit-tree, and a wrong literal disables the gate silently"
    )
    assert "run.sh PreCommit" in commands[0]["command"]


def assert_no_async_flags(merged: dict) -> None:
    watcher_groups = [
        group for lifecycle in merged["hooks"].values() for group in lifecycle
        if "agent-discipline-watcher" in json.dumps(group)
    ]
    assert watcher_groups, "watcher groups must be present before the async guard runs"
    for group in watcher_groups:
        for hook in group["hooks"]:
            assert "async" not in hook, (
                "async detaches a deny-capable watcher entry so it cannot block: "
                f"{hook['command']}"
            )
            assert "asyncRewake" not in hook, (
                "asyncRewake implies async and would detach this deny-capable entry: "
                f"{hook['command']}"
            )


def assert_claude_pretool_shape(entries: list[dict]) -> None:
    watcher_entries = [entry for entry in entries if "agent-discipline-watcher" in json.dumps(entry)]
    assert len(watcher_entries) == 2
    by_matcher = {entry["matcher"]: entry for entry in watcher_entries}
    assert "Bash" in by_matcher
    assert "run.sh PreCommit" in json.dumps(by_matcher["Bash"])
    write_matcher = next(matcher for matcher in by_matcher if matcher != "Bash")
    assert "NotebookEdit" in write_matcher
    assert "apply_patch" in write_matcher


def assert_uncle_bobs_cc_merge(merged: dict) -> None:
    text = json.dumps(merged)
    assert merged["model"] == "claude-opus-4"
    assert merged["env"] == {"SOME_FLAG": "1"}
    assert merged["statusLine"] == {"type": "command", "command": "echo hi"}
    assert merged["permissions"] == {"allow": ["Bash(ls:*)"], "deny": []}
    assert "uncle-bobs-cc" not in text
    assert "session_start.py" not in text
    assert "punct_session_start.py" not in text
    assert "gate.py" not in text
    assert "punct_gate.py" not in text
    assert "record.py" not in text
    assert "punct_record.py" not in text
    assert "pre_write.py" not in text
    assert "pre_commit_hook.py" not in text
    assert "unrelated-stop.py" in text
    assert "/stale/agent-discipline-watcher" not in text
    assert_watcher_hook_family(text, stop_wired=True)
    assert_claude_stop_entry(merged)
    assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])


def assert_codex_merge(merged: str) -> None:
    assert_no_stale_hooks(merged)
    assert "clean-coder-discipline" not in merged
    assert "unrelated-stop.py" in merged
    assert "unrelated-inline.py" in merged
    assert "[mcp_servers.knowledge-based-search]" in merged
    assert "/x/knowledge-based-search/server/mcp_server.py" in merged
    assert "[mcp_servers.lean-ctx]" in merged
    assert "/x/lean-ctx/config.toml" in merged
    assert "\n[[hooks.UserPromptSubmit]]\n\n[[hooks.UserPromptSubmit]]" not in merged
    assert_watcher_hook_family(merged)
    assert 'matcher = "Bash"' in merged
    assert 'matcher = "apply_patch|Edit|Write"' in merged


def assert_trailing_tables_survive(merged: str) -> None:
    assert "professional-agent-helper" not in merged
    assert merged.count("[[hooks.state.trusted_projects]]") == 2
    assert '[projects."/home/user/project1"]' in merged
    assert "[tui.model_availability_nux]" in merged
    for server in ("alpha", "beta", "gamma"):
        assert f"[mcp_servers.{server}]" in merged
    assert "[mcp_servers.alpha.http_headers]" in merged
    assert_watcher_hook_family(merged)


def assert_pi_merge(merged: dict) -> None:
    text = json.dumps(merged)
    assert_no_stale_hooks(text)
    assert merged["extensions"][0] == "/x/unrelated"
    assert merged["extensions"][1] == (
        "/tmp/agent-discipline-watcher/pi/extensions/agent-discipline-watcher/index.ts"
    )


if __name__ == "__main__":
    unittest.main()
