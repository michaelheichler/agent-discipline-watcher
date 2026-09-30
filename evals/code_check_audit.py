#!/usr/bin/env python3
"""Count hits first, because a rule blocks only once measured."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
test_rules = importlib.import_module("lib.test_rules")
test_units = importlib.import_module("lib.test_units")

DEFAULT_ROOT = REPOSITORY_ROOT / "hooks"
DEFAULT_REPORT = REPOSITORY_ROOT / "evals" / "code_check_audit.json"
SKIPPED_DIRS = frozenset({"__pycache__", "node_modules", "target"})


def source_files(root: Path) -> Iterator[Path]:
    """Skip hidden trees, because worktrees would count twice."""
    for path in sorted(root.rglob("*")):
        folders = path.relative_to(root).parts[:-1]
        hidden = any(part.startswith(".") or part in SKIPPED_DIRS for part in folders)
        if not hidden and path.suffix in test_units.LANGUAGES and path.is_file():
            yield path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _hit_rows(units: list, text: str, rule_sets: tuple) -> Iterator[tuple[str, dict]]:
    for unit in units:
        for row in test_rules.unit_findings(unit, text, rule_sets):
            yield row["rule"], {"path": unit.path, "line": row["line"], "test": unit.name}


def audit(root: Path, rule_sets: Iterable | None = None) -> dict:
    """Take a registry, because tests inject a fake rule set."""
    chosen = test_rules.RULE_SETS if rule_sets is None else tuple(rule_sets)
    hits: dict[str, list[dict]] = {rule.name: [] for rule_set in chosen for rule in rule_set.rules}
    functions = files = 0
    for path in source_files(root):
        text = _read(path)
        units = test_units.extract(path.relative_to(root).as_posix(), text)
        functions += len(units)
        files += bool(units)
        for rule, row in _hit_rows(units, text, chosen):
            hits[rule].append(row)
    return {
        "test_files": files,
        "test_functions": functions,
        "total_hits": sum(len(rows) for rows in hits.values()),
        "rules": {name: {"total": len(rows), "hits": rows} for name, rows in sorted(hits.items())},
    }


def _shown(root: Path) -> str:
    """Drop the home prefix, because the report lives in git."""
    resolved = root.resolve()
    if resolved.is_relative_to(REPOSITORY_ROOT):
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    return resolved.name


def main(argv: list[str] | None = None) -> int:
    """Exit zero, because the audit reports and never gates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = {"root": _shown(args.root), **audit(args.root)}
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['test_functions']} test functions in {report['test_files']} files, "
          f"{report['total_hits']} hits, report at {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
