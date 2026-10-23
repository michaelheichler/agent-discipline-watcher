"""Shared, because every Bash gate must read one token view."""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from itertools import takewhile
from typing import NamedTuple

from .find_matches import find_calls
from .folder_trees import folder_trees
from .shell_expansion import Expansions, expansions_for
from .shell_lines import command_lines
from .shell_operators import REDIRECT_HEAD_RE
from .xargs_feed import fed_calls
from .shell_syntax import (
    CLOBBER_HEAD_RE, DYNAMIC_RE, ENV_SPLIT_STRING_FLAGS,
    INTERPRETER_CODE_FLAGS, INTERPRETERS, LEADING_REDIRECT_RE,
    PIPE_OPERATORS, PROCESS_SUBSTITUTION_RE, QUOTED_SPAN_RE,
    SEPARATORS, SHELL_C_INTERPRETERS, VERSIONED_PYTHON_RE,
    WRAPPER_COMMANDS, WRAPPER_VALUE_FLAGS, InterpreterInvocation,
    _bare, _basename, _command_word_index, _copy_env_flag,
    _env_split_string_at, _expand_command_position_token,
    _expand_env_flags, _expand_env_split_strings, _flag_payload_token,
    _fused_split_string_payload, _interpreter_code_flags,
    _is_literal_token, _is_quoted, _is_unquoted_assignment,
    _leading_assignments, _merge_adjacent_fragments, _merge_clobber_operator,
    QUOTED_FRAGMENT_RE, _payload_command_index, _pipeline_groups, _segment_text, _segments,
    _skip_leading_redirect, _skip_prefixes, _skip_wrapper_options,
    _tokens, _words, _wrapper_consumes_value,
    has_process_substitution, interpreter_invocation,
)

__all__ = [
    "CLOBBER_HEAD_RE", "DYNAMIC_RE", "ENV_SPLIT_STRING_FLAGS",
    "INTERPRETER_CODE_FLAGS", "INTERPRETERS", "LEADING_REDIRECT_RE",
    "PIPE_OPERATORS", "PROCESS_SUBSTITUTION_RE", "QUOTED_SPAN_RE",
    "SEPARATORS", "SHELL_C_INTERPRETERS", "VERSIONED_PYTHON_RE",
    "WRAPPER_COMMANDS", "WRAPPER_VALUE_FLAGS", "InterpreterInvocation",
    "_bare", "_basename", "_command_word_index", "_copy_env_flag",
    "_env_split_string_at", "_expand_command_position_token",
    "_expand_env_flags", "_expand_env_split_strings", "_flag_payload_token",
    "_fused_split_string_payload", "_interpreter_code_flags",
    "_is_literal_token", "_is_quoted", "_is_unquoted_assignment",
    "_leading_assignments", "_merge_adjacent_fragments", "_merge_clobber_operator",
    "_payload_command_index", "_pipeline_groups", "_segment_text", "_segments",
    "_skip_leading_redirect", "_skip_prefixes", "_skip_wrapper_options",
    "_tokens", "_words", "_wrapper_consumes_value",
    "has_process_substitution", "interpreter_invocation",
    "HeredocEvent", "LiteralWrite", "executable_text", "heredoc_events", "literal_writes",
    "command_expansions", "expansion_memo", "line_segments", "write_paths", "write_targets",
]

STDERR_DESCRIPTOR = "2"
STDOUT_DESCRIPTOR = "1"
DESCRIPTOR_WORD_RE = re.compile(r"[0-9]*-?")
XARGS = "xargs"
FIND = "find"
FIND_WRITES = frozenset({"-delete", "-exec", "-execdir"})
PLACEHOLDER = "{}"
DIRECTORY_VERBS = frozenset({"cd", "pushd", "popd"})
TREE_VERB_RE = re.compile(r"\b(?:rm|mv|rsync)\b")
EXPANSION_MEMO: ContextVar[dict[tuple[str, str | None], Expansions] | None] = ContextVar("expansion_memo", default=None)
HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s()<>|&;'\"]+))")
LITERAL_PRODUCERS = frozenset({"echo", "printf"})
HOME_TOKEN_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
OPERAND_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TEE_APPEND_FLAGS = frozenset({"-a", "--append"})
HEREDOC_SINKS = frozenset({"cat", "tee"})
MAX_LITERAL_OUTPUT_CHARS = 1_000_000
PRINTF_TOKEN_RE = re.compile(r"%%|%s|\\[\\abefnrtv]|\\[0-7]{1,3}|[^%\\]+")
PRINTF_ESCAPES = {
    "\\": "\\", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t", "v": "\v",
}


