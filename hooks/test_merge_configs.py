import importlib.util
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / "hooks" / "merge-claude-settings.py"
CODEX = ROOT / "hooks" / "merge-codex-config.py"
CODEX_SNIPPET = ROOT / "hooks" / "codex-config.snippet.toml"

STALE_WATCHER_RUN_SH = "/stale/agent-discipline-watcher/hooks/run.sh"
SKILL_DIR = "/opt/adw-checkout"  # noqa: S108 (placeholder path, never created)

WIRED_EVENTS = frozenset({
    "ConfigChange",
    "InstructionsLoaded",
    "PostToolBatch",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "SubagentStop",
    "TaskCompleted",
    "UserPromptSubmit",
})

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
                        "command": "python /x/unrelated-search-skill/hooks/method_inject.py",
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
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/session_start.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_session_start.py"
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
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/record.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_record.py"
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
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/pre_write.py"
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
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/pre_commit_hook.py"
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
command = "python /x/unrelated-search-skill/hooks/prompt_inject.py"

# >>> agent-discipline-watcher >>>
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/tmp/agent-discipline-watcher/hooks/run.sh Stop"

[mcp_servers.unrelated-search-skill]
command = "/x/unrelated-runtime/.venv/bin/python"
args = ["/x/unrelated-search-skill/server/mcp_server.py"]

[mcp_servers.unrelated-context-skill]
command = "/x/unrelated-context-skill/bin/unrelated-context-skill"
args = ["serve", "--config", "/x/unrelated-context-skill/config.toml"]
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
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/session_start.py"
[[hooks.SessionStart.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/punct_session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/punct_gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "python /x/unrelated-stop.py"
"""

# Keep this regression case because trailing tables after legacy hooks caused config loss.
CODEX_CONFIG_TRAILING_TABLES = """
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/gate.py"

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py"

[[hooks.state.trusted_projects]]
path = "/x/project1"
trust = "trusted"

[[hooks.state.trusted_projects]]
path = "/x/project2"
trust = "trusted"

[projects."/x/project1"]
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

CODEX_CONFIG_NEW_EVENT_INLINE_ARRAYS = (
    "\n[hooks]\n"
    'SubagentStop = [{ command = "python professional-agent-helper/hooks/sub.py" },'
    ' { command = "python /x/unrelated-subagent.py" }]\n'
    'PostToolBatch = [{ command = "python punctuation-discipline/hooks/batch.py" }]\n'
    'TaskCompleted = [{ command = "python english-for-agents/hooks/task.py" }]\n'
    'PostToolUseFailure = [{ command = "python clean-coder-discipline/hooks/fail.py" }]\n'
    'InstructionsLoaded = [{ command = "python uncle-bobs-cc/hooks/loaded.py" }]\n'
    f'ConfigChange = [{{ command = "{STALE_WATCHER_RUN_SH} ConfigChange" }},'
    ' { command = "python /x/unrelated-config.py" }]\n'
)

def run_merge(script: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script), *args], check=True)


def load_codex_merger():
    spec = importlib.util.spec_from_file_location("agent_discipline_codex_merge", CODEX)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def assert_no_stale_hooks(text: str) -> None:
    assert "punctuation-discipline" not in text
    assert "english-for-agents" not in text
    assert "professional-agent-helper" not in text
    assert "uncle-bobs-cc" not in text


UNRELATED_SURVIVORS = ("unrelated-search-skill", "unrelated-context-skill", "unrelated-third-skill")
UNRELATED_PACKAGE_SETTINGS = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {"type": "command", "command": "python /x/unrelated-search-skill/hooks/skill_gate.py"},
                    {"type": "command", "command": "/x/unrelated-context-skill/bin/unrelated-context-skill serve"},
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {"type": "command", "command": "python /x/unrelated-third-skill/hooks/post.py"},
                    {"type": "command", "command": "python punctuation-discipline/hooks/post.py"},
                ]
            }
        ],
    }
}

ARBITRARY_EVENT_SETTINGS = {
    "hooks": {
        "SubagentStop": [
            {
                "hooks": [
                    {"type": "command", "command": f"{STALE_WATCHER_RUN_SH} SubagentStop"},
                    {"type": "command", "command": "python /x/unrelated-subagent.py"},
                ]
            }
        ],
        "ConfigChange": [
            {
                "hooks": [
                    {"type": "command", "command": "python punctuation-discipline/hooks/config.py"},
                ]
            }
        ],
    }
}


