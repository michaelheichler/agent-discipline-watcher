#!/usr/bin/env python3
"""Written from one source on demand because a committed copy per host would drift the moment the core changes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib import host, vendor


def build(targets: tuple[str, ...], source: Path, destination: Path) -> dict[str, int]:
    """Return a count per host because a silent build cannot show that a runtime lost half its files."""
    written: dict[str, int] = {}
    for target in targets:
        rows = vendor.vendor(target, source, destination / target)
        leaked = vendor.foreign_files(target, destination / target)
        if leaked:
            raise ValueError(f"{target} runtime carries foreign files: {sorted(map(str, leaked))}")
        written[target] = len(rows)
    return written


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write one vendored runtime tree per host.")
    parser.add_argument("--host", action="append", choices=host.SUPPORTED, dest="hosts")
    parser.add_argument("--source", default=str(vendor.REPO_ROOT))
    parser.add_argument("--destination", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    targets = tuple(args.hosts) if args.hosts else host.SUPPORTED
    try:
        counts = build(targets, Path(args.source), Path(args.destination))
    except ValueError as exc:
        print(f"build-runtime: {exc}", file=sys.stderr)
        return 2
    for name, count in counts.items():
        print(f"{name}\t{count} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
