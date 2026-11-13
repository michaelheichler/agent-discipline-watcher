"""Because helper paths depend on the enclosing file, resolve only known script-directory assignments."""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import NamedTuple

from .shell_text import ShellToken, _substitution_spans, shell_tokens

SCRIPT_SOURCE = r'(?:\$0|\$\{0\}|\$BASH_SOURCE|\$\{BASH_SOURCE(?:\[0\])?\})'
QUOTED_SOURCE = rf'(?:"{SCRIPT_SOURCE}"|{SCRIPT_SOURCE})'
DIRNAME = rf'\$\(dirname[ \t]+(?:--[ \t]+)?{QUOTED_SOURCE}\)'
QUOTED_DIRNAME = rf'(?:"{DIRNAME}"|{DIRNAME})'
CHANGE_DIRECTORY = r"(?:CDPATH=(?:''|\"\")[ \t]+)?cd[ \t]+(?:--[ \t]+)?"
DIRECTORY_RE = re.compile(
    rf'(?:{DIRNAME}|\$\{{(?:BASH_SOURCE(?:\[0\])?|0)%/\*\}}|'
    rf'\$\({CHANGE_DIRECTORY}{QUOTED_DIRNAME}[ \t]*&&[ \t]*pwd(?:[ \t]+-P)?\))'
)
ASSIGNMENT_RE = re.compile(
    r'(?m)^[ \t]*(?:(?:export|readonly|local)[ \t]+)?'
    r'(?P<name>[A-Za-z_][A-Za-z_0-9]*)=(?P<value>[^\n]+?)(?:[ \t]+#[^\n]*)?[ \t]*$'
)

MIGRATION_RE = re.compile(
    r"""
    ^[ \t]*(?P<start>printf)[ \t]+-v[ \t]+(?P<name>[A-Za-z_][A-Za-z_0-9]*)
    [ \t]+'%s'[ \t]+"\$\{BASH_SOURCE\[0\]\}"[ \t]*(?:\n|;)[ \t]*
    case[ \t]+"\$(?P=name)"[ \t]+in\s*
    \*"/"\*\)[ \t]*printf[ \t]+-v[ \t]+(?P=name)
    [ \t]+'%s'[ \t]+"\$\{(?P=name)%"/"\*\}"[ \t]*;;\s*
    \*\)[ \t]*printf[ \t]+-v[ \t]+(?P=name)[ \t]+'%s'[ \t]+\.[ \t]*;;\s*
    esac(?=[ \t]*(?:\n|;|$))
    """,
    re.MULTILINE | re.VERBOSE,
)


class ScriptLocation(NamedTuple):
    path: Path
    operand: str
    executed: bool


def with_script_directory(text: str, location: ScriptLocation) -> str:
    tokens = [token for token in shell_tokens(text) if token.match is not None]
    starts = {token.match.start() for token in tokens}
    changes_directory = _changes_directory(tokens)
    replacements = _migration_assignments(text, location, starts)
    for assignment in ASSIGNMENT_RE.finditer(text):
        if assignment.start("name") not in starts:
            continue
        value = assignment.group("value")
        expression = value[1:-1] if value.startswith('"') and value.endswith('"') else value
        if not DIRECTORY_RE.fullmatch(expression):
            continue
        if not location.executed and re.search(r'\$(?:0|\{0(?:\}|%))', expression):
            continue
        if "&&" in expression and changes_directory and not os.path.isabs(location.operand):
            continue
        directory = _directory_value(expression, location)
        replacements.append((assignment.start("value"), assignment.end("value"), shlex.quote(directory)))
    protected = tuple(replacements)
    replacements.extend(item for item in _dirname_words(text, location, tokens)
                        if not any(start <= item[0] < end for start, end, _value in protected))
    for start, end, value in sorted(replacements, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def _dirname_words(text: str, location: ScriptLocation, tokens: list[ShellToken]) -> list[tuple[int, int, str]]:
    replacements = []
    directory = os.path.dirname(location.operand) or "."
    escaped = directory.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    for token in tokens:
        if token.match.lastgroup != "double":
            continue
        word = text[token.match.start():token.end]
        replacements.extend((token.match.start() + start, token.match.start() + end, escaped)
                            for start, end in _dirname_spans(word, location))
    return replacements


def _dirname_spans(word: str, location: ScriptLocation) -> list[tuple[int, int]]:
    return [(start, end) for start, end, _body in _substitution_spans(word)
            if re.fullmatch(DIRNAME, word[start:end])
            and (location.executed or not re.search(r'\$(?:0|\{0\})', word[start:end]))]


def _changes_directory(tokens: list[ShellToken]) -> bool:
    depth = 0
    for token in tokens:
        word = token.match.group().strip()
        depth = max(0, depth + {"(": 1, ")": -1}.get(word, 0))
        if depth == 0 and word in {"cd", "pushd", "popd"}:
            return True
    return False


def _migration_assignments(text: str, location: ScriptLocation, starts: set[int]) -> list[tuple[int, int, str]]:
    replacements = []
    directory = shlex.quote(os.path.dirname(location.operand) or ".")
    for match in MIGRATION_RE.finditer(text):
        if match.start("start") not in starts:
            continue
        assignment = f"{match.group('name')}={directory}"
        replacement = assignment + "\n" * match.group().count("\n")
        replacements.append((match.start(), match.end(), replacement))
    return replacements


def _directory_value(expression: str, location: ScriptLocation) -> str:
    if "&&" in expression:
        parent = location.path.parent.resolve() if re.search(r'pwd[ \t]+-P\)$', expression) else location.path.parent
        return str(parent)
    if "%/*" in expression:
        return location.operand.rsplit("/", 1)[0] if "/" in location.operand else location.operand
    return os.path.dirname(location.operand) or "."
