from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import NamedTuple, cast

if __package__:
    from .scanner import ENGLISH_RULES, PUNCTUATION_RULES, scan_all
    from .slop_phrase import RULE_SCOPES as PHRASE_RULE_SCOPES
    from .slop_structure import STRUCTURE_RULES
else:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.scanner import ENGLISH_RULES, PUNCTUATION_RULES, scan_all
    from lib.slop_phrase import RULE_SCOPES as PHRASE_RULE_SCOPES
    from lib.slop_structure import STRUCTURE_RULES

class RuleScope(str, Enum):
    LINE = "line"
    DOCUMENT = "document"

class Surface(str, Enum):
    PROSE = "prose"
    COMMENT = "comment"
    COMMIT = "commit"

class CorpusRow(NamedTuple):
    label: str
    source: str
    bias: str
    text: str

class CorpusSplit(NamedTuple):
    development: tuple[CorpusRow, ...]
    held_out: tuple[CorpusRow, ...]

class Ratio(NamedTuple):
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

class Counts(NamedTuple):
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    @property
    def sample_size(self) -> int:
        return sum(self)

    @property
    def precision(self) -> Ratio:
        return Ratio(
            self.true_positive,
            self.true_positive + self.false_positive,
        )

    @property
    def recall(self) -> Ratio:
        return Ratio(
            self.true_positive,
            self.true_positive + self.false_negative,
        )

class Measurement(NamedTuple):
    rule: str
    surface: Surface
    corpus: str
    bias: str
    counts: Counts

class PartitionedMeasurement(NamedTuple):
    rule: str
    surface: Surface
    corpus: str
    bias: str
    development: Counts
    held_out: Counts

class Unmeasurable(NamedTuple):
    rule: str
    surface: Surface
    corpus: str
    bias: str
    sample_size: int
    reason: str

RuleResult = Measurement | Unmeasurable
PartitionedResult = PartitionedMeasurement | Unmeasurable

class MetricFloor(NamedTuple):
    precision: float
    recall: float

    @property
    def minimum_true_positives(self) -> int:
        return 1

class CorpusFormatError(ValueError):
    pass

_CORPUS_NAMES = {
    RuleScope.LINE: "corpus_slop_sentence.jsonl",
    RuleScope.DOCUMENT: "corpus_slop_document.jsonl",
}
_SURFACE_REASONS = {
    Surface.COMMENT: (
        "English rules do not run for code comments because scanner.py only enables "
        "the english family for prose paths."
    ),
    Surface.COMMIT: (
        "Commit bodies are currently scanned as Markdown, so no distinct commit "
        "surface measurement exists."
    ),
}
_PROSE_RULE_SCOPES = {
    "long_sentence": RuleScope.LINE,
    "oversized_list": RuleScope.DOCUMENT,
    "low_sentence_variance": RuleScope.DOCUMENT,
    "uniform_paragraph_endings": RuleScope.DOCUMENT,
    "three_item_list": RuleScope.LINE,
}

def _validated_row(parsed: object, path: Path, line_number: int) -> CorpusRow:
    if not isinstance(parsed, dict):
        raise CorpusFormatError(f"{path}:{line_number} must contain a JSON object")
    values = cast(dict[object, object], parsed)
    required = {"label", "source", "bias", "text"}
    if set(values) != required:
        raise CorpusFormatError(
            f"{path}:{line_number} must contain exactly {sorted(required)}"
        )
    if not all(isinstance(values[field], str) for field in required):
        raise CorpusFormatError(f"{path}:{line_number} fields must all be strings")
    label = cast(str, values["label"])
    if label not in ("ai", "human"):
        raise CorpusFormatError(
            f"{path}:{line_number} label must be 'ai' or 'human', got {label!r}"
        )
    return CorpusRow(
        label=label,
        source=cast(str, values["source"]),
        bias=cast(str, values["bias"]),
        text=cast(str, values["text"]),
    )

def _parse_row(line: str, path: Path, line_number: int) -> CorpusRow:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as error:
        raise CorpusFormatError(
            f"{path}:{line_number} contains invalid JSON: {error.msg}"
        ) from error
    return _validated_row(parsed, path, line_number)