def merge_twice(script: Path, payload: dict) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "settings.json"
        settings.write_text(json.dumps(payload))
        run_merge(script, "--settings", str(settings), "--skill-dir", SKILL_DIR)
        once = settings.read_text()
        run_merge(script, "--settings", str(settings), "--skill-dir", SKILL_DIR)
        return once, settings.read_text()


def assert_arbitrary_event_prune(merged: dict) -> None:
    text = json.dumps(merged)
    assert "punctuation-discipline" not in text
    assert "/stale/agent-discipline-watcher" not in text
    subagent_entries = merged["hooks"]["SubagentStop"]
    assert "SubagentStop" in json.dumps(subagent_entries)
    assert "unrelated-subagent.py" in json.dumps(subagent_entries)
    assert "ConfigChange" not in merged["hooks"] or "punctuation-discipline" not in json.dumps(
        merged["hooks"]["ConfigChange"]
    )


CLAUDE_ROUTES = (
    "SessionStart", "UserPromptSubmit", "PreToolUse",
    "PostToolUse", "PostToolBatch", "PostToolUseFailure", "SubagentStart",
    "SubagentStop", "Stop",
)
# Listed separately because Codex wires a reduced set and must not gain Claude-only routes.
CODEX_ROUTES = ("SessionStart", "PreToolUse", "PostToolUse")


def _route_pattern(route: str) -> re.Pattern[str]:
    # Tolerates an escaped closing quote because the merged command quotes the whole run.sh path.
    return re.compile(r'run\.sh\\?"?\s*' + re.escape(route) + r'\b')


