#!/usr/bin/env python3
"""Drawn on the terminal but answered on stdout, because bash reads the selection and the reader reads the screen."""
from __future__ import annotations

import argparse
import sys
import termios
import tty
from typing import TextIO

from lib import host, host_manifest, picker_state
from lib.picker_state import Action, Picker


ENTER_MOUSE = "\x1b[?1000h\x1b[?1006h"
LEAVE_MOUSE = "\x1b[?1006l\x1b[?1000l"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR = "\x1b[H\x1b[2J"
MAX_SEQUENCE = 32


def read_event(stream: TextIO) -> picker_state.Event:
    """Read one escape sequence to its terminator because a partial read decodes as a bare escape."""
    first = stream.read(1)
    if not first:
        return picker_state.Event(Action.CANCEL)
    if first != "\x1b":
        return picker_state.decode(first)
    sequence = first + stream.read(1)
    if not sequence.endswith("["):
        return picker_state.decode(sequence)
    while len(sequence) < MAX_SEQUENCE:
        char = stream.read(1)
        if not char:
            break
        sequence += char
        if char.isalpha():
            break
    return picker_state.decode(sequence)


def drive(picker: Picker, stream: TextIO, screen: TextIO) -> tuple[str, ...] | None:
    """Return nothing on cancel because an empty tuple already means the reader chose no host."""
    while True:
        screen.write(CLEAR + picker_state.render(picker) + "\n")
        screen.flush()
        event = read_event(stream)
        if event.action is Action.CANCEL:
            return None
        if event.action is Action.CONFIRM:
            return picker.chosen()
        picker = picker.apply(event)


def _raw(stream: TextIO, screen: TextIO, picker: Picker) -> tuple[str, ...] | None:
    descriptor = stream.fileno()
    saved = termios.tcgetattr(descriptor)
    screen.write(ENTER_MOUSE + HIDE_CURSOR)
    screen.flush()
    try:
        tty.setraw(descriptor)
        return drive(picker, stream, screen)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)
        screen.write(LEAVE_MOUSE + SHOW_CURSOR + "\n")
        screen.flush()


def choose(root: str | None = None) -> tuple[str, ...] | None:
    """Open the terminal directly because stdout carries the answer and cannot carry the frame."""
    picker = Picker(picker_state.rows_for(host_manifest.load_all(root)))
    with open("/dev/tty", "r+", encoding="utf-8") as terminal:
        return _raw(terminal, terminal, picker)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Choose which ADW host runtimes to install.")
    parser.add_argument("--host", action="append", choices=host.SUPPORTED, dest="hosts")
    parser.add_argument("--list", action="store_true")
    return parser.parse_args(argv)


def _installable_names(root: str | None = None) -> tuple[str, ...]:
    return tuple(entry.name for entry in host_manifest.installable(root))


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.list:
        print("\n".join(_installable_names()))
        return 0
    if args.hosts:
        allowed = set(_installable_names())
        refused = [name for name in args.hosts if name not in allowed]
        if refused:
            print(f"host-picker: no installer for {', '.join(refused)}", file=sys.stderr)
            return 2
        print("\n".join(dict.fromkeys(args.hosts)))
        return 0
    try:
        chosen = choose()
    except OSError as exc:
        print(f"host-picker: no terminal for the picker: {exc}", file=sys.stderr)
        return 2
    if chosen is None:
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
