#!/usr/bin/env python3
"""Replays real session baselines through the legacy subtract and the provenance engine, because the clean cut in 0.29.0 must show what flips before release."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HOOKS = str(REPOSITORY_ROOT / "hooks")
STATE_ROOT = Path.home() / ".adw" / "state"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "provenance_replay_result.json"
HOME = str(Path.home())
JOURNAL_KEY = "claude_candidate_journal"
LEGACY_MAP_KEY = "imported_baseline"
SAMPLES_PER_DIRECTION = 25
SNIPPET_CHARS = 200
UNIT_CHARS = 300
UNITS_SHOWN = 3
DIRECTIONS = ("both_owned", "both_inherited", "inherited_to_owned", "owned_to_inherited")


@dataclass(frozen=True, slots=True)
class _HooksModule:
    """Imported on first use, because importing this script must not change sys.path."""
    name: str

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self.loaded(), attribute)

    def loaded(self) -> ModuleType:
        if HOOKS not in sys.path:
            sys.path.insert(0, HOOKS)
        return importlib.import_module("lib." + self.name)


provenance = _HooksModule("provenance")
scan_input = _HooksModule("scan_input")
scanner = _HooksModule("scanner")
config = _HooksModule("config")
baseline_module = _HooksModule("baseline")
HOOKS_MODULES = (provenance, scan_input, scanner, config, baseline_module)


class Pair(NamedTuple):
    source: str
    session: str
    path: str
    before: str
    after: str


# Kept from 7ecc72a because hooks/ no longer ships the legacy classifier.
def finding_key(finding: dict) -> tuple[str, str, str]:
    return (
        str(finding.get("family", "")),
        str(finding.get("rule", "")),
        str(finding.get("snippet", "")).strip(),
    )


def rule_key(finding: dict) -> tuple[str, str]:
    return finding_key(finding)[:2]


def _consume(findings: list[dict], budget: Counter, key_of: Callable[[dict], tuple]) -> list[dict]:
    kept = []
    for row in findings:
        key = key_of(row)
        if budget[key]:
            budget[key] -= 1
            continue
        kept.append(row)
    return kept


def subtract(findings: list[dict], baseline: list[dict]) -> list[dict]:
    exact = Counter(
        finding_key(row)
        for row in baseline
        if row.get("rule") not in config.SCANNER_ALWAYS_BLOCKING_RULES | config.FIXED_OBSERVE_RULES
    )
    survivors = _consume(findings, exact, finding_key)
    if not survivors:
        return []
    loose: Counter = Counter()
    for key, remaining in exact.items():
        loose[key[:2]] += remaining
    return _consume(survivors, loose, rule_key)


def legacy_match(findings: list[dict], baseline: list[dict]) -> dict[int, str]:
    """Exact or loose, because the loose pass is the ISS-006 hole."""
    exact = Counter(finding_key(row) for row in baseline if row.get("rule") not in config.SCANNER_ALWAYS_BLOCKING_RULES | config.FIXED_OBSERVE_RULES)
    survivors = {id(row) for row in _consume(findings, exact.copy(), finding_key)}
    return {id(row): "loose" if id(row) in survivors else "exact" for row in findings}


def scrub(value: object) -> object:
    if isinstance(value, str):
        return value.replace(HOME, "~")
    if isinstance(value, dict):
        return {scrub(key): scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def _children(value: object) -> list:
    if isinstance(value, dict):
        return [*value, *value.values()]
    return value if isinstance(value, list) else []


def _strings(value: object) -> Iterator[str]:
    """Walked with a stack, because state.json nests rows inside maps inside lists."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
            continue
        stack.extend(_children(item))


def _states() -> Iterator[tuple[str, dict]]:
    for state_file in sorted(STATE_ROOT.glob("*/state.json")):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield state_file.parent.name, data


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def path_table(states: list[tuple[str, dict]]) -> dict[str, str]:
    """Real paths too, because the index files a snapshot under sha256 of its real path."""
    found = {text for _session, data in states for text in _strings(data) if text.startswith("/") and "\n" not in text and len(text) < 1024}
    table: dict[str, str] = {}
    for path in found:
        table[_digest(path)] = path
        table.setdefault(_digest(os.path.realpath(path)), os.path.realpath(path))
    return table


