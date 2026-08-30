"""Kept free of terminal calls because a picker that only a human can drive is a picker no test can cover."""
from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

try:
    from .host_manifest import HostManifest
except ImportError:
    from host_manifest import HostManifest


class Action(Enum):
    NONE = "none"
    MOVE_UP = "move_up"
    MOVE_DOWN = "move_down"
    TOGGLE = "toggle"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    CLICK = "click"


class Event(NamedTuple):
    """Carry the row beside the action because a click names its target and a key does not."""

    action: Action
    row: int | None = None


class Row(NamedTuple):
    """Pair the manifest with its reachability because an unselectable row still has to render."""

    manifest: HostManifest
    selectable: bool


HEADER_LINES = 2
LINES_PER_ROW = 2
SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_KEYS = {
    "\x1b[A": Action.MOVE_UP,
    "\x1b[B": Action.MOVE_DOWN,
    "k": Action.MOVE_UP,
    "j": Action.MOVE_DOWN,
    " ": Action.TOGGLE,
    "\r": Action.CONFIRM,
    "\n": Action.CONFIRM,
    "q": Action.CANCEL,
    "\x03": Action.CANCEL,
    "\x1b": Action.CANCEL,
}


def rows_for(manifests: tuple[HostManifest, ...]) -> tuple[Row, ...]:
    """Render every host because a reader deciding needs to see the ones they cannot pick and why."""
    return tuple(Row(entry, bool(entry.installer)) for entry in manifests)


def decode(sequence: str) -> Event:
    """Read the mouse first because its escape prefix also opens the arrow keys."""
    mouse = SGR_MOUSE.fullmatch(sequence)
    if mouse:
        button, _column, line, kind = mouse.groups()
        if button != "0" or kind != "m":
            return Event(Action.NONE)
        return Event(Action.CLICK, row_at_line(int(line)))
    return Event(_KEYS.get(sequence, Action.NONE))


def row_at_line(line: int) -> int | None:
    """Return nothing off a gap line because a stray click must not toggle the row above it."""
    offset = line - 1 - HEADER_LINES
    if offset < 0 or offset % LINES_PER_ROW:
        return None
    return offset // LINES_PER_ROW


class Picker(NamedTuple):
    rows: tuple[Row, ...]
    cursor: int = 0
    selected: frozenset[str] = frozenset()

    def move(self, delta: int) -> Picker:
        """Stop at the ends because wrapping past the last row hides which one the cursor left."""
        if not self.rows:
            return self
        target = min(max(self.cursor + delta, 0), len(self.rows) - 1)
        return self._replace(cursor=target)

    def toggle(self, index: int | None = None) -> Picker:
        """Ignore an unselectable row because a plugin install is not something this script performs."""
        target = self.cursor if index is None else index
        if not 0 <= target < len(self.rows) or not self.rows[target].selectable:
            return self
        name = self.rows[target].manifest.name
        chosen = set(self.selected) ^ {name}
        return self._replace(cursor=target, selected=frozenset(chosen))

    def apply(self, event: Event) -> Picker:
        if event.action is Action.MOVE_UP:
            return self.move(-1)
        if event.action is Action.MOVE_DOWN:
            return self.move(1)
        if event.action is Action.TOGGLE:
            return self.toggle()
        if event.action is Action.CLICK and event.row is not None:
            return self.toggle(event.row)
        return self

    def chosen(self) -> tuple[str, ...]:
        """Answer in row order because the router installs in the order the reader saw."""
        return tuple(row.manifest.name for row in self.rows if row.manifest.name in self.selected)


def render(picker: Picker) -> str:
    """Build the whole frame as one string because a partial redraw leaves the cursor mid-row."""
    lines = ["Select the ADW runtimes to install.", ""]
    for index, row in enumerate(picker.rows):
        pointer = ">" if index == picker.cursor else " "
        if not row.selectable:
            box = "[-]"
        else:
            box = "[x]" if row.manifest.name in picker.selected else "[ ]"
        lines.append(f"{pointer} {box} {row.manifest.title}")
        detail = row.manifest.summary if row.selectable else row.manifest.installer_note
        lines.append(f"      {detail}")
    lines.append("")
    lines.append("Arrows move, space toggles, Enter installs, q cancels.")
    return "\n".join(lines)


def writes_for(picker: Picker) -> tuple[str, ...]:
    """List the paths because D4 requires the reader to see what lands before they confirm."""
    return tuple(
        f"{row.manifest.title}: {path}"
        for row in picker.rows
        if row.manifest.name in picker.selected
        for path in row.manifest.writes
    )
