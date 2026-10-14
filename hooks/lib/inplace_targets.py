"""Because a scratch temp edit may run while a project edit still blocks, the gate needs the files an in-place editor rewrites."""
from __future__ import annotations

import os
import re
from typing import NamedTuple

from lib.script_payload import perl_substitution
from lib.shell_syntax import _bare, _basename, _command_word_index, interpreter_invocation
from lib.temp_scope import scratch_target

PERL_SWITCHES_RE = re.compile(r"-[pnlw]*(?:i[\w.~-]*)?")
VALUE_LETTERS = {"sed": frozenset("ef"), "perl": frozenset("IeE"), "ruby": frozenset("IeE")}
SCRIPT_LETTERS = {"sed": frozenset("e"), "perl": frozenset("eE"), "ruby": frozenset("e")}
SED_LONG_VALUES = {"--expression": "e", "--file": "f"}
SED_ADDRESS = r"(?:\d+|\$|/(?:\\.|[^/\\\n])*/)"
SED_SUBSTITUTE = r"s([^\w\s\\])(?:\\.|(?!\1)[^\\\n])*\1(?:\\.|(?!\1)[^\\\n])*\1[gpiImM\d]*"
SED_COMMAND_RE = re.compile(
    rf"\s*(?:{SED_ADDRESS}(?:\s*,\s*{SED_ADDRESS})?\s*!?\s*)?(?:{SED_SUBSTITUTE}|[dpP=])[ \t]*(?:[;\n]|$)"
)


class InplaceEdit(NamedTuple):
    verb: str
    targets: list[str]
    scripts: list[str]
    script_file: bool


def inplace_edit(segment: list[str]) -> InplaceEdit | None:
    """Because sed, perl and ruby read the first operand as the script unless -e names one, that operand is no target then."""
    index = _command_word_index(segment)
    verb = _basename(segment[index]) if index < len(segment) else ""
    if verb not in VALUE_LETTERS:
        return None
    values, operands = _values_and_operands(verb, [_bare(token) for token in segment[index + 1:]])
    scripts = [value for letter, value in values if letter in SCRIPT_LETTERS[verb]]
    operands = [operand for operand in operands if operand]
    targets = operands if scripts else operands[1:]
    if not scripts and operands:
        scripts = [operands[0]]
    return InplaceEdit(verb, targets, scripts, any(letter == "f" for letter, _ in values))


def scratch_inplace_edit(segment: list[str], command: str, cwd: str | os.PathLike[str] | None) -> bool:
    """Because the edited text never reaches the scanner, only a known script that writes nothing beyond scratch temp targets may run."""
    edit = inplace_edit(segment)
    if edit is None or not edit.targets or edit.script_file:
        return False
    if not all(scratch_target(target, command, cwd) for target in edit.targets):
        return False
    if edit.verb == "sed":
        return all(_safe_sed_script(script) for script in edit.scripts)
    if edit.verb != "perl" or len(edit.scripts) != 1 or not _plain_perl_options(segment):
        return False
    invocation = interpreter_invocation(segment)
    return invocation is not None and invocation.payload == edit.scripts[0] and perl_substitution(edit.scripts[0])


def _plain_perl_options(segment: list[str]) -> bool:
    """Because -M, -I, -x and -s load or run code beyond the -e script, only line-loop and in-place switches may appear."""
    words = [_bare(token) for token in segment[_command_word_index(segment) + 1:]]
    options = [word for position, word in enumerate(words) if word.startswith("-") and (position == 0 or words[position - 1] != "-e")]
    return all(word == "-e" or PERL_SWITCHES_RE.fullmatch(word) for word in options)


def _values_and_operands(verb: str, words: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    values: list[tuple[str, str]] = []
    operands: list[str] = []
    position = 0
    while position < len(words):
        word = words[position]
        position += 1
        if word == "--":
            return values, operands + words[position:]
        if not word.startswith("-") or word == "-":
            operands.append(word)
            continue
        letter, value = _option(verb, word)
        if letter and value is None:
            value = words[position] if position < len(words) else ""
            position += 1
        if letter:
            values.append((letter, value or ""))
    return values, operands


def _option(verb: str, word: str) -> tuple[str, str | None]:
    """Because i takes the rest of its cluster as a backup suffix, letters after it are no flags."""
    if word.startswith("--"):
        name, separator, value = word.partition("=")
        letter = SED_LONG_VALUES.get(name, "") if verb == "sed" else ""
        return letter, value if separator else None
    letters = word[1:]
    for position, letter in enumerate(letters):
        if letter == "i":
            return "", None
        if letter in VALUE_LETTERS[verb]:
            return letter, letters[position + 1:] or None
    return "", None


def _safe_sed_script(script: str) -> bool:
    """Because sed w, W and e commands write or run beyond the edited file, only substitutions and plain line commands pass."""
    position = 0
    while position < len(script):
        match = SED_COMMAND_RE.match(script, position)
        if match is None or match.end() == position:
            return False
        position = match.end()
    return bool(script.strip())