def read_current(path: Path, cfg: dict) -> tuple[str | None, str]:
    """Gated like scan_input.read_scannable, because the replay reports why it skipped a file."""
    try:
        if not path.is_file():
            return None, "current_missing"
        if path.stat().st_size > scan_input._max_scan_bytes(cfg):
            return None, "over_scan_limit"
        raw = path.read_bytes()
    except OSError:
        return None, "current_missing"
    if scan_input.is_binary_content(path, raw) or b"\0" in raw[:scan_input.CONTENT_SAMPLE_BYTES]:
        return None, "binary"
    return raw.decode("utf-8", errors="replace"), ""


def config_for(path: str) -> dict:
    parent = Path(path).parent
    return config.effective_config(None, parent if parent.is_dir() else None)


def _index_marks(session_dir: Path) -> Iterator[tuple[str, str]]:
    index = session_dir / "imported" / "paths"
    if not index.is_dir():
        return
    for mark_file in sorted(index.iterdir()):
        if not mark_file.name.startswith("."):
            yield mark_file.name, mark_file.read_text(encoding="utf-8")


def _snapshot_pair(entry: tuple[str, str, str], table: dict[str, str]) -> tuple[Pair | None, str]:
    session, name, mark = entry
    if mark in ("", "new"):
        return None, "git_or_new_mark"
    path = table.get(name)
    if path is None:
        return None, "unresolved_path"
    blob = STATE_ROOT / session / "imported" / mark
    if not blob.is_file():
        return None, "blob_missing"
    after, reason = read_current(Path(path), config_for(path))
    if after is None:
        return None, reason
    before = blob.read_bytes().decode("utf-8", errors="replace")
    return (None, "identical") if before == after else (Pair("snapshot", session, path, before, after), "")


def _all_marks() -> Iterator[tuple[str, str, str]]:
    for session_dir in sorted(STATE_ROOT.iterdir()):
        yield from ((session_dir.name, name, mark) for name, mark in _index_marks(session_dir))


def snapshot_pairs(table: dict[str, str], skipped: Counter) -> list[Pair]:
    pairs = []
    for entry in _all_marks():
        pair, reason = _snapshot_pair(entry, table)
        if pair is None:
            skipped["snapshot:" + reason] += 1
            continue
        pairs.append(pair)
    return pairs


def _journal_pair(session: str, row: dict, cfg_of: Callable[[str], dict]) -> tuple[Pair | None, str]:
    before, after, path = row.get("before_context"), row.get("source_context"), row.get("path")
    if not isinstance(before, str) or not isinstance(after, str) or not isinstance(path, str):
        return None, "no_before_context"
    if row.get("source_truncated") is True:
        return None, "source_truncated"
    if len(after.encode("utf-8")) > scan_input._max_scan_bytes(cfg_of(path)) or "\0" in after[:8192]:
        return None, "over_scan_limit_or_binary"
    return (None, "identical") if before == after else (Pair("journal", session, path, before, after), "")


def _document_rows(states: list[tuple[str, dict]]) -> Iterator[tuple[str, dict]]:
    for session, data in states:
        rows = data.get(JOURNAL_KEY)
        yield from (
            (session, row) for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and row.get("role") == "document"
        )


def journal_pairs(states: list[tuple[str, dict]], skipped: Counter) -> list[Pair]:
    pairs, seen = [], set()
    for session, row in _document_rows(states):
        pair, reason = _journal_pair(session, row, config_for)
        key = pair and (pair.path, _digest(pair.before), _digest(pair.after))
        if pair is None or key in seen:
            skipped["journal:" + (reason or "duplicate")] += 1
            continue
        seen.add(key)
        pairs.append(pair)
    return pairs


def _shift(edits: list, index: int) -> int | None:
    """None under an edit, because an edited unit has no single old index."""
    shift = 0
    for edit in edits:
        if edit.new_start <= index < edit.new_end:
            return None
        if edit.new_end <= index:
            shift += (edit.old_end - edit.old_start) - (edit.new_end - edit.new_start)
    return index + shift


def _old_indices(edits: list, index: int) -> list[int]:
    old = _shift(edits, index)
    if old is not None:
        return [old]
    edit = next(edit for edit in edits if edit.new_start <= index < edit.new_end)
    return list(range(edit.old_start, min(edit.old_end, edit.old_start + UNITS_SHOWN)))


