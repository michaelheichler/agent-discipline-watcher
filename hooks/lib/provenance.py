"""Ownership by unit diff, because matching finding text let a reworded offender pass as inherited."""
from __future__ import annotations

import difflib
import re
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import PurePath
from typing import NamedTuple

try:
    from .config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from .findings import BLOCK_RULES
    from .markup import MIXED_LANGUAGE_EXTS
    from .pattern_semantic import prose_source
    from .prose_structure import (
        LIST_ITEM_RE, Paragraph, ProseLine, SentenceSpan, _markdown_prose_lines, _paragraph_groups, sentence_spans,
    )
    from .scanner import _is_prose
except ImportError:
    from config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from findings import BLOCK_RULES
    from markup import MIXED_LANGUAGE_EXTS
    from pattern_semantic import prose_source
    from prose_structure import (
        LIST_ITEM_RE, Paragraph, ProseLine, SentenceSpan, _markdown_prose_lines, _paragraph_groups, sentence_spans,
    )
    from scanner import _is_prose

# Floored because a key like } or pass recurs too often to prove a move.
MOVED_KEY_FLOOR = 12
SIZE_RULES = frozenset({"function_too_long", "oversized_list"})
ENDING_RULES = frozenset({"uniform_paragraph_endings"})
OWNED_RULES = SCANNER_ALWAYS_BLOCKING_RULES | FIXED_OBSERVE_RULES
DIFF_UNITS_PER_SECOND = 200_000
MAX_DIFF_CELLS = 50_000
# Capped because a block of bare lines would otherwise diff as one sentence.
MAX_UNBROKEN_LINES = 3
ORDERED_ITEM_RE = re.compile(r"^\s*(\d+)[.)]\s+")
TERMINAL_RE = re.compile(r"[.!?][\"')\]]*$")
Check = Callable[[], object]


def _unchecked() -> None:
    return None


class Unit(NamedTuple):
    key: str
    first: int
    last: int
    start: int = 0
    end: int | None = None
    ending: bool = False


class Edit(NamedTuple):
    old_start: int
    old_end: int
    new_start: int
    new_end: int


class _Diff(NamedTuple):
    edits: tuple[Edit, ...]
    changed: frozenset[int]
    regrouped: frozenset[int] = frozenset()


def _normal(text: str) -> str:
    return " ".join(text.split())


def _physical_keys(text: str) -> list[str]:
    return [_normal(line) for line in text.splitlines()]


def _prose_file(path: str, text: str) -> bool:
    return _is_prose(path, text) or PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS


def _code_units(text: str) -> list[Unit]:
    return [Unit(key, number, number) for number, line in enumerate(text.splitlines(), 1) if (key := _normal(line))]


def _interrupts(line: str, paragraph: Paragraph, in_list: bool) -> bool:
    """Only 1 interrupts prose, because CommonMark keeps a reflowed "12." inside its paragraph."""
    if not LIST_ITEM_RE.match(line):
        return False
    ordered = ORDERED_ITEM_RE.match(line)
    return not (paragraph and not in_list and ordered and int(ordered.group(1)) != 1)


def _paragraphs(path: str, lines: list[ProseLine]) -> list[Paragraph]:
    if PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS:
        return _paragraph_groups(path, lines)
    found: list[Paragraph] = []
    paragraph: Paragraph = []
    in_list = False
    for number, line in lines:
        if line.strip() and not _interrupts(line, paragraph, in_list):
            paragraph.append((number, line.strip()))
            continue
        in_list = bool(line.strip())
        if paragraph:
            found.append(paragraph)
            paragraph = []
    return [*found, paragraph] if paragraph else found


def _span_units(span: SentenceSpan, ending: bool, texts: dict[int, str]) -> list[Unit]:
    """Per line past the cap, because an unterminated run of bare lines is no sentence."""
    if span.last - span.first < MAX_UNBROKEN_LINES or TERMINAL_RE.search(span.text):
        return [Unit(_normal(span.text), span.first, span.last, span.start, span.end, ending)]
    middle = [Unit(_normal(texts[number]), number, number) for number in range(span.first + 1, span.last)]
    first = Unit(_normal(texts[span.first][span.start:]), span.first, span.first, span.start)
    last = Unit(_normal(texts[span.last][:span.end]), span.last, span.last, 0, span.end, ending)
    return [first, *middle, last]