def assert_watcher_hook_family(text: str, routes: tuple[str, ...] = CODEX_ROUTES) -> None:
    for event in ("PreToolUse", "PostToolUse", "SessionStart"):
        assert event in text
    for route in routes:
        assert _route_pattern(route).search(text), f"{route} route missing from the merged config"
    for route in set(CLAUDE_ROUTES) - set(routes):
        assert not _route_pattern(route).search(text), f"{route} must not appear on this surface"


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

    def test_claude_pretool_shape_and_async_convention_survive_double_merge(self):
        assert CLAUDE.exists()
        merge_args = ("--skill-dir", "/tmp/agent-discipline-watcher")  # noqa: S108 (placeholder path, never created)
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(CLAUDE_SETTINGS))
            run_merge(CLAUDE, "--settings", str(settings), *merge_args)
            run_merge(CLAUDE, "--settings", str(settings), *merge_args)
            merged = json.loads(settings.read_text())
        assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])
        assert_no_async_flags(merged)

    def test_claude_double_merge_is_idempotent_for_a_skill_dir_without_the_package_name(self):
        assert CLAUDE.exists()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps({}))
            run_merge(CLAUDE, "--settings", str(settings), "--skill-dir", SKILL_DIR)
            once = settings.read_text()
            run_merge(CLAUDE, "--settings", str(settings), "--skill-dir", SKILL_DIR)
            twice = settings.read_text()
        assert once == twice, "a second merge from the same skill dir must not duplicate entries"
        merged = json.loads(twice)
        expected_counts = {"SessionStart": 1, "PreToolUse": 1, "PostToolUse": 1, "Stop": 1}
        for lifecycle, expected in expected_counts.items():
            groups = merged["hooks"][lifecycle]
            watcher_groups = [group for group in groups if SKILL_DIR in json.dumps(group)]
            assert len(watcher_groups) == expected, f"{lifecycle} doubled on re-merge"

    def test_claude_merge_writes_through_a_settings_symlink(self):
        assert CLAUDE.exists()
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real"
            real_dir.mkdir()
            real_settings = real_dir / "settings.json"
            real_settings.write_text(json.dumps({"model": "claude-opus-5"}))
            link = Path(tmp) / "settings.json"
            link.symlink_to(real_settings)
            run_merge(CLAUDE, "--settings", str(link), "--skill-dir", SKILL_DIR)
            self.assertTrue(link.is_symlink(), "merge must not swap the symlink for a plain file")
            merged = json.loads(real_settings.read_text())
        self.assertEqual(merged["model"], "claude-opus-5")
        self.assertIn("PreToolUse", merged["hooks"])

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

    def test_codex_mentions_legacy_requires_a_full_name_not_a_substring(self):
        merger = load_codex_merger()
        assert merger._mentions_legacy("professional-agent-helper/hooks/stop.py")
        assert not merger._mentions_legacy("my-professional-agent-helper-fork/hooks/stop.py")

    def test_codex_preserves_a_differently_named_fork_of_a_legacy_package(self):
        assert CODEX.exists()
        config_text = (
            "[hooks]\n"
            'Stop = [{ command = "python my-professional-agent-helper-fork/hooks/stop.py" }]\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(config_text)
            run_merge(CODEX, "--config", str(config), "--skill-dir", SKILL_DIR)
            merged = config.read_text()
        assert "my-professional-agent-helper-fork" in merged
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

    def test_codex_hook_lifecycles_cover_every_wired_event(self):
        merger = load_codex_merger()
        missing = sorted(WIRED_EVENTS - merger.HOOK_LIFECYCLES)
        assert not missing, (
            "HOOK_LIFECYCLES misses wired events, stale-strip mishandles them on reinstall: "
            f"{missing}"
        )

    def test_codex_hook_lifecycles_cover_snippet_events(self):
        merger = load_codex_merger()
        snippet_events = set(
            re.findall(r"\[\[hooks\.([A-Za-z]+)(?:\.hooks)?\]\]", CODEX_SNIPPET.read_text())
        )
        missing = sorted(snippet_events - merger.HOOK_LIFECYCLES)
        assert not missing, f"snippet wires events HOOK_LIFECYCLES cannot strip: {missing}"

    def test_codex_snippet_only_calls_dispatch_routes(self):
        run_sh = ROOT / "hooks" / "run.sh"
        raw_dispatch = run_sh.read_text().split('DISPATCH="', 1)[1].split('"', 1)[0]
        dispatch_routes = {pair.split(":", 1)[0] for pair in raw_dispatch.split()}
        snippet_routes = set(
            re.findall(r'run\.sh\\?"?\s+([A-Za-z]+)', CODEX_SNIPPET.read_text())
        )
        unknown = sorted(snippet_routes - dispatch_routes)
        assert not unknown, f"Codex calls routes run.sh cannot dispatch: {unknown}"

    def test_codex_strips_stale_inline_arrays_for_new_events(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG_NEW_EVENT_INLINE_ARRAYS)
            run_merge(CODEX, "--config", str(config), "--skill-dir", SKILL_DIR)
            merged = config.read_text()
        assert_no_stale_hooks(merged)
        assert "clean-coder-discipline" not in merged
        assert "uncle-bobs-cc" not in merged
        assert "/stale/agent-discipline-watcher" not in merged
        assert "unrelated-subagent.py" in merged
        assert "unrelated-config.py" in merged

    def test_codex_double_merge_is_idempotent(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG)
            run_merge(CODEX, "--config", str(config), "--skill-dir", SKILL_DIR)
            once = config.read_text()
            run_merge(CODEX, "--config", str(config), "--skill-dir", SKILL_DIR)
            twice = config.read_text()
        assert once == twice, "second merge must not duplicate or corrupt entries"
        assert twice.count("# >>> agent-discipline-watcher >>>") == 1
        watcher_block = twice.split("# >>> agent-discipline-watcher >>>", 1)[1].split(
            "# <<< agent-discipline-watcher <<<", 1
        )[0]
        expected_counts = {"SessionStart": 1, "PreToolUse": 2, "PostToolUse": 1}
        for event, expected in expected_counts.items():
            needle = f'command = "\\"{SKILL_DIR}/hooks/run.sh\\" {event}"'
            assert watcher_block.count(needle) == expected

    def test_codex_snippet_quotes_the_executable_for_a_skill_dir_with_a_space(self):
        assert CODEX.exists()
        skill_dir = "/opt/agent discipline watcher"
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            run_merge(CODEX, "--config", str(config), "--skill-dir", skill_dir)
            merged = config.read_text()
        merger = load_codex_merger()
        data = merger.tomllib.loads(merged)
        commands = [
            hook["command"]
            for entries in data["hooks"].values()
            for entry in entries
            for hook in entry.get("hooks", [])
        ]
        session_start = [command for command in commands if command.endswith("SessionStart")]
        assert session_start
        for command in session_start:
            assert shlex.split(command)[0] == f"{skill_dir}/hooks/run.sh"

    def test_codex_merge_refuses_when_no_toml_parser_is_available(self):
        merger = load_codex_merger()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG, encoding="utf-8")
            before = config.read_text(encoding="utf-8")
            with mock.patch.object(merger, "tomllib", None):
                with self.assertRaises(RuntimeError) as caught:
                    merger.merge(config, Path(SKILL_DIR))
            assert "python3.11" in str(caught.exception)
            assert config.read_text(encoding="utf-8") == before, (
                "a refused merge must leave the original config untouched"
            )

    def test_claude_leaves_unrelated_package_hooks_alone(self):
        assert CLAUDE.exists()
        once, twice = merge_twice(CLAUDE, UNRELATED_PACKAGE_SETTINGS)
        assert once == twice, "a second merge must not disturb unrelated hooks"
        text = json.dumps(json.loads(twice))
        for survivor in UNRELATED_SURVIVORS:
            assert survivor in text, (
                f"{survivor} was never merged into this package, so installing must leave its hooks alone"
            )
        assert "punctuation-discipline" not in text

    def test_claude_prunes_watcher_entries_under_arbitrary_event_keys(self):
        assert CLAUDE.exists()
        once, twice = merge_twice(CLAUDE, ARBITRARY_EVENT_SETTINGS)
        assert once == twice, "double merge must be idempotent under arbitrary event keys"
        assert_arbitrary_event_prune(json.loads(twice))


