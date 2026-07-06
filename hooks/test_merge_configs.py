import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


def assert_no_stale_hooks(text: str) -> None:
    assert "punctuation-discipline" not in text
    assert "english-for-agents" not in text
    assert "knowledge-based-search/hooks" not in text
    assert "professional-agent-helper" not in text


def assert_watcher_hook_family(text: str) -> None:
    for event in ("PreToolUse", "PostToolUse", "Stop", "SessionStart", "UserPromptSubmit"):
        assert event in text
    for event in ("PreToolUse", "PreCommit", "PostToolUse", "Stop", "SessionStart", "UserPromptSubmit"):
        assert f"run.sh {event}" in text


class MergeConfigTests(unittest.TestCase):
    def test_claude_removes_legacy_hooks_and_adds_watcher_family(self):
        assert CLAUDE.exists()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(CLAUDE_SETTINGS))
            run_merge(CLAUDE, "--settings", str(settings), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = json.loads(settings.read_text())
        assert_claude_merge(merged)

    def test_codex_removes_legacy_hooks_and_adds_watcher_family(self):
        assert CODEX.exists()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(CODEX_CONFIG)
            run_merge(CODEX, "--config", str(config), "--skill-dir", "/tmp/agent-discipline-watcher")
            merged = config.read_text()
        assert_codex_merge(merged)

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
    assert_watcher_hook_family(text)
    assert_claude_pretool_shape(merged["hooks"]["PreToolUse"])
    assert "compact" in merged["hooks"]["SessionStart"][0]["matcher"]
    assert len(merged["hooks"]["UserPromptSubmit"]) == 1


def assert_claude_pretool_shape(entries: list[dict]) -> None:
    watcher_entries = [entry for entry in entries if "agent-discipline-watcher" in json.dumps(entry)]
    assert len(watcher_entries) == 2
    by_matcher = {entry["matcher"]: entry for entry in watcher_entries}
    assert "Bash" in by_matcher
    assert "run.sh PreCommit" in json.dumps(by_matcher["Bash"])
    write_matcher = next(matcher for matcher in by_matcher if matcher != "Bash")
    assert "NotebookEdit" in write_matcher
    assert "apply_patch" in write_matcher


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


def assert_pi_merge(merged: dict) -> None:
    text = json.dumps(merged)
    assert_no_stale_hooks(text)
    assert merged["extensions"][0] == "/x/unrelated"
    assert merged["extensions"][1] == (
        "/tmp/agent-discipline-watcher/pi/extensions/agent-discipline-watcher/index.ts"
    )


if __name__ == "__main__":
    unittest.main()
