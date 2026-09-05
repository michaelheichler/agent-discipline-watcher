import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MERGER = ROOT / "hooks" / "merge-codex-hooks.py"
CONFIG_MERGER = ROOT / "hooks" / "merge-codex-config.py"
SKILL_DIR = "/opt/adw-checkout"


def run_merge(settings: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(MERGER),
            "--hooks-json",
            str(settings),
            "--skill-dir",
            SKILL_DIR,
        ],
        check=True,
    )


class CodexHooksMergeTests(unittest.TestCase):
    def test_preserves_unrelated_hooks_and_replaces_watcher_entries(self) -> None:
        settings = {
            "description": "Keep this metadata",
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "gitnexus"}]},
                    {
                        "matcher": "Bash",
                        "hooks": [{
                            "type": "command",
                            "command": "ADW_CODEX_HOOK=1 \"/stale/agent-discipline-watcher/hooks/run.sh\" PreToolUse",
                        }],
                    },
                ],
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "keep-this-hook"}]},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp) / "hooks.json"
            hooks.write_text(json.dumps(settings), encoding="utf-8")
            run_merge(hooks)
            once = hooks.read_text(encoding="utf-8")
            run_merge(hooks)
            twice = hooks.read_text(encoding="utf-8")
            merged = json.loads(twice)

        self.assertEqual(once, twice)
        self.assertEqual(merged["description"], "Keep this metadata")
        self.assertIn("keep-this-hook", twice)
        self.assertIn("gitnexus", twice)
        self.assertNotIn("/stale/agent-discipline-watcher", twice)
        for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"):
            watcher_groups = [
                group for group in merged["hooks"][event]
                if "ADW_CODEX_HOOK=1" in json.dumps(group)
            ]
            self.assertTrue(watcher_groups, f"{event} watcher route missing")

    def test_strip_only_removes_inline_watcher_hooks(self) -> None:
        config_text = (
            'model = "gpt-5.6-luna"\n\n'
            '# >>> agent-discipline-watcher >>>\n'
            '[[hooks.Stop]]\n'
            '[[hooks.Stop.hooks]]\n'
            'type = "command"\n'
            'command = "ADW_CODEX_HOOK=1 \\\"/opt/adw-checkout/hooks/run.sh\\\" Stop"\n'
            '# <<< agent-discipline-watcher <<<\n\n'
            '[mcp_servers.keep]\n'
            'command = "keep"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(config_text, encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(CONFIG_MERGER),
                    "--config",
                    str(config),
                    "--skill-dir",
                    SKILL_DIR,
                    "--strip-only",
                ],
                check=True,
            )
            merged = config.read_text(encoding="utf-8")

        self.assertNotIn("ADW_CODEX_HOOK=1", merged)
        self.assertNotIn("agent-discipline-watcher >>>", merged)
        self.assertIn('model = "gpt-5.6-luna"', merged)
        self.assertIn('[mcp_servers.keep]', merged)