def corpus_path(scope: RuleScope) -> Path:
    """Exposed because the corpora are third-party samples the punctuation gate refuses to carry, so a checkout may not hold them."""
    return Path(__file__).with_name(_CORPUS_NAMES[scope])


def load_corpus(scope: RuleScope) -> tuple[CorpusRow, ...]:
    path = corpus_path(scope)
    rows: list[CorpusRow] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        rows.append(_parse_row(line, path, line_number))
    if not rows:
        raise CorpusFormatError(f"{path} contains no corpus rows")
    return tuple(rows)

def _row_key(row: CorpusRow) -> bytes:
    payload = "\x00".join(row).encode("utf-8")
    return hashlib.sha256(payload).digest()

def split_corpus(rows: tuple[CorpusRow, ...]) -> CorpusSplit:
    development: list[CorpusRow] = []
    held_out: list[CorpusRow] = []
    for label in ("ai", "human"):
        labelled = sorted((row for row in rows if row.label == label), key=_row_key)
        midpoint = (len(labelled) + 1) // 2
        development.extend(labelled[:midpoint])
        held_out.extend(labelled[midpoint:])
    if not development or not held_out:
        raise CorpusFormatError("Both corpus partitions must contain rows")
    return CorpusSplit(tuple(development), tuple(held_out))

def _rule_scopes() -> dict[str, RuleScope]:
    scopes = {rule: RuleScope.LINE for _pattern, rule, _action in ENGLISH_RULES}
    scopes.update(_PROSE_RULE_SCOPES)
    scopes.update({rule.name: RuleScope.LINE for rule in STRUCTURE_RULES})
    scopes.update({rule: RuleScope(scope) for rule, scope in PHRASE_RULE_SCOPES.items()})
    scopes.update({rule: RuleScope.LINE for _family, _patterns, rule, _detail, _action in PUNCTUATION_RULES})
    return scopes

def _validated_rule_scope(rule: str, scope: RuleScope) -> None:
    if not rule:
        raise ValueError("rule must not be empty")
    expected_scope = _rule_scopes().get(rule)
    if expected_scope is None:
        raise ValueError(f"rule {rule!r} is not emitted by scanner.scan_all")
    if expected_scope != scope:
        raise ValueError(
            f"rule {rule!r} requires {expected_scope.value!r} scope, got {scope.value!r}"
        )

def _surface_reason(surface: Surface) -> str | None:
    return _SURFACE_REASONS.get(surface)

def _scan_source(surface: Surface, text: str) -> tuple[str, str]:
    if surface != Surface.PROSE:
        raise ValueError(f"{surface.value} has no distinct scanner input")
    return "sample.md", text

def _rule_hit(rule: str, surface: Surface, text: str) -> bool:
    path, source = _scan_source(surface, text)
    return any(finding.get("rule") == rule for finding in scan_all(path, source, {}))

def _counts(rule: str, surface: Surface, rows: tuple[CorpusRow, ...]) -> Counts:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    true_negative = 0
    for row in rows:
        expected = row.label == "ai"
        actual = _rule_hit(rule, surface, row.text)
        true_positive += int(expected and actual)
        false_positive += int(not expected and actual)
        false_negative += int(expected and not actual)
        true_negative += int(not expected and not actual)
    return Counts(true_positive, false_positive, false_negative, true_negative)

def _corpus_identity(rows: tuple[CorpusRow, ...]) -> tuple[str, str]:
    sources = {row.source for row in rows}
    biases = {row.bias for row in rows}
    if len(sources) != 1 or len(biases) != 1:
        raise CorpusFormatError("A scoring corpus must have one source and one bias note")
    return next(iter(sources)), next(iter(biases))

def _unmeasurable_results(
    rule: str,
    rows: tuple[CorpusRow, ...],
    corpus: str,
    bias: str,
    surfaces: tuple[Surface, ...],
) -> tuple[Unmeasurable, ...]:
    results: list[Unmeasurable] = []
    for surface in surfaces:
        reason = _surface_reason(surface)
        if reason is not None:
            results.append(Unmeasurable(rule, surface, corpus, bias, len(rows), reason))
    return tuple(results)