def _sentence_units(path: str, text: str) -> tuple[list[Unit], dict[int, str]]:
    lines = list(_markdown_prose_lines(prose_source(path, text)))
    texts: dict[int, str] = {}
    units: list[Unit] = []
    for paragraph in _paragraphs(path, lines):
        texts.update(paragraph)
        spans = list(sentence_spans(paragraph))
        for index, span in enumerate(spans):
            units.extend(_span_units(span, index == len(spans) - 1, texts))
    return [unit for unit in units if unit.key], texts


def _prose_units(path: str, text: str) -> tuple[list[Unit], dict[int, str]]:
    """Uncovered lines stay units, because a heading or list item can still carry a finding."""
    sentences, texts = _sentence_units(path, text)
    covered = {number for unit in sentences for number in range(unit.first, unit.last + 1)}
    loose = [
        Unit(key, number, number)
        for number, line in enumerate(text.splitlines(), 1)
        if number not in covered and (key := _normal(line))
    ]
    return sorted([*sentences, *loose], key=lambda unit: (unit.first, unit.start)), texts


def _units(path: str, text: str, prose: bool) -> tuple[list[Unit], dict[int, str]]:
    return _prose_units(path, text) if prose else (_code_units(text), {})


def _prefix(old: Sequence[str], new: Sequence[str]) -> int:
    size = min(len(old), len(new))
    for index in range(size):
        if old[index] != new[index]:
            return index
    return size


def _suffix(old: Sequence[str], new: Sequence[str], low: int) -> int:
    size = min(len(old), len(new)) - low
    for offset in range(size):
        if old[-1 - offset] != new[-1 - offset]:
            return offset
    return size


def _affordable(old_count: int, new_count: int, check: Check) -> bool:
    left = check()
    return not isinstance(left, (int, float)) or old_count + new_count <= left * DIFF_UNITS_PER_SECOND


def _matching_cells(old: Sequence[str], new: Sequence[str]) -> int:
    """Equal pairs, not the rectangle, because repeated units are what make SequenceMatcher slow."""
    old_counts = Counter(old)
    return sum(old_counts[key] * count for key, count in Counter(new).items())


