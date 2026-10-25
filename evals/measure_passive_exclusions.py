"""Because the passive_voice exclusion list only removes hits, the measurement lists every removed hit so a reader can check that none is a real passive."""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals" / "corpus_paragraphs.jsonl"
RESULT = ROOT / "evals" / "passive_voice_exclusions.json"
# Because the old pattern lacks only the exclusion lookahead.
EXCLUSION_RE = re.compile(r"\(\?!\(\?:[^)]*\)\\b\)")


def patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    sys.path.insert(0, str(ROOT / "hooks"))
    current = importlib.import_module("lib.slop_structure")._PASSIVE_VOICE_RE
    return re.compile(EXCLUSION_RE.sub("", current.pattern), re.IGNORECASE), current


def paragraphs() -> list[str]:
    found: list[str] = []
    with CORPUS.open(encoding="utf-8") as handle:
        for line in handle:
            found.extend(json.loads(line).get("paragraphs", []))
    return found


def removed_hits(texts: list[str]) -> tuple[int, int, list[str]]:
    old_pattern, new_pattern = patterns()
    old_total = new_total = 0
    removed: list[str] = []
    for text in texts:
        old = {match.start(): match.group(0) for match in old_pattern.finditer(text)}
        new = {match.start() for match in new_pattern.finditer(text)}
        old_total += len(old)
        new_total += len(new)
        removed.extend(phrase for start, phrase in old.items() if start not in new)
    return old_total, new_total, removed


def main() -> None:
    old_total, new_total, removed = removed_hits(paragraphs())
    counts: dict[str, int] = {}
    for phrase in removed:
        counts[phrase.lower()] = counts.get(phrase.lower(), 0) + 1
    result = {
        "corpus": CORPUS.name,
        "old_hits": old_total,
        "new_hits": new_total,
        "removed_hits": len(removed),
        "removed_phrases": dict(sorted(counts.items(), key=lambda item: -item[1])),
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "removed_phrases"}))


if __name__ == "__main__":
    main()