def score_rule(
    rule: str,
    scope: RuleScope,
    surfaces: tuple[Surface, ...],
) -> tuple[RuleResult, ...]:
    _validated_rule_scope(rule, scope)
    if not surfaces:
        raise ValueError("surfaces must not be empty")
    rows = load_corpus(scope)
    corpus, bias = _corpus_identity(rows)
    unmeasurable = _unmeasurable_results(rule, rows, corpus, bias, surfaces)
    reasons = {result.surface: result for result in unmeasurable}
    return tuple(
        reasons[surface]
        if surface in reasons
        else Measurement(rule, surface, corpus, bias, _counts(rule, surface, rows))
        for surface in surfaces
    )

def _partitioned_measurement(
    rule: str,
    surface: Surface,
    corpus: str,
    bias: str,
    partitions: CorpusSplit,
) -> PartitionedMeasurement:
    return PartitionedMeasurement(
        rule,
        surface,
        corpus,
        bias,
        _counts(rule, surface, partitions.development),
        _counts(rule, surface, partitions.held_out),
    )

def score_rule_partitions(
    rule: str,
    scope: RuleScope,
    surfaces: tuple[Surface, ...],
) -> tuple[PartitionedResult, ...]:
    _validated_rule_scope(rule, scope)
    if not surfaces:
        raise ValueError("surfaces must not be empty")
    rows = load_corpus(scope)
    corpus, bias = _corpus_identity(rows)
    partitions = split_corpus(rows)
    unmeasurable = _unmeasurable_results(rule, rows, corpus, bias, surfaces)
    reasons = {result.surface: result for result in unmeasurable}
    return tuple(
        reasons[surface]
        if surface in reasons
        else _partitioned_measurement(rule, surface, corpus, bias, partitions)
        for surface in surfaces
    )


def held_out_measurement(result: PartitionedMeasurement) -> Measurement:
    return Measurement(result.rule, result.surface, result.corpus, result.bias, result.held_out)

def _format_ratio(ratio: Ratio, sample_size: int) -> str:
    if ratio.value is None:
        return f"unmeasurable ({ratio.numerator}/{ratio.denominator}, n={sample_size})"
    return (
        f"{ratio.value:.4f} "
        f"({ratio.numerator}/{ratio.denominator}, n={sample_size})"
    )

def _format_unmeasurable(result: Unmeasurable) -> str:
    return " | ".join(
        (
            result.rule,
            result.surface.value,
            result.corpus,
            f"n={result.sample_size}",
            "unmeasurable",
            "unmeasurable",
            "unmeasurable",
            result.bias,
            result.reason,
        )
    )

def _format_measurement(result: Measurement) -> str:
    counts = result.counts
    return " | ".join(
        (
            result.rule,
            result.surface.value,
            result.corpus,
            f"n={counts.sample_size}",
            f"{counts.true_positive}/{counts.recall.denominator} AI (n={counts.sample_size})",
            _format_ratio(counts.precision, counts.sample_size),
            _format_ratio(counts.recall, counts.sample_size),
            result.bias,
            "",
        )
    )

def _format_partitioned_measurement(result: PartitionedMeasurement) -> str:
    development = result.development
    held_out = result.held_out
    return " | ".join(
        (
            result.rule,
            result.surface.value,
            result.corpus,
            f"development/in-sample n={development.sample_size}",
            _format_ratio(development.precision, development.sample_size),
            _format_ratio(development.recall, development.sample_size),
            f"held-out n={held_out.sample_size}",
            _format_ratio(held_out.precision, held_out.sample_size),
            _format_ratio(held_out.recall, held_out.sample_size),
            result.bias,
            "",
        )
    )


def _format_partitioned_unmeasurable(result: Unmeasurable) -> str:
    return " | ".join(
        (
            result.rule,
            result.surface.value,
            result.corpus,
            f"n={result.sample_size}",
            "unmeasurable",
            "unmeasurable",
            "unmeasurable",
            "unmeasurable",
            "unmeasurable",
            result.bias,
            result.reason,
        )
    )

