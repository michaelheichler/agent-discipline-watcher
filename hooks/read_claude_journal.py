"""Bounded here, because a reviewer reading state could see other sessions."""
from __future__ import annotations

import argparse
import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import claude_presets  # noqa: E402  # pylint: disable=wrong-import-position
from lib.journal import mark_reviewed, read_for_stop  # noqa: E402  # pylint: disable=wrong-import-position
from lib.config import effective_hook_config  # noqa: E402  # pylint: disable=wrong-import-position
from lib.pattern_semantic import load_exemplars, load_manifest, rule_blocks, rule_prompt  # noqa: E402  # pylint: disable=wrong-import-position


Reader = Callable[[str], list[dict]]
Marker = Callable[[str, list[dict]], None]


def _blocking_rows(rows: list[dict]) -> list[dict]:
    """Dropped, because this reviewer can only pass or block."""
    if not any(row.get("role") == "pattern" for row in rows):
        return rows
    manifest = load_manifest()
    config_for = functools.cache(lambda path: effective_hook_config({}, path or None))

    def observed(row: dict) -> bool:
        rule = str(row.get("rule"))
        if row.get("role") != "pattern" or rule not in manifest["rules"]:
            return False
        return not rule_blocks(manifest, rule, config_for(str(row.get("path") or "")))

    return [row for row in rows if not observed(row)]


def _rule_entries(rows: list[dict], exemplar_source: Callable[[], tuple]) -> list[dict]:
    """Beside the rows, because the judge compares against both sides."""
    rules = sorted({str(row.get("rule")) for row in rows if row.get("role") == "pattern"})
    if not rules:
        return []
    exemplars, manifest = exemplar_source(), load_manifest()
    prompts = (rule_prompt(rule, exemplars, manifest) for rule in rules if rule in manifest["rules"])
    return [
        {
            "role": "rule", "rule": prompt.name, "action": prompt.action,
            "violating": list(prompt.violating_examples), "clean": list(prompt.clean_examples),
        }
        for prompt in prompts
    ]


def main(argv: list[str] | None = None, *, read: Reader = read_for_stop, mark: Marker = mark_reviewed, exemplar_source: Callable[[], tuple] = load_exemplars) -> int:
    parser = argparse.ArgumentParser(prog="read_claude_journal")
    parser.add_argument(claude_presets.DOCUMENTS_FLAG, dest="documents", action="store_true")
    parser.add_argument("session_id")
    args = parser.parse_args(argv)
    try:
        stored = read(args.session_id)
    except ValueError as exc:
        parser.error(str(exc))
    rows = [row for row in stored if args.documents or row.get("role") != "document"]
    judged = _blocking_rows(rows)
    served = judged + _rule_entries(judged, exemplar_source)
    sys.stdout.write(json.dumps(served, ensure_ascii=True, separators=(",", ":")) + "\n")
    mark(args.session_id, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
