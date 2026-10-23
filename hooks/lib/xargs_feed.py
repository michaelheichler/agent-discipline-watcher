"""Because xargs fed by a literal producer runs its callback on words the command already holds, those calls are judged like typed ones."""
from __future__ import annotations

import re
import shlex
from typing import NamedTuple

from .shell_syntax import DYNAMIC_RE, _bare, _basename, _command_word_index, _without_redirects

FED_VERBS = frozenset({
    "rm", "unlink", "shred", "truncate", "chmod", "chown", "touch", "sponge", "mkfifo",
    "cp", "mv", "install", "rsync", "curl", "wget", "sort",
})
CALLBACK_READERS = frozenset({
    "cat", "grep", "egrep", "fgrep", "rg", "wc", "head", "tail", "ls", "file", "stat", "echo", "printf",
    "basename", "dirname", "realpath", "readlink", "sha1sum", "sha256sum", "shasum", "md5sum", "md5", "du",
    "test", "[", "diff", "cmp", "jq", "true", "false",
})
# Because rg --pre runs a program and file -C writes a magic file.
READER_HAZARDS: dict[str, tuple[str, ...] | None] = {"rg": ("--pre",), "file": ("-C", "--compile")}
PASSIVE_FLAGS = frozenset({"-r", "--no-run-if-empty", "-t", "--verbose", "-x", "--exit"})
NULL_FLAGS = frozenset({"-0", "--null"})
IGNORED_VALUE_FLAGS = frozenset({"-P", "--max-procs", "-s", "--max-chars"})
MODE_FLAGS = {
    "-n": "count", "--max-args": "count", "-L": "lines", "--max-lines": "lines",
    "-I": "replace", "--replace": "replace", "-d": "delimiter", "--delimiter": "delimiter",
}
DELIMITERS = {"\\n": "\n", "\\t": "\t"}
BLANKS = " \t"
SEPARATING = BLANKS + "\n"
QUOTING = frozenset("'\"\\")
LINE_MODES = frozenset({"replace", "lines"})
ITEM_RE = re.compile(r"""(?:[^ \t\n'"\\]|'[^'\n]*'|"[^"\n]*"|\\[\s\S])+""")
ITEM_PART_RE = re.compile(r"""'([^'\n]*)'|"([^"\n]*)"|\\([\s\S])|([^'"\\]+)""")
COUNT_RE = re.compile(r"[1-9][0-9]{0,3}")
# Because xargs sizes a long feed into calls of its own.
MAX_FEED_CHARS = 4096
MAX_CALLS = 256
Call = tuple[str, ...]


class Feed(NamedTuple):
    """Because -0, -d, -n, -L, and -I each change which words reach a call, modes stay by name."""

    modes: dict[str, str]
    callback: list[str]


def fed_calls(consumer: list[str], text: str) -> tuple[Call, ...] | None:
    """None unless every option is understood, because an unknown xargs flag may change which words arrive."""
    index = _command_word_index(consumer)
    if len(text) > MAX_FEED_CHARS or index >= len(consumer) or _basename(consumer[index]) != "xargs":
        return None
    feed = _feed(_without_redirects(consumer[index + 1:]))
    if feed is None or not feed.callback or _basename(_bare(feed.callback[0])) not in FED_VERBS | CALLBACK_READERS:
        return None
    lines = _items(feed.modes, text)
    calls = None if lines is None else _calls(feed, lines)
    return None if calls is None or len(calls) > MAX_CALLS else calls


def _feed(args: list[str]) -> Feed | None:
    feed = Feed({}, [])
    position = 0
    while position < len(args) and _bare(args[position]).startswith("-"):
        position = _read_flag(feed.modes, args, position)
        if position < 0:
            return None
    feed.callback.extend(args[position:])
    return feed


def _read_flag(modes: dict[str, str], args: list[str], position: int) -> int:
    """-1 for a flag outside the known set, because its effect on the words is unknown."""
    flag, value = _split_flag(_bare(args[position]))
    if flag in PASSIVE_FLAGS | NULL_FLAGS and value is None:
        modes.update({"null": ""} if flag in NULL_FLAGS else {})
        return position + 1
    if flag not in MODE_FLAGS and flag not in IGNORED_VALUE_FLAGS:
        return -1
    if value is None and position + 1 >= len(args):
        return -1
    if value is None:
        value, position = _bare(args[position + 1]), position + 1
    modes.update({MODE_FLAGS[flag]: value} if flag in MODE_FLAGS else {})
    return position + 1


def _split_flag(word: str) -> tuple[str, str | None]:
    if word.startswith("--"):
        name, has_value, value = word.partition("=")
        return name, value if has_value else None
    return word[:2], word[2:] or None


def _items(modes: dict[str, str], text: str) -> list[list[str]] | None:
    """Lines of words, because -L and -I count lines while the other modes only count words."""
    if "null" in modes or "delimiter" in modes:
        delimiter = "\0" if "null" in modes else DELIMITERS.get(modes["delimiter"], modes["delimiter"])
        return [[item] for item in _terminated(text, delimiter)] if len(delimiter) == 1 else None
    if LINE_MODES.intersection(modes):
        return _line_items(text, "replace" in modes)
    if ITEM_RE.sub("", text).strip(SEPARATING):
        return None
    return [[_unquoted(match.group()) for match in ITEM_RE.finditer(text)]]


def _terminated(text: str, delimiter: str) -> list[str]:
    parts = text.split(delimiter)
    return parts[:-1] if parts and not parts[-1] else parts


def _line_items(text: str, whole: bool) -> list[list[str]] | None:
    """Plain lines only, because a quote or a trailing blank makes xargs join or split lines its own way."""
    lines = [line for line in text.split("\n") if line.strip(BLANKS)]
    if any(QUOTING.intersection(line) or line.endswith(tuple(BLANKS)) for line in lines):
        return None
    return [[line.lstrip(BLANKS)] if whole else line.split() for line in lines]


def _unquoted(item: str) -> str:
    return "".join(next(part for part in parts.groups() if part is not None) for parts in ITEM_PART_RE.finditer(item))


def _calls(feed: Feed, lines: list[list[str]]) -> tuple[Call, ...] | None:
    if "replace" in feed.modes:
        return _replaced_calls(feed, [line[0] for line in lines])
    words = [word for line in lines for word in line]
    size = feed.modes.get("count") or feed.modes.get("lines")
    if size is None:
        return (_call(feed, words),)
    if not COUNT_RE.fullmatch(size):
        return None
    if "count" in feed.modes:
        groups = _chunks(words, int(size))
    else:
        groups = [[word for line in group for word in line] for group in _chunks(lines, int(size))]
    return tuple(_call(feed, group) for group in groups or [[]])


def _call(feed: Feed, words: list[str]) -> Call:
    return (*feed.callback, *map(shlex.quote, words))


def _chunks(items: list, size: int) -> list[list]:
    return [items[start:start + size] for start in range(0, len(items), size)]


def _replaced_calls(feed: Feed, items: list[str]) -> tuple[Call, ...] | None:
    """Literal arguments only, because a replacement inside an expansion lands where only the shell knows."""
    calls = [tuple(_replaced(token, feed.modes["replace"], item) for token in feed.callback) for item in items]
    return None if any(None in call for call in calls) else tuple(calls)


def _replaced(token: str, marker: str, item: str) -> str | None:
    if marker not in token:
        return token
    single_quoted = len(token) > 1 and token[0] == token[-1] == "'" and token.count("'") == 2
    plain = not DYNAMIC_RE.search(token) and not QUOTING.intersection(token)
    return shlex.quote(_bare(token).replace(marker, item)) if single_quoted or plain else None