def _format_result(result: RuleResult) -> str:
    if isinstance(result, Unmeasurable):
        return _format_unmeasurable(result)
    return _format_measurement(result)

def _format_partitioned_result(result: PartitionedResult) -> str:
    if isinstance(result, Unmeasurable):
        return _format_partitioned_unmeasurable(result)
    return _format_partitioned_measurement(result)

def format_table(results: tuple[RuleResult, ...]) -> str:
    if not results:
        raise ValueError("results must not be empty")
    header = (
        "rule | surface | corpus | sample | true positives | precision | recall | bias | note"
    )
    separator = " | ".join("---" for _column in range(9))
    rows = "\n".join(_format_result(result) for result in results)
    return f"{header}\n{separator}\n{rows}"

def format_partition_table(results: tuple[PartitionedResult, ...]) -> str:
    if not results:
        raise ValueError("results must not be empty")
    header = (
        "rule | surface | corpus | development sample | development precision | "
        "development recall | held-out sample | held-out precision | held-out recall | bias | note"
    )
    separator = " | ".join("---" for _column in range(11))
    rows = "\n".join(_format_partitioned_result(result) for result in results)
    return f"{header}\n{separator}\n{rows}"

def _below(value: float | None, floor: float) -> bool:
    return value is None or value < floor

def _validate_floor(surface: Surface, floor: MetricFloor) -> None:
    for metric, value in (("precision", floor.precision), ("recall", floor.recall)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{surface.value} {metric} floor must be between 0 and 1, got {value}"
            )

def _measurement_regressions(result: Measurement, floor: MetricFloor) -> tuple[str, ...]:
    regressions: list[str] = []
    if result.counts.true_positive < floor.minimum_true_positives:
        regressions.append(f"{result.rule} on {result.surface.value} has no true positives")
    if _below(result.counts.precision.value, floor.precision):
        regressions.append(
            f"{result.rule} on {result.surface.value} precision is below {floor.precision:.4f}"
        )
    if _below(result.counts.recall.value, floor.recall):
        regressions.append(
            f"{result.rule} on {result.surface.value} recall is below {floor.recall:.4f}"
        )
    return tuple(regressions)

def floor_regressions(
    results: tuple[RuleResult | PartitionedMeasurement, ...],
    floors: Mapping[Surface, MetricFloor],
) -> tuple[str, ...]:
    regressions: list[str] = []
    for result in results:
        floor = floors.get(result.surface)
        if floor is None:
            regressions.append(f"{result.rule} on {result.surface.value} has no recorded floor")
            continue
        _validate_floor(result.surface, floor)
        if isinstance(result, PartitionedMeasurement):
            message = f"{result.rule} is partitioned, pass held_out_measurement(result) to floor_regressions"
            raise TypeError(message)
        if isinstance(result, Unmeasurable):
            regressions.append(
                f"{result.rule} on {result.surface.value} is unmeasurable: {result.reason}"
            )
            continue
        regressions.extend(_measurement_regressions(result, floor))
    return tuple(regressions)

def assert_floors(
    results: tuple[RuleResult, ...],
    floors: Mapping[Surface, MetricFloor],
) -> None:
    regressions = floor_regressions(results, floors)
    if regressions:
        raise AssertionError("\n".join(regressions))

def _arguments(arguments: Sequence[str]) -> tuple[str, RuleScope, tuple[Surface, ...]]:
    parser = argparse.ArgumentParser(
        description="Score one scanner rule on its matching labelled corpus."
    )
    parser.add_argument("rule")
    parser.add_argument("scope", choices=tuple(RuleScope))
    parser.add_argument("surfaces", nargs="*", choices=tuple(Surface))
    parsed = parser.parse_args(arguments)
    surfaces = tuple(Surface(value) for value in parsed.surfaces)
    if not surfaces:
        surfaces = tuple(Surface)
    return parsed.rule, RuleScope(parsed.scope), surfaces

def main(arguments: Sequence[str]) -> int:
    rule, scope, surfaces = _arguments(arguments)
    print(format_partition_table(score_rule_partitions(rule, scope, surfaces)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
