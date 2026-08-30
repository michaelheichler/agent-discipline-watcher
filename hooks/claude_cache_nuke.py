#!/usr/bin/env python3
"""Separated from the installer because a wipe this blunt deserves a dry run and a test suite."""
from __future__ import annotations

import argparse
import sys

from lib import claude_cache


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clear the Claude plugin cache for ADW.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--revision", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.revision:
        print(claude_cache.recorded_revision())
        return 0
    try:
        targets = claude_cache.removable()
        if args.dry_run:
            for target in targets:
                print(target.path)
            return 0
        for path in claude_cache.nuke():
            print(f"removed {path}")
    except claude_cache.NukeRefusal as exc:
        print(f"adw-cache-nuke: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"adw-cache-nuke: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
