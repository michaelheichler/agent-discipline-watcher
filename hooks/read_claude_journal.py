"""Print only bounded current-session document candidates for a Claude Stop reviewer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.journal import read_for_stop  # noqa: E402  # pylint: disable=wrong-import-position


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="read_claude_journal")
    parser.add_argument("session_id")
    args = parser.parse_args(argv)
    try:
        rows = read_for_stop(args.session_id)
    except ValueError as exc:
        parser.error(str(exc))
    sys.stdout.write(json.dumps(rows, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
