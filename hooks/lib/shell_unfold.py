"""Because bash expands literal braces and walks a literal for list before any command runs, the gates judge the words it will run."""
from __future__ import annotations

import re

BRACE_SKIP_RE = re.compile(r"""[$`'"\\*?\[]|^[A-Za-z_]\w*(?:\[[^\]]*\])?\+?=""", re.ASCII)
LOOP_VALUE_RE = re.compile(r"[\w./@%+,:=-]+", re.ASCII)
NAME_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
REDIRECT_TAIL_RE = re.compile(r"(?:[<>]|>[&|])$")
MAX_WORDS = 128
# Because the group search grows with the square of the word length.
MAX_BRACE_WORD = 512
LOOP_OPENERS = frozenset({";", "&&", "||", "(", "&"})
LOOP_CLOSERS = frozenset({";", "&&", "||", ")"})
COMMAND_STARTERS = LOOP_OPENERS | LOOP_CLOSERS | {"|", "|&", "{", "!"}
NESTED_WORDS = frozenset({"for", "while", "until", "select", "do", "done", "case", "esac", "function", "in"})
# Because each of these can rebind a name or run text the loop list did not show.
REBINDING_WORDS = frozenset({
    "read", "unset", "declare", "local", "export", "typeset", "readonly", "mapfile", "readarray",
    "getopts", "let", "eval", "source", "printf", "wait", "coproc", "trap",
})


def unfolded(tokens: list[str]) -> list[str]:
    """Because bash refuses a redirect whose braces build two names, a redirect word stays unexpanded and so unresolved."""
    words: list[str] = []
    for position, token in enumerate(tokens):
        redirected = "<" in token or ">" in token or (position and REDIRECT_TAIL_RE.search(tokens[position - 1]))
        words += [token] if redirected else brace_words(token)
    return _unrolled(words)


def brace_words(token: str) -> list[str]:
    """Only a fully literal word, because a quote, escape, expansion, or glob changes what bash builds from the braces."""
    if "{" not in token or len(token) > MAX_BRACE_WORD or BRACE_SKIP_RE.search(token):
        return [token]
    words = _expanded(token)
    if words is None or len(words) > MAX_WORDS or "" in words:
        return [token]
    return words


def _expanded(word: str) -> list[str] | None:
    """Because bash reads the leftmost group first, and a group without a top-level comma stays literal text."""
    group = next((found for found in map(lambda start: _group(word, start), range(len(word))) if found), None)
    if group is None:
        return [word]
    start, end, commas = group
    found: list[str] = []
    for left, right in zip([start, *commas], [*commas, end]):
        inner = _expanded(word[:start] + word[left + 1:right] + word[end + 1:])
        if inner is None or len(found) + len(inner) > MAX_WORDS:
            return None
        found += inner
    return found


def _group(word: str, start: int) -> tuple[int, int, list[int]] | None:
    if word[start] != "{":
        return None
    depth, commas = 0, []
    for index in range(start, len(word)):
        char = word[index]
        depth += {"{": 1, "}": -1}.get(char, 0)
        if char == "," and depth == 1:
            commas.append(index)
        if depth == 0:
            return (start, index, commas) if commas else None
    return None


def _unrolled(tokens: list[str]) -> list[str]:
    """Because a group keeps the body guarded and in this shell, a cd in it still moves later commands and its assignments prove nothing."""
    for start, token in enumerate(tokens):
        if token != "for" or (start and tokens[start - 1] not in LOOP_OPENERS):
            continue
        loop = _loop(tokens, start)
        if loop is None:
            continue
        name, values, body, end = loop
        unrolled = ["{"]
        for value in values:
            unrolled += [*_bound(body, name, value), ";"]
        return tokens[:start] + unrolled + [f"{name}={values[-1]}", ";", "}"] + _unrolled(tokens[end:])
    return tokens


def _loop(tokens: list[str], start: int) -> tuple[str, list[str], list[str], int] | None:
    """Because only plain literal list words and plain $name reads let bash bind each value as written."""
    try:
        name, keyword = tokens[start + 1], tokens[start + 2]
        split = tokens.index(";", start + 3)
        close = tokens.index("done", split)
    except (IndexError, ValueError):
        return None
    values = tokens[start + 3:split]
    body = tokens[split + 2:close]
    body = body[:-1] if body[-1:] == [";"] else body
    if not NAME_RE.fullmatch(name) or keyword != "in" or tokens[split + 1:split + 2] != ["do"]:
        return None
    if not values or len(values) > MAX_WORDS or not all(LOOP_VALUE_RE.fullmatch(value) for value in values):
        return None
    if close + 1 < len(tokens) and tokens[close + 1] not in LOOP_CLOSERS:
        return None
    return (name, values, body, close + 1) if body and _binds_only_plainly(body, name) else None


def _binds_only_plainly(body: list[str], name: str) -> bool:
    reference = re.compile(rf"\$(?:\{{{name}\}}|{name}(?!\w))")
    for position, token in enumerate(body):
        leads = position == 0 or body[position - 1] in COMMAND_STARTERS
        if token in NESTED_WORDS or token in REBINDING_WORDS or (leads and token == ".") or re.match(rf"{name}(?:\[[^\]]*\])?\+?=", token):
            return False
        if name not in token:
            continue
        mentions = len(re.findall(rf"\$\{{?[#!]?{name}(?!\w)", token))
        plain = len(reference.findall(token))
        if mentions != plain or (plain and re.search(r"['\\*?\[]|\$\$", token)):
            return False
    return True


def _bound(body: list[str], name: str, value: str) -> list[str]:
    reference = re.compile(rf"\$(?:\{{{name}\}}|{name}(?!\w))")
    return [reference.sub(lambda _: value, token) for token in body]
