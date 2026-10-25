"""Because a queue, a bug list or an inventory has as many entries as it has, only three short look-alike entries read as a forced triad."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_TRIAD_WORDS = 10
MAX_WORD_SPREAD = 7
MARKER_RE = re.compile(r"^\s*(?:[-+*]|(\d+)[.)])\s+")
CHECKBOX_RE = re.compile(r"^\[[ xX]\]")
# Because an id like I-001, #12, 13r or Item 15 names a tracked thing.
ITEM_ID_RE = re.compile(r"^(?:[A-Z]{1,5}-\d+|#\d+|\d+[a-z]?\b|[A-Za-z]+\s+#?\d+[a-z]?\b)")
CODE_OR_PATH_RE = re.compile(r"`|\S/\S|\b\w+\.(?:py|ts|tsx|js|mjs|md|json|ya?ml|txt|sh|html|css)\b")
INNER_SENTENCE_RE = re.compile(r"[.!?]\s+\S")


@dataclass(slots=True)
class ListRun:
    """Because a list run ends on the first line that is neither an item, a nested line, nor a blank, it collects its items as it goes."""

    start: int = 0
    last: int = 0
    indent: int = 0
    first: str = ""
    items: list[str] = field(default_factory=list)
    continued: bool = False

    def take(self, number: int, line: str, marker: bool) -> bool:
        indent = len(line) - len(line.lstrip())
        if marker and (not self.items or indent == self.indent):
            self.start, self.first = (number, line) if not self.items else (self.start, self.first)
            self.indent, self.last = indent, number
            self.items.append(line)
            return True
        nested = bool(self.items) and bool(line.strip()) and indent > self.indent
        if nested:
            self.last, self.continued = number, True
            return True
        return not line.strip() and bool(self.items) and bool(number)


def forced_triad(run: ListRun) -> bool:
    if run.continued or len(run.items) != 3:
        return False
    markers = [MARKER_RE.match(item) for item in run.items]
    bodies = [item[marker.end():].strip() if marker else item.strip() for item, marker in zip(run.items, markers)]
    numbers = [int(marker.group(1)) for marker in markers if marker and marker.group(1)]
    if numbers and numbers != list(range(numbers[0], numbers[0] + 3)):
        return False
    words = [len(body.split()) for body in bodies]
    if max(words) > MAX_TRIAD_WORDS or max(words) - min(words) > MAX_WORD_SPREAD:
        return False
    return all(_plain_entry(body) for body in bodies) and len({body[:1].isupper() for body in bodies}) == 1


def _plain_entry(body: str) -> bool:
    if CHECKBOX_RE.match(body) or ITEM_ID_RE.match(body) or CODE_OR_PATH_RE.search(body):
        return False
    return INNER_SENTENCE_RE.search(body.rstrip(".!?")) is None