def assert_claude_merge(merged: dict) -> None:
    text = json.dumps(merged)
    assert_no_stale_hooks(text)
    assert "unrelated-stop.py" in text
    assert_watcher_hook_family(text, CLAUDE_ROUTES)
    assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])
    assert "compact" in merged["hooks"]["SessionStart"][0]["matcher"]


def _watcher_hook_entries(merged: dict) -> list[dict]:
    return [
        hook
        for lifecycle in merged["hooks"].values()
        for group in lifecycle
        if "agent-discipline-watcher" in json.dumps(group)
        for hook in group["hooks"]
    ]


def assert_no_async_flags(merged: dict) -> None:
    entries = _watcher_hook_entries(merged)
    assert entries, "watcher groups must be present before the async guard runs"
    for hook in entries:
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
    assert len(watcher_entries) == 1, "PreToolUse dispatches every tool through one unmatched entry"
    entry = watcher_entries[0]
    assert "matcher" not in entry, "PreToolUse carries no matcher because pre_tool.py dispatches internally"
    assert _route_pattern("PreToolUse").search(json.dumps(entry))


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
    assert_watcher_hook_family(text, CLAUDE_ROUTES)
    assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])


def assert_codex_merge(merged: str) -> None:
    assert_no_stale_hooks(merged)
    assert "clean-coder-discipline" not in merged
    assert "unrelated-stop.py" in merged
    assert "unrelated-inline.py" in merged
    assert "[mcp_servers.unrelated-search-skill]" in merged
    assert "/x/unrelated-search-skill/server/mcp_server.py" in merged
    assert "[mcp_servers.unrelated-context-skill]" in merged
    assert "/x/unrelated-context-skill/config.toml" in merged
    assert "\n[[hooks.UserPromptSubmit]]\n\n[[hooks.UserPromptSubmit]]" not in merged
    assert_watcher_hook_family(merged)
    assert 'matcher = "Bash"' in merged
    assert 'matcher = "apply_patch|Edit|Write"' in merged


def assert_trailing_tables_survive(merged: str) -> None:
    assert "professional-agent-helper" not in merged
    assert merged.count("[[hooks.state.trusted_projects]]") == 2
    assert '[projects."/x/project1"]' in merged
    assert "[tui.model_availability_nux]" in merged
    for server in ("alpha", "beta", "gamma"):
        assert f"[mcp_servers.{server}]" in merged
    assert "[mcp_servers.alpha.http_headers]" in merged
    assert_watcher_hook_family(merged)


if __name__ == "__main__":
    unittest.main()