def _clip(text: str, size: int) -> str:
    return text if len(text) <= size else text[:size] + "..."


def unit_context(prov: provenance.Provenance, old_units: list, finding: dict) -> dict:
    """Changed units first, because the first units of a long span are usually the unchanged ones."""
    first, last = provenance._bounds(finding)
    evidence = prov._evidence(finding, first, last)
    changed = [index for index in evidence if index in prov.changed]
    indices = (changed or evidence)[:UNITS_SHOWN]
    edits = sorted(prov.diffs[0].edits, key=lambda edit: (edit.new_start, edit.new_end))
    old = sorted({spot for index in indices for spot in _old_indices(edits, index) if spot < len(old_units)})
    snippet = provenance._normal(str(finding.get("snippet", "")))
    return {
        "units_in_span": len(evidence),
        "changed_units_in_span": len(changed),
        "snippet_in_changed_unit": bool(snippet) and any(snippet in prov.units[index].key for index in changed),
        "changed_unit_lines": [[prov.units[index].first, prov.units[index].last] for index in changed[:UNITS_SHOWN]],
        "current_units": [_clip(prov.units[index].key, UNIT_CHARS) for index in indices],
        "baseline_units": [_clip(old_units[index].key, UNIT_CHARS) for index in old[:UNITS_SHOWN]],
    }


def engine_reason(prov: provenance.Provenance, finding: dict) -> str:
    """In step with Provenance.owns, so each flip names the branch that decided it."""
    rule = finding.get("rule")
    first, last = provenance._bounds(finding)
    if rule in provenance.OWNED_RULES:
        return "always_owned_rule"
    if rule in provenance.SIZE_RULES:
        return "span_grew" if prov.growth(first, last) > 0 else "span_did_not_grow"
    if not prov.seams.isdisjoint(provenance._seam_range(rule, first, last)):
        return "seam_in_span"
    indices = prov._evidence(finding, first, last)
    if not indices:
        return "no_unit_file_changed" if prov.changed or prov.seams else "no_unit_file_unchanged"
    if not prov.changed.isdisjoint(indices):
        return "changed_unit"
    edited = {index for edit in prov.diffs[0].edits for index in range(edit.new_start, edit.new_end)}
    return "moved_unit" if edited.intersection(indices) else "unchanged_unit"


def _halves(findings: list[dict], owned_ids: set[int], pair: Pair) -> set[int]:
    owned = [row for row in findings if id(row) in owned_ids]
    inherited = [row for row in findings if id(row) not in owned_ids]
    return {id(row) for row in baseline_module._length_relief((owned, inherited), pair.before, pair.after)[0]}


def _direction(legacy: bool, engine: bool) -> str:
    if legacy == engine:
        return "both_owned" if legacy else "both_inherited"
    return "owned_to_inherited" if legacy else "inherited_to_owned"


class Judged(NamedTuple):
    prov: provenance.Provenance
    old_units: list
    labels: dict[int, str]


def _row(pair: Pair, finding: dict, judged: Judged) -> dict:
    prov, old_units, labels = judged
    return {
        "source": pair.source,
        "path": pair.path,
        "line": finding.get("line"),
        "end_line": finding.get("end_line"),
        "rule": finding.get("rule"),
        "snippet": _clip(str(finding.get("snippet", "")), SNIPPET_CHARS),
        "legacy_match": labels.get(id(finding), "owned"),
        "engine_reason": engine_reason(prov, finding),
        **unit_context(prov, old_units, finding),
    }


def replay(pair: Pair) -> tuple[list[tuple[str, dict]], float, float]:
    cfg = config_for(pair.path)
    findings = scanner.scan_all(pair.path, pair.after, cfg)
    started = time.perf_counter()
    baseline_rows = scanner.scan_all(pair.path, pair.before, cfg)
    legacy_seconds = time.perf_counter() - started
    started = time.perf_counter()
    prov = provenance.compare(pair.path, pair.before, pair.after)
    engine = {id(row) for row in findings if prov.owns(row)}
    diff_seconds = time.perf_counter() - started
    legacy = _halves(findings, {id(row) for row in subtract(findings, baseline_rows)}, pair)
    engine = _halves(findings, engine, pair)
    judged = Judged(prov, provenance._units(pair.path, pair.before, prov.prose)[0], legacy_match(findings, baseline_rows))
    rows = []
    for finding in findings:
        direction = _direction(id(finding) in legacy, id(finding) in engine)
        flip = direction in ("inherited_to_owned", "owned_to_inherited")
        rows.append((direction, _row(pair, finding, judged) if flip else {"rule": finding.get("rule")}))
    return rows, diff_seconds, legacy_seconds


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered) + 0.5) - 1))]