class LiteralWrite(NamedTuple):
    path: str
    text: str
    append: bool


class HeredocEvent(NamedTuple):
    consumer_segment: list[str]
    body: str
    dynamic: bool
    group_has_write_target: bool


def write_paths(command: str) -> list[str]:
    """Because an undecidable write body is not the same as no write at all, keep the target even when its content is unreadable here."""
    expansions = command_expansions(command)
    words = [word for segment in line_segments(command) for word, _ in _write_path_words(segment)]
    return [path for path in map(expansions.path, words) if path is not None]


def write_targets(command: str) -> list[tuple[str, str]]:
    return [(write.path, write.text) for write in literal_writes(command)]


def literal_writes(command: str) -> list[LiteralWrite]:
    """Drop a write whose text is not knowable here, because a guessed body would misreport what the command actually sends."""
    expansions = command_expansions(command)
    rows = [write for line, bodies, _ in _logical_lines(command) for write in _line_writes(line, bodies)]
    return [write._replace(path=path) for write in rows if (path := expansions.path(write.path)) is not None]


@contextmanager
def expansion_memo() -> Iterator[None]:
    """Because one gate decision reads the same command many times, it builds each view once and drops it after."""
    token = EXPANSION_MEMO.set({})
    try:
        yield
    finally:
        EXPANSION_MEMO.reset(token)


def command_expansions(command: str, cwd: str | os.PathLike[str] | None = None) -> Expansions:
    memo = EXPANSION_MEMO.get()
    key = (command, None if cwd is None else os.fspath(cwd))
    if memo is not None and key in memo:
        return memo[key]
    built = _expansions(command, cwd)
    if memo is not None:
        memo[key] = built
    return built


def _expansions(command: str, cwd: str | os.PathLike[str] | None) -> Expansions:
    expansions = expansions_for(command, cwd)
    feeds = _xargs_feeds(command) if XARGS in command else ()
    feeds += _find_feeds(command, expansions, os.fspath(cwd)) if FIND in command and cwd is not None else ()
    expansions = expansions._replace(feeds=feeds) if feeds else expansions
    if cwd is None or not TREE_VERB_RE.search(command):
        return expansions
    return expansions._replace(trees=folder_trees(line_segments(command), expansions, os.fspath(cwd)))


def _find_feeds(command: str, expansions: Expansions, cwd: str) -> tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...]:
    """Only before any cd, because the walk starts where the command does."""
    segments = list(takewhile(lambda segment: _verb(segment) not in DIRECTORY_VERBS, line_segments(command)))
    writing = [segment for segment in segments if _verb(segment) == FIND and FIND_WRITES.intersection(map(_bare, segment))]
    found = [(tuple(segment), find_calls(segment, partial(_find_word, expansions), cwd)) for segment in writing]
    return tuple((key, calls) for key, calls in found if calls is not None)


def _find_word(expansions: Expansions, word: str) -> str | None:
    """{} kept, because bash leaves a brace pair without a comma alone and find fills it."""
    return PLACEHOLDER if word == PLACEHOLDER else expansions.path(word)


def _verb(segment: list[str]) -> str:
    index = _command_word_index(segment)
    return _basename(segment[index]) if index < len(segment) else ""


def _xargs_feeds(command: str) -> tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...]:
    """Adjacent pairs only, because xargs reads the stdin of the segment right before it."""
    pairs = [
        (producer, consumer) for line in command_lines(command)
        for group in _pipeline_groups(line.text) for producer, consumer in zip(group, group[1:])
    ]
    fed = [(tuple(consumer), _fed(producer, consumer)) for producer, consumer in pairs]
    return tuple((key, calls) for key, calls in fed if calls is not None)


def _fed(producer: list[str], consumer: list[str]) -> tuple[tuple[str, ...], ...] | None:
    texts = _literal_contents([producer])
    return fed_calls(consumer, texts[0]) if len(texts) == 1 and texts[0] is not None else None


