"""Every settings edit once read as a wiring removal, because an edit carries only its own fragment and not the file it lands in."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pre_write

WIRED_SETTINGS = json.dumps({
    "env": {"EXISTING": "1"},
    "enabledPlugins": {"agent-discipline-watcher@agent-discipline-watcher": True},
}, indent=2)


def _rules(response: dict) -> list[str]:
    reason = response.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    return [part.split(": ")[0].split("/")[-1] for part in reason.splitlines() if "/" in part]


class ProtectedEditScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(WIRED_SETTINGS, encoding="utf-8")
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self) -> None:
        if self._home is not None:
            os.environ["HOME"] = self._home
        self.tmp.cleanup()

    def _edit(self, old: str, new: str) -> dict:
        return pre_write.run(
            {"tool_input": {"file_path": str(self.settings), "old_string": old, "new_string": new}},
            {"ledger_path": str(self.home / "ledger.jsonl"), "baseline": "none"},
        )

    def test_an_edit_that_leaves_the_wiring_alone_is_not_a_removal(self) -> None:
        response = self._edit('"EXISTING": "1"', '"EXISTING": "1",\n    "ADW_EMBEDDING_ENABLED": "1"')

        self.assertNotIn("watcher_wiring_removal", _rules(response))

    def test_an_edit_that_strips_the_wiring_still_blocks(self) -> None:
        response = self._edit('"agent-discipline-watcher@agent-discipline-watcher": true', '"other": true')

        self.assertIn("watcher_wiring_removal", _rules(response))


if __name__ == "__main__":
    unittest.main()