def spread(rows: list[dict], size: int) -> list[dict]:
    """Round robin over rules, because twenty rows of one rule would hide the others."""
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda row: (row["path"], row["line"] or 0)):
        by_rule[row["rule"]].append(row)
    rounds = zip_longest(*(by_rule[rule] for rule in sorted(by_rule)))
    return [row for one_round in rounds for row in one_round if row is not None][:size]


def _timing(values: list[float]) -> dict:
    return {
        "p50_ms": round(percentile(values, 0.5) * 1000, 2),
        "p90_ms": round(percentile(values, 0.9) * 1000, 2),
        "max_ms": round(max(values, default=0.0) * 1000, 2),
    }


def _tally(rows: list[tuple[str, dict]], per_rule: dict[str, Counter], flips: dict[str, list[dict]]) -> None:
    for direction, row in rows:
        per_rule[row["rule"]][direction] += 1
        if "path" in row:
            flips[direction].append(row)


def collect(pairs: list[Pair]) -> dict:
    per_rule: dict[str, Counter] = defaultdict(Counter)
    flips: dict[str, list[dict]] = defaultdict(list)
    diff_times, legacy_times, sessions = [], [], set()
    for pair in pairs:
        rows, diff_seconds, legacy_seconds = replay(pair)
        diff_times.append(diff_seconds)
        legacy_times.append(legacy_seconds)
        sessions.add(pair.session)
        _tally(rows, per_rule, flips)
    return {"per_rule": per_rule, "flips": flips, "diff": diff_times, "legacy": legacy_times, "sessions": sessions}


def result(pairs: list[Pair], skipped: Counter, collected: dict) -> dict:
    per_rule = collected["per_rule"]
    totals = Counter()
    for counts in per_rule.values():
        totals.update(counts)
    return {
        "config": "effective_config per file from its parent directory, as the hooks resolve the project config",
        "sessions_with_pairs": len(collected["sessions"]),
        "pairs_scanned": dict(Counter(pair.source for pair in pairs)),
        "pairs_by_suffix": dict(Counter(Path(pair.path).suffix or "(none)" for pair in pairs).most_common()),
        "pairs_skipped": dict(sorted(skipped.items())),
        "totals": {direction: totals[direction] for direction in DIRECTIONS},
        "per_rule": {rule: {direction: counts[direction] for direction in DIRECTIONS} for rule, counts in sorted(per_rule.items())},
        "flip_engine_reasons": {
            direction: dict(Counter(row["engine_reason"] for row in collected["flips"][direction]))
            for direction in DIRECTIONS[2:]
        },
        "diff_time": _timing(collected["diff"]),
        "legacy_baseline_scan_time": _timing(collected["legacy"]),
        "samples": {direction: spread(collected["flips"][direction], SAMPLES_PER_DIRECTION) for direction in DIRECTIONS[2:]},
    }


def summary(report: dict) -> str:
    lines = [
        f"pairs scanned {report['pairs_scanned']} across {report['sessions_with_pairs']} sessions",
        f"pairs skipped {report['pairs_skipped']}",
        f"totals {report['totals']}",
        f"flip reasons {report['flip_engine_reasons']}",
        f"diff time {report['diff_time']}, legacy baseline scan {report['legacy_baseline_scan_time']}",
        "flips per rule:",
    ]
    for rule, counts in report["per_rule"].items():
        if counts["inherited_to_owned"] or counts["owned_to_inherited"]:
            lines.append(f"  {rule}: inherited_to_owned {counts['inherited_to_owned']}, owned_to_inherited {counts['owned_to_inherited']}")
    return "\n".join(lines)


def main() -> None:
    # Loaded first, because a first import inside replay would count as diff time.
    for module in HOOKS_MODULES:
        module.loaded()
    states = list(_states())
    skipped: Counter = Counter()
    pairs = snapshot_pairs(path_table(states), skipped) + journal_pairs(states, skipped)
    report = scrub(result(pairs, skipped, collect(pairs)))
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"wrote {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