def _rising(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Patience sorted, because the chain must rise in old and new order at once."""
    tails: list[int] = []
    tail_at: list[int] = []
    back: list[int] = []
    for position, (old_index, _new_index) in enumerate(pairs):
        slot = bisect_left(tails, old_index)
        back.append(tail_at[slot - 1] if slot else -1)
        if slot == len(tails):
            tails.append(old_index)
            tail_at.append(position)
        else:
            tails[slot], tail_at[slot] = old_index, position
    chain = []
    position = tail_at[-1] if tail_at else -1
    while position >= 0:
        chain.append(pairs[position])
        position = back[position]
    return chain[::-1]


def _anchors(old: Sequence[str], new: Sequence[str]) -> list[tuple[int, int]]:
    """Units unique on both sides split the middle, because one SequenceMatcher over 25k code lines took 7.6 s."""
    old_counts, new_counts = Counter(old), Counter(new)
    # Floored, because a unique } anchor would displace a longer moved line.
    old_at = {key: index for index, key in enumerate(old) if old_counts[key] == 1 and len(key) >= MOVED_KEY_FLOOR}
    return _rising([(old_at[key], index) for index, key in enumerate(new) if new_counts[key] == 1 and key in old_at])


def _matched(old: Sequence[str], new: Sequence[str], origin: tuple[int, int]) -> tuple[Edit, ...]:
    old_low, new_low = origin
    if not old or not new:
        return (Edit(old_low, old_low + len(old), new_low, new_low + len(new)),) if old or new else ()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return tuple(
        Edit(old_start + old_low, old_end + old_low, new_start + new_low, new_end + new_low)
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes()
        if tag != "equal"
    )


def _wholesale(old_count: int, new_count: int, origin: tuple[int, int]) -> tuple[Edit, ...]:
    """An insert then a delete, because growth must still see the old middle leave."""
    old_low, new_low = origin
    inserted = (Edit(old_low, old_low, new_low, new_low + new_count),) if new_count else ()
    deleted = (Edit(old_low, old_low + old_count, new_low + new_count, new_low + new_count),) if old_count else ()
    return inserted + deleted


def _reclaims(spare: Counter, key: str) -> bool:
    if len(key) < MOVED_KEY_FLOOR or not spare[key]:
        return False
    spare[key] -= 1
    return True


def _unmoved(old: Sequence[str], new: Sequence[str], edits: tuple[Edit, ...]) -> frozenset[int]:
    """Counted, because a second copy of a moved unit is new text."""
    spare = Counter(old[index] for edit in edits for index in range(edit.old_start, edit.old_end))
    return frozenset(
        index
        for edit in edits
        for index in range(edit.new_start, edit.new_end)
        if not _reclaims(spare, new[index])
    )


def _inserted(edits: Sequence[Edit]) -> frozenset[int]:
    return frozenset(index for edit in edits for index in range(edit.new_start, edit.new_end))


def _gaps(old: Sequence[str], new: Sequence[str]) -> Iterator[Edit]:
    old_from = new_from = 0
    for old_to, new_to in [*_anchors(old, new), (len(old), len(new))]:
        if old_to > old_from or new_to > new_from:
            yield Edit(old_from, old_to, new_from, new_to)
        old_from, new_from = old_to + 1, new_to + 1


def _aligned(old: Sequence[str], new: Sequence[str], low: int) -> tuple[list[Edit], list[Edit]]:
    """A gap over the cell cap counts as changed, because that is the conservative answer."""
    matched: list[Edit] = []
    forced: list[Edit] = []
    for gap in _gaps(old, new):
        old_part, new_part = old[gap.old_start:gap.old_end], new[gap.new_start:gap.new_end]
        origin = (low + gap.old_start, low + gap.new_start)
        if _matching_cells(old_part, new_part) > MAX_DIFF_CELLS:
            forced.extend(_wholesale(len(old_part), len(new_part), origin))
        else:
            matched.extend(_matched(old_part, new_part, origin))
    return matched, forced


def _diff(old: Sequence[str], new: Sequence[str], check: Check) -> _Diff:
    low = _prefix(old, new)
    high = _suffix(old, new, low)
    old_mid, new_mid = old[low:len(old) - high], new[low:len(new) - high]
    if not _affordable(len(old_mid), len(new_mid), check):
        edits = _wholesale(len(old_mid), len(new_mid), (low, low))
        return _Diff(edits, _inserted(edits))
    matched, forced = _aligned(old_mid, new_mid, low)
    return _Diff((*matched, *forced), _unmoved(old, new, matched) | _inserted(forced))


def _equal_pairs(edits: Sequence[Edit], old_size: int, new_size: int) -> Iterator[tuple[int, int]]:
    new_at = old_at = 0
    for edit in [*sorted(edits), Edit(old_size, old_size, new_size, new_size)]:
        yield from zip(range(new_at, edit.new_start), range(old_at, edit.old_start))
        new_at, old_at = edit.new_end, edit.old_end


def _regrouped(edits: Sequence[Edit], old: list[Unit], new: list[Unit]) -> frozenset[int]:
    """Lines whose unedited unit gained or lost its paragraph end, because a merge or split edits no sentence."""
    return frozenset(
        new[new_index].last
        for new_index, old_index in _equal_pairs(edits, len(old), len(new))
        if new[new_index].ending != old[old_index].ending
    )


def _unit_diff(old: list[Unit], new: list[Unit], check: Check) -> _Diff:
    diff = _diff([unit.key for unit in old], [unit.key for unit in new], check)
    return diff._replace(regrouped=_regrouped(diff.edits, old, new))


def _span_growth(edit: Edit, low: int, high: int) -> int:
    """Surplus only for a straddling edit, because its old side may sit outside the span."""
    removed = edit.old_end - edit.old_start
    if edit.new_start == edit.new_end:
        return -removed if low < edit.new_start <= high else 0
    inside = min(edit.new_end, high + 1) - max(edit.new_start, low)
    if inside <= 0:
        return 0
    if inside == edit.new_end - edit.new_start:
        return inside - removed
    return max(0, inside - removed)


def _summed_growth(diff: _Diff, low: int, high: int) -> int:
    return sum(_span_growth(edit, low, high) for edit in diff.edits)


def _bounds(finding: dict) -> tuple[int, int]:
    line = int(finding.get("line") or 1)
    end_line = finding.get("end_line")
    return line, max(int(end_line), line) if end_line else line


def _seam_range(rule: object, first: int, last: int) -> range:
    """Block spans only, because deleting a sentence or a paragraph break can create a paragraph finding."""
    return range(first, last + 1) if rule in BLOCK_RULES or first != last else range(0)


def _holds(unit: Unit, line: int, column: int) -> bool:
    low = unit.start if unit.first == line else 0
    high = unit.end if unit.last == line and unit.end is not None else column + 1
    return low <= column < high


@dataclass(frozen=True)
class Provenance:
    units: tuple[Unit, ...]
    diffs: tuple[_Diff, ...]
    prose: bool
    texts: dict[int, str] = field(default_factory=dict, repr=False)
    physical: tuple[_Diff, ...] = ()

    @cached_property
    def changed(self) -> frozenset[int]:
        return frozenset.intersection(*(diff.changed for diff in self.diffs))

    @cached_property
    def changed_lines(self) -> frozenset[int]:
        return frozenset(
            number for index in self.changed for number in range(self.units[index].first, self.units[index].last + 1)
        )

    @cached_property
    def removed_seams(self) -> frozenset[int]:
        """The line a removal follows, 0 for the top, because a removal has no changed line to show."""
        return frozenset.intersection(*(self._removals(diff) for diff in self.diffs))

    @cached_property
    def seams(self) -> frozenset[int]:
        return frozenset.intersection(*self._parent_seams)

    @cached_property
    def _parent_seams(self) -> tuple[frozenset[int], ...]:
        """Either kind, because a merged or split paragraph changes no unit."""
        return tuple(self._removals(diff) | diff.regrouped for diff in self.diffs)

    @cached_property
    def _by_line(self) -> dict[int, list[int]]:
        found: dict[int, list[int]] = {}
        for index, unit in enumerate(self.units):
            for number in range(unit.first, unit.last + 1):
                found.setdefault(number, []).append(index)
        return found

    def _removals(self, diff: _Diff) -> frozenset[int]:
        return frozenset(
            self.units[edit.new_start - 1].last if edit.new_start else 0
            for edit in diff.edits
            if edit.new_start == edit.new_end and edit.old_end > edit.old_start
        )

    def _touching(self, first: int, last: int) -> list[int]:
        return sorted({index for number in range(first, last + 1) for index in self._by_line.get(number, ())})

    def _grown(self, parent: int, first: int, last: int) -> int:
        """Physical lines count too in code, because the scanner counts a blank line toward function length."""
        indices = self._touching(first, last)
        logical = _summed_growth(self.diffs[parent], indices[0], indices[-1]) if indices else 0
        return logical if self.prose else max(logical, _summed_growth(self.physical[parent], first - 1, last - 1))

    def growth(self, first: int, last: int) -> int:
        """Smallest over parents, because a merge that took a long span from one parent did not grow it."""
        return min(self._grown(parent, first, last) for parent in range(len(self.diffs)))

    def _narrowed(self, line: int, match: object) -> list[int]:
        """Every sentence on the line, because a missing or repeated match cannot pick one."""
        on_line = self._by_line.get(line, [])
        text = self.texts.get(line)
        if not isinstance(match, str) or not match or text is None or text.count(match) != 1:
            return on_line
        column = text.index(match)
        return [index for index in on_line if _holds(self.units[index], line, column)] or on_line

    def _evidence(self, finding: dict, first: int, last: int) -> list[int]:
        rule = finding.get("rule")
        if rule in ENDING_RULES:
            return [index for index in self._touching(first, last) if self.units[index].ending]
        if self.prose and first == last and rule not in BLOCK_RULES:
            return self._narrowed(first, finding.get("match"))
        return self._touching(first, last)

    def _owned_against(self, parent: int, seam_range: range, evidence: list[int]) -> bool:
        """Owned when evidence sits on no unit and the file changed, because unplaced debt must not hide new text."""
        changed, seams = self.diffs[parent].changed, self._parent_seams[parent]
        if not seams.isdisjoint(seam_range):
            return True
        if not evidence:
            return bool(changed or seams)
        return not changed.isdisjoint(evidence)

    def owns(self, finding: dict) -> bool:
        """Owned only against every parent, because a parent that explains the finding makes it inherited."""
        rule = finding.get("rule")
        if rule in OWNED_RULES:
            return True
        first, last = _bounds(finding)
        if rule in SIZE_RULES:
            return self.growth(first, last) > 0
        seam_range, evidence = _seam_range(rule, first, last), self._evidence(finding, first, last)
        return all(self._owned_against(parent, seam_range, evidence) for parent in range(len(self.diffs)))


def compare(path: str, before: str, after: str, check: Check = _unchecked) -> Provenance:
    return compare_any(path, [before], after, check)


def compare_any(path: str, befores: list[str], after: str, check: Check = _unchecked) -> Provenance:
    """No parent counts as an empty one, because text with no baseline is all the agent's."""
    prose = _prose_file(path, after)
    units, texts = _units(path, after, prose)
    check()
    diffs, physical = [], []
    for before in befores or [""]:
        old = units if before == after else _units(path, before, prose)[0]
        check()
        diffs.append(_unit_diff(old, units, check))
        if not prose:
            physical.append(_diff(_physical_keys(before), _physical_keys(after), check))
    return Provenance(tuple(units), tuple(diffs), prose, texts, tuple(physical))
