from __future__ import annotations

import re

SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&", "(", ")"})
PIPE_OPERATORS = frozenset({"|", "|&"})
REDIRECT_OPERATORS = frozenset({">", ">>", ">|", ">&", "&>", "&>>"})
JOINED_OPERATOR_RE = re.compile(r"(?:&&|\|\||\|&|&>>?|[0-9]*(?:>>?|>\||>&))$")
LEADING_REDIRECT_RE = re.compile(r"^(?:&>>?|[0-9]*(?:>>|>\||>&|>|<<?))")
REDIRECT_HEAD_RE = re.compile(r"^([0-9]*)(&>>?|>&|>>|>\||>)")


def _split_punctuation_runs(tokens: list[str]) -> list[str]:
    parts: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[;&|()>]+", token):
            parts.extend(token)
        else:
            parts.append(token)
    return parts


def _merge_adjacent_fragments(command: str, tokens: list[str]) -> list[str]:
    merged: list[str] = []
    search_from = 0
    prev_end: int | None = None
    prev_is_word = False
    for token in tokens:
        start = command.find(token, search_from)
        if start == -1:
            start = search_from
        end = start + len(token)
        adjacent = start == prev_end and bool(merged)
        escaped = adjacent and prev_is_word and (len(merged[-1]) - len(merged[-1].rstrip("\\"))) % 2
        is_word = token not in SEPARATORS | REDIRECT_OPERATORS or bool(escaped)
        joined = merged[-1] + token if adjacent else token
        if adjacent and ((is_word and prev_is_word) or (not is_word and JOINED_OPERATOR_RE.fullmatch(joined))):
            merged[-1] = joined
        else:
            merged.append(token)
        prev_end = end
        prev_is_word = is_word
        search_from = end
    return merged
