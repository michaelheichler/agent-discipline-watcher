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
from lib.journal import read_for_stop  # noqa: E402  # pylint: disable=wrong-import-position


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
    sys.stdout.write(json.dumps(rows, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
