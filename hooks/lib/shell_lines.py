"""Because shlex treats a newline as a space and never sees a quoted $(...) or a here-string, commands are read here the way bash runs them."""
from __future__ import annotations

import re
from typing import NamedTuple

from .shell_text import SCAN_RE, _delimiter, _Heredoc, _heredoc_body, _normalize_ansi_c_quotes, _substitutions

SKIPPED = frozenset({"continuation", "comment"})
SUBSTITUTING = frozenset({"double", "backtick"})


class CommandLine(NamedTuple):
    """Bodies kept apart, because a heredoc body is data unless its command reads it as a script."""

    text: str
    bodies: tuple[str, ...]


class ShellPass(NamedTuple):
    lines: list[CommandLine]
    substitutions: list[str]


class _Line(NamedTuple):
    parts: tuple[str, ...]
    pending: tuple[tuple[_Heredoc, bool], ...]


def shell_pass(command: str) -> ShellPass:
    """One lexer for every newline-aware reader, so every pre_bash view splits a command alike."""
    text = _normalize_ansi_c_quotes(command)
    found = ShellPass([], [])
    line = _Line((), ())
    position = 0
    while position < len(text):
        match = SCAN_RE.match(text, position)
        if match is None:
            break
        line, position = _taken(found, line, match)
    if line.parts:
        found.lines.append(CommandLine("".join(line.parts), ()))
    return found


def command_lines(command: str) -> list[CommandLine]:
    return shell_pass(command).lines


def _taken(found: ShellPass, line: _Line, match: re.Match[str]) -> tuple[_Line, int]:
    kind = match.lastgroup
    if kind == "separator" and match.group() == "\n":
        return _ended(found, line, match)
    if kind in SUBSTITUTING:
        found.substitutions.extend(_substitutions(match.group()))
    if kind == "heredoc":
        expands = match.group("bare") is not None and "\\" not in match.group()
        line = line._replace(pending=(*line.pending, (_Heredoc(_delimiter(match), bool(match.group("strip")), False), expands)))
    if kind not in SKIPPED:
        line = line._replace(parts=(*line.parts, match.group()))
    return line, match.end()


def _ended(found: ShellPass, line: _Line, match: re.Match[str]) -> tuple[_Line, int]:
    """Because an unquoted delimiter lets the shell run $(...) inside the body, that body is read for substitutions."""
    position = match.end()
    bodies: list[str] = []
    for heredoc, expands in line.pending:
        body, position, _ = _heredoc_body(match.string, position, heredoc)
        bodies.append(body)
        found.substitutions.extend(_substitutions(body) if expands else [])
    found.lines.append(CommandLine("".join(line.parts), tuple(bodies)))
    return _Line((), ()), position
