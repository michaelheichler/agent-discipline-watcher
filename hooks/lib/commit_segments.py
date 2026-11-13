"""Because shell operators separate execution steps, preserve them while reading command words."""
from __future__ import annotations

import re
import shlex

from .commit_inputs import PLAIN_COMMIT, Input, UnreadableCommit
from .shell_operators import SEPARATORS
from .shell_text import INLINE_INPUT, Redirect, ShellToken, _Scanner, _normalize_ansi_c_quotes

RESERVED_WORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "do", "while", "until", "coproc"})
PUNCTUATION_RUN_RE = re.compile(r"[;&|()\n]+")
SHELL_OPERATOR_RE = re.compile(r"&&|\|\||\|&|[;&|()]|\n")
UNREADABLE_QUOTING = (
    "The commit gate cannot read the quoting in this command, so it cannot see what the commit records. "
    f"{PLAIN_COMMIT}"
)


class _CommitScanner(_Scanner):
    def segments(self) -> list[list[str]]:
        text = self.text()
        try:
            lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()\n")
            lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, ""
            tokens = [operator for token in lexer for operator in _operators(token)]
        except ValueError:
            if "commit" in text:
                raise UnreadableCommit(UNREADABLE_QUOTING) from None
            return []
        return _split_segments(tokens)

    def _lead_with(self, bodies: list[str]) -> None:
        for body in bodies:
            self.parts.insert(self.command_part, f"( {_CommitScanner(body).text()}\n)\n")
            self.command_part += 1

    def _replace(self, token: ShellToken) -> None:
        if token.match.lastgroup != "procsub":
            super()._replace(token)
            return
        body = self.command[token.match.end():token.end - 1]
        self.parts.insert(self.command_part, f"( {_CommitScanner(body).text()}\n) | ")
        self.command_part += 1
        self._process_file()


def segments(command: str | list[str]) -> list[list[str]]:
    if isinstance(command, list):
        return _split_segments(command)
    return _CommitScanner(_normalize_ansi_c_quotes(command.split("\0", 1)[0])).segments()


def command_words(segment: list[str]) -> list[str]:
    index = 0
    while index < len(segment) and (segment[index] in RESERVED_WORDS or segment[index] == "function"):
        index += 2 if segment[index] == "function" else 1
    return segment[index:]


def bind_input(inputs: dict[int, Input], redirect: Redirect) -> None:
    if redirect.operator in {"<", "<>"}:
        inputs[redirect.fd] = Input(path=redirect.target)
        return
    if redirect.operator == INLINE_INPUT:
        inputs[redirect.fd] = Input(text=redirect.target)
        return
    if redirect.operator == "<&" and redirect.target.isdigit() and int(redirect.target) in inputs:
        inputs[redirect.fd] = inputs[int(redirect.target)]


def is_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator and name and name.isidentifier())


def alias_definitions(args: list[str]) -> dict[str, str]:
    return {name: value for name, separator, value in (arg.partition("=") for arg in args) if separator}


def _operators(token: str) -> list[str]:
    if not PUNCTUATION_RUN_RE.fullmatch(token):
        return [token]
    return [";" if operator == "\n" else operator for operator in SHELL_OPERATOR_RE.findall(token)]


def _split_segments(tokens: list[str]) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            result.extend([current, [token]])
            current = []
            continue
        current.append(token)
    result.append(current)
    return result
