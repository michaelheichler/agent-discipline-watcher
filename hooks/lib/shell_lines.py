"""Because shlex treats a newline as a space and never sees a quoted $(...) or a here-string, commands are read here the way bash runs them."""
from __future__ import annotations

from typing import NamedTuple

from .shell_text import ShellToken, _normalize_ansi_c_quotes, _substitutions, shell_tokens

SKIPPED = frozenset({"continuation", "comment"})
SUBSTITUTING = frozenset({"double", "backtick"})


class CommandLine(NamedTuple):
    """Bodies kept apart, because a heredoc body is data unless its command reads it as a script."""

    text: str
    bodies: tuple[str, ...]


class ShellPass(NamedTuple):
    lines: list[CommandLine]
    substitutions: list[str]


def shell_pass(command: str) -> ShellPass:
    """One lexer for every newline-aware reader, so every pre_bash view splits a command alike."""
    text = _normalize_ansi_c_quotes(command)
    found = ShellPass([], [])
    parts: list[str] = []
    for token in shell_tokens(text):
        if token.match is None:
            continue
        if token.match.lastgroup == "separator" and token.match.group() == "\n":
            _ended(found, parts, token)
            parts = []
        else:
            _taken(found, parts, token)
    if parts:
        found.lines.append(CommandLine("".join(parts), ()))
    return found


def command_lines(command: str) -> list[CommandLine]:
    return shell_pass(command).lines


def _taken(found: ShellPass, parts: list[str], token: ShellToken) -> None:
    match = token.match
    source = match.string[match.start():min(token.end, len(match.string))]
    if match.lastgroup in SUBSTITUTING:
        found.substitutions.extend(_substitutions(source))
    if match.lastgroup not in SKIPPED:
        parts.append(source)


def _ended(found: ShellPass, parts: list[str], token: ShellToken) -> None:
    """Because an unquoted delimiter lets the shell run $(...) inside the body, that body is read for substitutions."""
    for body in token.bodies:
        found.substitutions.extend(_substitutions(body.text) if body.expands else [])
    found.lines.append(CommandLine("".join(parts), tuple(body.text for body in token.bodies)))
