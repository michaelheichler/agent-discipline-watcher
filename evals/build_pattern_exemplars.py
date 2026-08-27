#!/usr/bin/env python3
"""Ships the neighbours the scanner votes among, because the benchmark that produced them is too large to install."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.scanner import scan_all

BENCHMARK_PATH = REPOSITORY_ROOT / "evals" / "benchmark_patterns.jsonl"
JUDGE_STAGE_PATH = REPOSITORY_ROOT / "evals" / "judge_stage.json"
OUTPUT_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars.json"
PER_SIDE = 40
JUDGE_EXAMPLES = 4
MAX_CHARS = 220
VIOLATING = "violating"
DEVELOPMENT = "development"


def _action_in(rule: str, text: str) -> str:
    matched = [
        str(finding["action"])
        for finding in scan_all("sample.md", text, {})
        if finding["rule"] == rule and finding.get("action")
    ]
    return matched[0] if matched else ""


def rule_action(rule: str, examples: list[dict]) -> str:
    """Taken from a real finding rather than a registry, because the judge must be told the same fix the writer is told."""
    found = [action for action in (_action_in(rule, row["text"]) for row in examples) if action]
    if not found:
        raise ValueError(f"rule {rule!r} produced no finding carrying an action, so the judge would be told nothing")
    return found[0]


def load_rows() -> list[dict]:
    with BENCHMARK_PATH.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _usable(row: dict) -> bool:
    return row["split"] == DEVELOPMENT and len(row["text"]) <= MAX_CHARS


def _side(rows: list[dict], rule: str, label: str) -> list[dict]:
    return [row for row in rows if row["rule"] == rule and row["label"] == label and _usable(row)][:PER_SIDE]


def build(rows: list[dict]) -> list[dict]:
    """Draws only from the development split, because a held out row spent here stops the next measurement being honest."""
    exemplars: list[dict] = []
    for rule in sorted({row["rule"] for row in rows}):
        violating = _side(rows, rule, VIOLATING)
        clean = _side(rows, rule, "clean")
        if len(violating) < JUDGE_EXAMPLES or len(clean) < JUDGE_EXAMPLES:
            raise ValueError(f"{rule}: {len(violating)} violating and {len(clean)} clean rows cannot seed a judge prompt")
        exemplars.extend(
            {"rule": rule, "label": row["label"], "origin": row["origin"], "text": row["text"]}
            for row in violating + clean
        )
    return exemplars


def serialize(exemplars: list[dict]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row) + "\n" for row in exemplars)


def _precisions() -> dict[str, float]:
    if not JUDGE_STAGE_PATH.is_file():
        return {}
    measured = json.loads(JUDGE_STAGE_PATH.read_text(encoding="utf-8"))
    return {rule: row["after_judge"]["precision"] for rule, row in measured.items()}


def build_manifest(exemplars: list[dict], digest: str) -> dict[str, object]:
    precisions = _precisions()
    rules = sorted({row["rule"] for row in exemplars})
    return {
        "exemplars": OUTPUT_PATH.name,
        "sha256": digest,
        "per_side": PER_SIDE,
        "judge_examples": JUDGE_EXAMPLES,
        "origins": dict(sorted(Counter(row["origin"] for row in exemplars).items())),
        "rules": {
            rule: {
                "action": rule_action(rule, [row for row in exemplars if row["rule"] == rule and row["label"] == VIOLATING]),
                "judge_precision": precisions.get(rule),
            }
            for rule in rules
        },
    }


def main() -> None:
    exemplars = build(load_rows())
    serialized = serialize(exemplars)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(exemplars, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"{len(exemplars)} exemplars over {len({row['rule'] for row in exemplars})} rules")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
