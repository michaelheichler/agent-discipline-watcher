"""Because a here-string, an eval, or an awk program runs code the outer command only quotes, each one is read as the script it is."""
from __future__ import annotations

import re
from typing import NamedTuple

from lib.opaque_write import _bare_interpreter_name
from lib.shell_expansion import Expansions
from lib.shell_parse import _bare, _basename, _command_word_index, line_segments
from lib.write_targets import _without_redirects

AWK_NAMES = frozenset({"awk", "gawk", "mawk", "nawk"})
AWK_VALUE_FLAGS = frozenset({"-f", "-v", "-F", "-i", "-l", "-E", "--file", "--assign", "--field-separator", "--include", "--load"})
AWK_PROGRAM_FILE_FLAGS = frozenset({"-f", "--file", "-E"})
AWK_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
AWK_RUN_RE = re.compile(r"\bsystem\s*\(|\|\s*getline|\|&")
AWK_OUTPUT_RE = re.compile(r"\b(?:print|printf)\b[^;{}\n]*?(>>?|\|)\s*(\"\d+\"|[^\s;{}]*)")
AWK_STANDARD_STREAMS = frozenset({'"/dev/stdout"', '"/dev/stderr"'})
HERESTRING = "<<<"


class Script(NamedTuple):
    """Body None when the text cannot be read, because only a literal body can be judged."""

    interpreter: str
    body: str | None
    segment: tuple[str, ...]


def herestring_scripts(command: str, expansions: Expansions) -> list[Script]:
    scripts = []
    for segment in line_segments(command):
        word, rest = _herestring(segment)
        name = _bare_interpreter_name(rest) if word is not None else None
        scripts.extend([Script(name, expansions.assigned(word), tuple(segment))] if name and word is not None else [])
    return scripts


def _herestring(segment: list[str]) -> tuple[str | None, list[str]]:
    for index, token in enumerate(segment):
        if token == HERESTRING and index + 1 < len(segment):
            return segment[index + 1], segment[:index] + segment[index + 2:]
        if token.startswith(HERESTRING) and len(token) > len(HERESTRING):
            return token[len(HERESTRING):], segment[:index] + segment[index + 1:]
    return None, segment


def eval_scripts(command: str, expansions: Expansions) -> list[Script]:
    """Joined as bash joins them, because eval re-reads its words as one command line."""
    scripts = []
    for segment in line_segments(command):
        args = _eval_args(segment)
        if args:
            parts = [expansions.assigned(token) for token in _without_redirects(args)]
            body = None if None in parts else " ".join(part for part in parts if part is not None)
            scripts.append(Script("eval", body, tuple(segment)))
    return scripts


def _eval_args(segment: list[str]) -> list[str]:
    index = _command_word_index(segment)
    index += 1 if index < len(segment) and _bare(segment[index]) == "builtin" else 0
    return segment[index + 1:] if index < len(segment) and _bare(segment[index]) == "eval" else []


def awk_writes(command: str, expansions: Expansions) -> bool:
    """Because an awk print can redirect to a file or a pipe, a program that does is judged like any other inline writer."""
    for segment in line_segments(command):
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in AWK_NAMES and _awk_args_write(segment[index + 1:], expansions):
            return True
    return False


def _awk_args_write(args: list[str], expansions: Expansions) -> bool:
    words = [_bare(token) for token in args]
    position = 0
    while position < len(words) and words[position].startswith("-") and words[position] != "--":
        if words[position] in AWK_PROGRAM_FILE_FLAGS:
            return False
        if words[position:position + 2] in (["-i", "inplace"], ["--include", "inplace"]) or words[position] in {"-iinplace", "--include=inplace"}:
            return True
        position += 2 if words[position] in AWK_VALUE_FLAGS else 1
    position += 1 if words[position:position + 1] == ["--"] else 0
    program = expansions.assigned(args[position]) if position < len(args) else ""
    return program is None or _program_writes(program)


def _program_writes(program: str) -> bool:
    strings = AWK_STRING_RE.findall(program)
    numbers = iter(range(len(strings)))
    stripped = AWK_STRING_RE.sub(lambda _match: f'"{next(numbers)}"', program)
    if AWK_RUN_RE.search(stripped):
        return True
    for match in AWK_OUTPUT_RE.finditer(stripped):
        target = match.group(2)
        named = strings[int(target[1:-1])] if target.startswith('"') else ""
        if match.group(1) == "|" or named not in AWK_STANDARD_STREAMS:
            return True
    return False
