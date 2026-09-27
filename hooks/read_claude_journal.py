"""Bounded here, because a reviewer reading state could see other sessions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import claude_presets  # noqa: E402  # pylint: disable=wrong-import-position
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
    parser.add_argument(claude_presets.DOCUMENTS_FLAG, dest="documents", action="store_true")
    parser.add_argument("session_id")
    args = parser.parse_args(argv)
    try:
        stored = read_for_stop(args.session_id)
    except ValueError as exc:
        parser.error(str(exc))
    rows = [row for row in stored if args.documents or row.get("role") != "document"]
    served = rows + _rule_entries(rows)
    sys.stdout.write(json.dumps(served, ensure_ascii=True, separators=(",", ":")) + "\n")
    mark_reviewed(args.session_id, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
