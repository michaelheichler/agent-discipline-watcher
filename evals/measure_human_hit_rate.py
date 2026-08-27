#!/usr/bin/env python3
"""Scores every shipped rule against prose no model wrote, because the watcher has never had a false-positive denominator."""
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.config import DEFAULTS
from lib.scanner import scan_all
from lib.slop_harness import _rule_scopes

CORPUS_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_sentences.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_manifest.json"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "human_hit_rate.json"
SAMPLE_NAME = "sample.md"
GENRE_ORDER = ("news", "encyclopedia", "literature")
DEFAULT_GATE = "enforce"
UNMEASURABLE_REASON = "Document-scope rules need a whole document, so one sentence cannot fire them and their silence here proves nothing."


class Row(NamedTuple):
    genre: str
    text: str


def load_rows(corpus_path: Path) -> tuple[Row, ...]:
    with corpus_path.open(encoding="utf-8") as stream:
        parsed = [json.loads(line) for line in stream if line.strip()]
    if not parsed:
        raise ValueError(f"{corpus_path}: corpus contains no rows, rebuild it first")
    return tuple(Row(row["genre"], row["text"]) for row in parsed)


def _rules_hit(text: str) -> set[str]:
    return {finding["rule"] for finding in scan_all(SAMPLE_NAME, text, {})}


def count_hits(rows: tuple[Row, ...]) -> dict[str, Counter[str]]:
    hits: dict[str, Counter[str]] = {}
    for row in rows:
        for rule in _rules_hit(row.text):
            hits.setdefault(rule, Counter())[row.genre] += 1
    return hits


def _gate_state(rule: str) -> str:
    return DEFAULTS["rule_gates"].get(rule, DEFAULT_GATE)


def _rule_record(rule: str, counts: Counter[str], totals: Counter[str]) -> dict[str, object]:
    fired = sum(counts.values())
    return {
        "gate": _gate_state(rule),
        "hits": fired,
        "rate": round(fired / sum(totals.values()), 6),
        "by_genre": {
            genre: {"hits": counts[genre], "rate": round(counts[genre] / totals[genre], 6)}
            for genre in GENRE_ORDER
        },
    }


def _quiet_rules(hits: dict[str, Counter[str]], scope: str) -> list[str]:
    scopes = _rule_scopes()
    return sorted(rule for rule in scopes if rule not in hits and scopes[rule].value == scope)


def build_report(rows: tuple[Row, ...], hits: dict[str, Counter[str]]) -> dict[str, object]:
    totals = Counter(row.genre for row in rows)
    measured = {rule: _rule_record(rule, hits[rule], totals) for rule in sorted(hits)}
    return {
        "corpus": CORPUS_PATH.name,
        "corpus_sha256": json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["sha256"],
        "sentences": {genre: totals[genre] for genre in GENRE_ORDER},
        "rules": measured,
        "silent_rules": _quiet_rules(hits, "line"),
        "unmeasurable_rules": _quiet_rules(hits, "document"),
        "unmeasurable_reason": UNMEASURABLE_REASON,
    }


def _format_row(rule: str, record: dict[str, object]) -> str:
    by_genre = record["by_genre"]
    columns = " ".join(f"{by_genre[genre]['rate']:8.4f}" for genre in GENRE_ORDER)
    return f"{rule:<28} {record['gate']:<8} {record['rate']:8.4f} {columns}"


def format_table(report: dict[str, object]) -> str:
    header = f"{'rule':<28} {'gate':<8} {'overall':>8} " + " ".join(f"{genre:>8}" for genre in GENRE_ORDER)
    rules = report["rules"]
    ordered = sorted(rules, key=lambda rule: -rules[rule]["rate"])
    lines = [header] + [_format_row(rule, rules[rule]) for rule in ordered]
    lines.append(f"silent on every sentence: {', '.join(report['silent_rules']) or 'none'}")
    lines.append(f"unmeasurable at sentence scope: {', '.join(report['unmeasurable_rules']) or 'none'}")
    return "\n".join(lines)


def main() -> None:
    rows = load_rows(CORPUS_PATH)
    report = build_report(rows, count_hits(rows))
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(format_table(report))


if __name__ == "__main__":
    main()
