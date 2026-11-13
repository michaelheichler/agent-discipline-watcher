"""Because defining a function does not run it, keep its body until a call reaches it."""
from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from typing import NamedTuple

from .shell_text import shell_tokens

NAME_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
POSITIONAL_RE = re.compile(r'"\$\{?([@*1-9])\}?"|\$\{?([@*1-9])\}?')


class Function(NamedTuple):
    name: str
    body: str
    original: str


class _Token(NamedTuple):
    start: int
    end: int
    word: str


def extract_functions(text: str) -> tuple[str, dict[str, Function]]:
    tokens = [_Token(token.match.start(), token.end, text[token.match.start():token.end])
              for token in shell_tokens(text)
              if token.match is not None and token.match.lastgroup != "comment" and token.match.group().strip()]
    prefix = "__adw_function_"
    while prefix in text:
        prefix += "_"
    declarations: dict[str, Function] = {}
    replacements = []
    for name, start_index, opening, closing in _function_spans(tokens):
        start, end = tokens[start_index].start, tokens[closing].end
        marker = f"{prefix}{len(declarations)}"
        declarations[marker] = Function(name, text[tokens[opening].end:tokens[closing].start], text[start:end])
        replacements.append((start, end, marker))
    for start, end, marker in reversed(replacements):
        text = text[:start] + marker + text[end:]
    return text, declarations


def _function_spans(tokens: list[_Token]) -> Iterator[tuple[str, int, int, int]]:
    index = 0
    while index < len(tokens):
        header = _function_header(tokens, index)
        closing = _closing_brace(tokens, header[1]) if header is not None else None
        if closing is None:
            index += 1
            continue
        yield header[0], index, header[1], closing
        index = closing + 1


def _function_header(tokens: list[_Token], index: int) -> tuple[str, int] | None:
    cursor = index + 1 if tokens[index].word == "function" else index
    if cursor >= len(tokens) or NAME_RE.fullmatch(tokens[cursor].word) is None:
        return None
    name = tokens[cursor].word
    cursor += 1
    parentheses = [token.word for token in tokens[cursor:cursor + 2]] == ["(", ")"]
    cursor += 2 if parentheses else 0
    if cursor >= len(tokens) or tokens[cursor].word != "{":
        return None
    return (name, cursor) if parentheses or tokens[index].word == "function" else None


def _closing_brace(tokens: list[_Token], opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(tokens)):
        depth += {"{": 1, "}": -1}.get(tokens[index].word, 0)
        if depth == 0:
            return index
    return None


def with_positional(text: str, positional: list[str]) -> str:
    if not positional:
        return text
    prepared, declarations = extract_functions(text)
    markers = "|".join(re.escape(marker) for marker in sorted(declarations, key=len, reverse=True))
    parts = re.split(f"({markers})", prepared) if markers else [prepared]
    return "".join(declarations[part].original if part in declarations
                   else POSITIONAL_RE.sub(lambda match: _positional_value(match, positional), part) for part in parts)


def _positional_value(match: re.Match, positional: list[str]) -> str:
    name = match.group(1) or match.group(2)
    if name in "@*":
        return shlex.join(positional)
    index = int(name) - 1
    return shlex.quote(positional[index]) if index < len(positional) else "''"
