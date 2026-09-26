"""Bounded here, because a reviewer reading state could see other sessions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import claude_native, claude_presets  # noqa: E402  # pylint: disable=wrong-import-position
from lib.journal import mark_reviewed, read_for_stop  # noqa: E402  # pylint: disable=wrong-import-position
from lib.pattern_semantic import load_exemplars, load_manifest, rule_prompt  # noqa: E402  # pylint: disable=wrong-import-position


def _rule_entries(rows: list[dict]) -> list[dict]:
    """Beside the rows, because the judge compares against both sides."""
    rules = sorted({str(row.get("rule")) for row in rows if row.get("role") == "pattern"})
    if not rules:
        return []
    exemplars, manifest = load_exemplars(), load_manifest()
    prompts = (rule_prompt(rule, exemplars, manifest) for rule in rules if rule in manifest["rules"])
    return [
        {
            "role": "rule", "rule": prompt.name, "action": prompt.action,
            "violating": list(prompt.violating_examples), "clean": list(prompt.clean_examples),
        }
        for prompt in prompts
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="read_claude_journal")
    parser.add_argument(claude_presets.SUPERSEDED_FLAG, dest="superseded", action="store_true")
    parser.add_argument("session_id", nargs="?")
    args = parser.parse_args(argv)
    if args.superseded:
        superseded = claude_presets.plugin_superseded(claude_native.settings_path())
        sys.stdout.write(("true" if superseded else "false") + "\n")
        return 0
    if not args.session_id:
        parser.error("a session id is required")
    try:
        rows = read_for_stop(args.session_id)
    except ValueError as exc:
        parser.error(str(exc))
    served = rows + _rule_entries(rows)
    sys.stdout.write(json.dumps(served, ensure_ascii=True, separators=(",", ":")) + "\n")
    mark_reviewed(args.session_id, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