def line_segments(command: str) -> list[list[str]]:
    """Split where a newline ends a command, because shlex reads one as a space and would merge every later command into the first."""
    return [segment for line in command_lines(command) for segment in _segments(line.text)]


def _logical_lines(command: str) -> list[tuple[str, list[str | None], list[str]]]:
    lines = command.splitlines()
    rows: list[tuple[str, list[str | None], list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        bodies: list[str | None] = []
        raw_bodies: list[str] = []
        for match in _heredoc_matches(line):
            raw_body, dynamic, index = _heredoc_body(lines, index, match)
            raw_bodies.append(raw_body)
            bodies.append(None if dynamic else raw_body)
        rows.append((line, bodies, raw_bodies))
    return rows


def _heredoc_matches(text: str) -> list[re.Match]:
    """Skip a << inside quotes, because the shell reads it as data."""
    quoted = [span.span() for span in QUOTED_FRAGMENT_RE.finditer(text)]
    return [
        match for match in HEREDOC_RE.finditer(text)
        if not any(start <= match.start() < end for start, end in quoted)
    ]


def executable_text(command: str) -> str:
    """Drop literal cat or tee heredoc bodies, because no shell runs them."""
    kept: list[str] = []
    for line, bodies, raw_bodies in _logical_lines(command):
        kept.append(line)
        unnested = "(" not in line and "`" not in line
        cursor = 0
        for group in _pipeline_groups(line):
            events, cursor = _group_heredoc_events(group, bodies, raw_bodies, cursor)
            data_only = unnested and all(_is_heredoc_sink(segment) for segment in group)
            kept.extend(event.body for event in events if event.dynamic or not data_only)
    return "\n".join(kept)


def _is_heredoc_sink(segment: list[str]) -> bool:
    index = _payload_command_index(segment)
    return index < len(segment) and _basename(segment[index]) in HEREDOC_SINKS


def _heredoc_body(lines: list[str], index: int, match: re.Match) -> tuple[str, bool, int]:
    strip, delimiter = match.group(1) == "-", match.group(2) or match.group(3) or match.group(4)
    collected: list[str] = []
    while index < len(lines):
        raw = lines[index]
        index += 1
        line = raw.lstrip("\t") if strip else raw
        if line.rstrip() == delimiter:
            body = "".join(line + "\n" for line in collected)
            expandable = match.group(4) is not None
            return body, expandable and bool(DYNAMIC_RE.search(body)), index
        collected.append(line)
    return "\n".join(collected), True, index


def _line_writes(line: str, bodies: list[str | None]) -> list[LiteralWrite]:
    """Because an unrelated command on the same line can also write, a heredoc there must never stand in for this one's content."""
    rows: list[LiteralWrite] = []
    cursor = 0
    for group in _pipeline_groups(line):
        heredoc_total = sum(len(_heredoc_matches(_segment_text(segment))) for segment in group)
        group_bodies = bodies[cursor:cursor + heredoc_total]
        cursor += heredoc_total
        target_writes = [write for segment in group for write in _content_words(segment)]
        if not target_writes:
            continue
        contents = group_bodies if heredoc_total else _literal_contents(group)
        rows.extend(_paired_writes(target_writes, contents))
    return rows


def _paired_writes(target_writes: list[tuple[str, bool]], contents: list[str | None]) -> list[LiteralWrite]:
    if not contents or None in contents:
        return []
    if len(contents) == 1:
        return [LiteralWrite(path, contents[0], append) for path, append in target_writes]
    if len(contents) == len(target_writes):
        return [LiteralWrite(path, text, append) for (path, append), text in zip(target_writes, contents)]
    return []


def _write_path_writes(segment: list[str]) -> list[tuple[str, bool]]:
    return [(_bare(word), append) for word, append in _write_path_words(segment)]


def _write_path_words(segment: list[str]) -> list[tuple[str, bool]]:
    """Raw words of every file outside bare stderr, because a quote decides whether $M expands."""
    opened = [(word, append) for word, append, descriptor in _descriptor_writes(segment) if descriptor != STDERR_DESCRIPTOR]
    words = list(dict.fromkeys(_redirect_words(segment) + opened)) + _tee_words(segment)
    return [(word, append) for word, append in words if _is_file_target(_bare(word))]


def _journal_words(segment: list[str]) -> list[tuple[str, bool]]:
    """Every file a descriptor opens, because the run truncates a stderr file too and the post-run scan must read it."""
    opened = [(word, append) for word, append, _ in _descriptor_writes(segment)]
    words = list(dict.fromkeys(_write_path_words(segment) + opened))
    return [(word, append) for word, append in words if _is_file_target(_bare(word))]


def _content_words(segment: list[str]) -> list[tuple[str, bool]]:
    """Only fd 1's file and tee, because a file opened on another descriptor receives none of a producer's text."""
    words = _redirect_words(segment) + _tee_words(segment)
    return [(word, append) for word, append in words if _is_file_target(_bare(word))]


def _target_words(segment: list[str]) -> list[str]:
    """Because 2>file creates or truncates its file even when nothing reaches it, every descriptor counts."""
    words = [word for word, _, _ in _descriptor_writes(segment)] + [word for word, _ in _tee_words(segment)]
    return [word for word in words if _is_file_target(_bare(word))]


def _redirect_paths(segment: list[str]) -> list[str]:
    return [_bare(word) for word, _, _ in _descriptor_writes(segment)]


def _redirect_words(segment: list[str]) -> list[tuple[str, bool]]:
    """The file fd 1 ends on, because a literal producer prints to stdout and 2>f 1>&2 sends that into f."""
    table: dict[str, tuple[str, bool] | None] = {}
    for index, token in enumerate(segment):
        match = REDIRECT_HEAD_RE.match(token)
        if match and not _is_quoted(token):
            word = token[match.end():] or (segment[index + 1] if index + 1 < len(segment) else "")
            _route(table, (match.group(1) or STDOUT_DESCRIPTOR, match.group(2), word))
    route = table.get(STDOUT_DESCRIPTOR)
    return [route] if route is not None else []


def _route(table: dict[str, tuple[str, bool] | None], redirect: tuple[str, str, str]) -> None:
    """Because N>&M copies where M points now, a later redirect of M leaves N alone."""
    descriptor, operator, word = redirect
    source = _bare(word)
    if operator.startswith("&") or (operator == ">&" and not DESCRIPTOR_WORD_RE.fullmatch(source) and descriptor == STDOUT_DESCRIPTOR):
        table[STDOUT_DESCRIPTOR] = table[STDERR_DESCRIPTOR] = (word, operator.endswith(">>"))
    elif operator != ">&" or not DESCRIPTOR_WORD_RE.fullmatch(source):
        table[descriptor] = (word, operator == ">>")
    else:
        number = source.rstrip("-")
        table[descriptor] = table.get(number) if number else None
        table.update({number: None} if source.endswith("-") and number else {})


def _descriptor_writes(segment: list[str]) -> list[tuple[str, bool, str]]:
    writes = []
    for index, token in enumerate(segment):
        match = REDIRECT_HEAD_RE.match(token)
        if _is_quoted(token) or not match:
            continue
        word = token[match.end():]
        if not word and index + 1 < len(segment):
            word = segment[index + 1]
        if match.group(2) == ">&" and (match.group(1) or re.fullmatch(r"(?:[0-9]+-?|-)", _bare(word))):
            continue
        writes.append((word, match.group(2) in {">>", "&>>"}, match.group(1)))
    return writes


def _tee_words(segment: list[str]) -> list[tuple[str, bool]]:
    index = _command_word_index(segment)
    if index >= len(segment) or _basename(segment[index]) != "tee":
        return []
    args = segment[index + 1:]
    append = any(_bare(token) in TEE_APPEND_FLAGS for token in args)
    return [(token, append) for token in args if not _bare(token).startswith("-")]


def _is_file_target(path: str) -> bool:
    return bool(path) and not path.startswith("/dev/")


def _literal_contents(segments: list[list[str]]) -> list[str | None]:
    contents = []
    for segment in segments:
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in LITERAL_PRODUCERS:
            contents.append(_producer_text(_basename(segment[index]), segment[index + 1:]))
            continue
        payload = _shell_c_literal_payload(segment)
        if payload is not None:
            contents.append(payload)
    return contents


def _shell_c_literal_payload(segment: list[str]) -> str | None:
    """Read the payload's own literal producer text, because an outer redirect on the sh -c segment captures that inner command's stdout, not the payload's own source line."""
    invocation = interpreter_invocation(segment)
    if invocation is None or invocation.interpreter not in SHELL_C_INTERPRETERS or invocation.payload is None:
        return None
    inner_segments = _segments(invocation.payload)
    if len(inner_segments) != 1:
        return None
    contents = _literal_contents(inner_segments)
    if len(contents) != 1:
        return None
    return contents[0]


def _producer_words(args: list[str]) -> list[str] | None:
    words: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        match = REDIRECT_HEAD_RE.match(token)
        if match and not _is_quoted(token):
            skip = not token[match.end():]
            continue
        if DYNAMIC_RE.search(token) and not (token.startswith("'") and token.endswith("'")):
            return None
        words.append(_bare(token))
    return words


def _echo_flags(flags: str, ending: str, expand: bool) -> tuple[str, bool]:
    for option in flags[1:]:
        if option == "n":
            ending = ""
        else:
            expand = option == "e"
    return ending, expand


def _producer_text(producer: str, args: list[str]) -> str | None:
    words = _producer_words(args)
    if words is None:
        return None
    if producer == "printf":
        return _printf_text(words)
    ending = "\n" if producer == "echo" else ""
    expand = False
    while producer == "echo" and words and re.fullmatch(r"-[neE]+", words[0]):
        ending, expand = _echo_flags(words.pop(0), ending, expand)
    text = " ".join(words)
    if expand:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text + ending


def _printf_tokens(format_string: str) -> list[str | None] | None:
    tokens = PRINTF_TOKEN_RE.findall(format_string)
    if "".join(tokens) != format_string:
        return None
    return [None if token == "%s" else "%" if token == "%%" else _printf_escape(token) for token in tokens]


def _printf_escape(token: str) -> str:
    """Octal by value, because printf turns \\0 into the NUL that frames xargs -0 input."""
    if not token.startswith("\\"):
        return token
    return chr(int(token[1:], 8) & 0xFF) if token[1:].isdigit() else PRINTF_ESCAPES[token[1]]


def _printf_text(words: list[str]) -> str | None:
    options_ended = words[:1] == ["--"]
    args = words[1:] if options_ended else words
    if not args or (not options_ended and args[0].startswith("-")):
        return None
    tokens = _printf_tokens(args[0])
    if tokens is None:
        return None
    values = args[1:]
    slots = tokens.count(None)
    rounds = max(1, (len(values) + slots - 1) // slots) if slots else 1
    size = rounds * sum(len(token) for token in tokens if token is not None)
    if slots:
        size += sum(len(value) for value in values)
    if size > MAX_LITERAL_OUTPUT_CHARS:
        return None
    remaining = iter(values)
    return "".join(
        next(remaining, "") if token is None else token
        for _ in range(rounds) for token in tokens
    )


def heredoc_events(command: str) -> list[HeredocEvent]:
    """Walks segments inside each pipeline group, because a heredoc belongs to the one segment that consumes it, not the whole line."""
    events: list[HeredocEvent] = []
    for line, bodies, raw_bodies in _logical_lines(command):
        cursor = 0
        for group in _pipeline_groups(line):
            group_events, cursor = _group_heredoc_events(group, bodies, raw_bodies, cursor)
            events.extend(group_events)
    return events


def _group_heredoc_events(
    group: list[list[str]], bodies: list[str | None], raw_bodies: list[str], cursor: int,
) -> tuple[list[HeredocEvent], int]:
    group_has_write_target = any(_write_path_writes(segment) for segment in group)
    events: list[HeredocEvent] = []
    for segment in group:
        heredoc_count = len(_heredoc_matches(_segment_text(segment)))
        for offset in range(heredoc_count):
            events.append(HeredocEvent(
                consumer_segment=segment,
                body=raw_bodies[cursor + offset],
                dynamic=bodies[cursor + offset] is None,
                group_has_write_target=group_has_write_target,
            ))
        cursor += heredoc_count
    return events, cursor


def _expand_home(token: str) -> str:
    token = OPERAND_PREFIX_RE.sub("", token, count=1)
    match = HOME_TOKEN_RE.match(token)
    if not match:
        return token
    return "~" + token[match.end():]
