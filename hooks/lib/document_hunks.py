"""A reviewer that re-reads a whole document flags old text the agent never touched, so it gets only the changed hunks."""
from __future__ import annotations

from typing import Any

try:
    from .provenance import compare
except ImportError:
    from provenance import compare

CONTEXT_LINES = 3


def _span(new_start: int, new_end: int, count: int) -> tuple[int, int]:
    """Because a removal has no changed line, its window grows from the seam."""
    high = max(new_end, new_start) + CONTEXT_LINES
    return max(1, new_start + 1 - CONTEXT_LINES), min(count, high)


def _edits(changed: frozenset[int], seams: frozenset[int]) -> list[tuple[int, int]]:
    """Zero-based like an opcode, because a seam is an empty edit after its line."""
    runs: list[list[int]] = []
    for number in sorted(changed):
        if runs and runs[-1][1] == number - 1:
            runs[-1][1] = number
        else:
            runs.append([number - 1, number])
    return sorted([*((start, end) for start, end in runs), *((seam, seam) for seam in seams)])


def _windows(edits: list[tuple[int, int]], count: int) -> list[tuple[int, int, set[int]]]:
    """Merged because two hunks with overlapping context must show each line once."""
    found: list[tuple[int, int, set[int]]] = []
    for new_start, new_end in edits:
        low, high = _span(new_start, new_end, count)
        lines = set(range(new_start + 1, new_end + 1))
        if found and low <= found[-1][1] + 1:
            previous = found.pop()
            low, high, lines = previous[0], max(previous[1], high), previous[2] | lines
        found.append((low, high, lines))
    return found


def changed_hunks(path: str, before: str, after: str) -> list[dict[str, Any]]:
    """Plain dicts, because the Stop row crosses the journal boundary as JSON-shaped data."""
    lines = after.splitlines()
    if not lines:
        return []
    provenance = compare(path, before, after)
    edits = _edits(provenance.changed_lines, provenance.removed_seams)
    return [
        {"start": low, "lines": lines[low - 1:high], "changed": sorted(changed)}
        for low, high, changed in _windows(edits, len(lines))
    ]


def hunk_chars(hunks: list[dict[str, Any]]) -> int:
    return sum(len(line) for hunk in hunks for line in hunk["lines"])


def _runs(numbers: list[int]) -> list[str]:
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return [str(first) if first == last else f"{first}-{last}" for first, last in runs]


def hunk_header(path: str, hunk: dict[str, Any]) -> str:
    """Because the order and bridge questions need a place, the header names the line range."""
    end = hunk["start"] + len(hunk["lines"]) - 1
    changed = ", ".join(_runs(hunk["changed"])) or "none (text was removed between these lines)"
    return f"{path} lines {hunk['start']}-{end}, changed lines: {changed}"


def hunk_text(path: str, hunk: dict[str, Any]) -> str:
    marked = set(hunk["changed"])
    body = (
        f"{'+' if number in marked else ' '} {line}"
        for number, line in enumerate(hunk["lines"], hunk["start"])
    )
    return "\n".join([hunk_header(path, hunk), *body])
