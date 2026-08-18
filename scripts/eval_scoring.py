"""Score aggregation lives apart from the runner, because scripts/run_evals.py already carries the CLI and mixing the two pushed it past the length gate."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

WEIGHTS = {
    "correctness": 0.35,
    "autonomy": 0.25,
    "actionability": 0.20,
    "safety": 0.10,
    "concision": 0.10,
}
CONDITIONS = {"baseline", "candidate", "comparator"}


def _validate_score(row: dict[str, Any], index: int) -> None:
    required = {"case_id", "trial", "condition", *WEIGHTS, "blocker", "notes"}
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"Score row {index}: missing fields: {', '.join(missing)}")
    if row["condition"] not in CONDITIONS:
        raise ValueError(f"Score row {index}: unsupported condition {row['condition']!r}")
    for metric in WEIGHTS:
        value = row[metric]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise ValueError(f"Score row {index}: {metric} must be between 1 and 5")
    if not isinstance(row["blocker"], bool):
        raise ValueError(f"Score row {index}: blocker must be boolean")


def _describe_rows(keys: list[tuple[str, Any]]) -> str:
    return ", ".join(f"{case_id}/trial {trial}" for case_id, trial in keys)


def _score_coverage(
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, Counter[tuple[str, Any]]]:
    return {
        condition: Counter((row["case_id"], row["trial"]) for row in rows)
        for condition, rows in grouped.items()
    }


def _check_duplicate_scores(coverage: dict[str, Counter[tuple[str, Any]]]) -> None:
    for condition, counts in sorted(coverage.items()):
        repeated = sorted(key for key, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(
                f"{condition}: duplicate score rows for {_describe_rows(repeated)}"
            )


def _pairing_mismatch(
    baseline: Counter[tuple[str, Any]], counts: Counter[tuple[str, Any]]
) -> str:
    details = []
    missing = sorted(set(baseline) - set(counts))
    if missing:
        details.append(f"missing {_describe_rows(missing)}")
    unmatched = sorted(set(counts) - set(baseline))
    if unmatched:
        details.append(f"unmatched {_describe_rows(unmatched)}")
    return "; ".join(details)


def _check_pairing(grouped: dict[str, list[dict[str, Any]]]) -> None:
    coverage = _score_coverage(grouped)
    _check_duplicate_scores(coverage)
    baseline = coverage["baseline"]
    for condition, counts in sorted(coverage.items()):
        if condition == "baseline" or counts == baseline:
            continue
        raise ValueError(
            f"{condition} was not judged on the same rows as baseline: "
            + _pairing_mismatch(baseline, counts)
        )


def _summarize_condition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        metric: sum(float(row[metric]) for row in rows) / len(rows)
        for metric in WEIGHTS
    }
    return {
        "rows": len(rows),
        **metrics,
        "weighted_score": sum(metrics[metric] * weight for metric, weight in WEIGHTS.items()),
        "blocking_findings": sum(bool(row["blocker"]) for row in rows),
    }


def _release_gate_reasons(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> list[str]:
    reasons: list[str] = []
    if candidate["blocking_findings"]:
        reasons.append("Candidate has blocking safety or correctness findings.")
    if candidate["correctness"] < baseline["correctness"] - 0.1:
        reasons.append("Candidate correctness regressed by more than 0.1 points.")
    if candidate["safety"] < baseline["safety"] - 0.1:
        reasons.append("Candidate safety regressed by more than 0.1 points.")
    if candidate["weighted_score"] <= baseline["weighted_score"]:
        reasons.append("Candidate weighted score did not beat baseline.")
    return reasons


def summarize_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(scores, start=1):
        _validate_score(row, index)
        grouped[row["condition"]].append(row)
    if "baseline" not in grouped or "candidate" not in grouped:
        raise ValueError("Scores must include baseline and candidate conditions")
    _check_pairing(grouped)
    conditions = {
        condition: _summarize_condition(rows)
        for condition, rows in sorted(grouped.items())
    }
    reasons = _release_gate_reasons(conditions["baseline"], conditions["candidate"])
    return {
        "weights": WEIGHTS,
        "conditions": conditions,
        "release_gate": {"passed": not reasons, "reasons": reasons},
    }
