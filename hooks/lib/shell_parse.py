"""Shell command tokenizing: split a Bash command into segments and locate the literal targets it writes."""
from __future__ import annotations

import re
from typing import NamedTuple

from .shell_operators import REDIRECT_HEAD_RE
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
    _payload_command_index, _pipeline_groups, _segment_text, _segments,
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
    "HeredocEvent", "LiteralWrite", "heredoc_events", "literal_writes",
    "write_paths", "write_targets",
]

STDERR_DESCRIPTOR = "2"
HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s()<>|&;'\"]+))")
LITERAL_PRODUCERS = frozenset({"echo", "printf"})
HOME_TOKEN_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
OPERAND_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TEE_APPEND_FLAGS = frozenset({"-a", "--append"})
MAX_LITERAL_OUTPUT_CHARS = 1_000_000
PRINTF_TOKEN_RE = re.compile(r"%%|%s|\\[\\abefnrtv]|[^%\\]+")
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
    return [
        path
        for line, _, _ in _logical_lines(command)
        for segment in _segments(line)
        for path in _write_paths(segment)
    ]


def write_targets(command: str) -> list[tuple[str, str]]:
    return [(write.path, write.text) for write in literal_writes(command)]


def literal_writes(command: str) -> list[LiteralWrite]:
    """Drop a write whose text is not knowable here, because a guessed body would misreport what the command actually sends."""
    rows: list[LiteralWrite] = []
    for line, bodies, _ in _logical_lines(command):
        rows.extend(_line_writes(line, bodies))
    return rows


def _logical_lines(command: str) -> list[tuple[str, list[str | None], list[str]]]:
    lines = command.splitlines()
    rows: list[tuple[str, list[str | None], list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        bodies: list[str | None] = []
        raw_bodies: list[str] = []
        for match in HEREDOC_RE.finditer(line):
            raw_body, dynamic, index = _heredoc_body(lines, index, match)
            raw_bodies.append(raw_body)
            bodies.append(None if dynamic else raw_body)
        rows.append((line, bodies, raw_bodies))
    return rows


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
        heredoc_total = sum(len(HEREDOC_RE.findall(_segment_text(segment))) for segment in group)
        group_bodies = bodies[cursor:cursor + heredoc_total]
        cursor += heredoc_total
        target_writes = [write for segment in group for write in _write_path_writes(segment)]
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


def _write_paths(segment: list[str]) -> list[str]:
    return [path for path, _ in _write_path_writes(segment)]


def _write_path_writes(segment: list[str]) -> list[tuple[str, bool]]:
    writes = _redirect_writes(segment) + _tee_writes(segment)
    return [(path, append) for path, append in writes if _is_file_target(path)]


def _redirect_paths(segment: list[str]) -> list[str]:
    return [path for path, _ in _redirect_writes(segment)]


def _redirect_writes(segment: list[str]) -> list[tuple[str, bool]]:
    writes = []
    for index, token in enumerate(segment):
        match = REDIRECT_HEAD_RE.match(token)
        if _is_quoted(token) or not match or match.group(1) == STDERR_DESCRIPTOR:
            continue
        rest = token[match.end():]
        if not rest and index + 1 < len(segment):
            rest = segment[index + 1]
        target = _bare(rest)
        if match.group(2) == ">&" and (match.group(1) or re.fullmatch(r"(?:[0-9]+-?|-)", target)):
            continue
        writes.append((target, match.group(2) in {">>", "&>>"}))
    return writes


def _tee_writes(segment: list[str]) -> list[tuple[str, bool]]:
    index = _command_word_index(segment)
    if index >= len(segment) or _basename(segment[index]) != "tee":
        return []
    args = segment[index + 1:]
    append = any(_bare(token) in TEE_APPEND_FLAGS for token in args)
    return [(_bare(token), append) for token in args if not _bare(token).startswith("-")]


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


def _producer_text(producer: str, args: list[str]) -> str | None:
    words: list[str] = []
    skip = False
    ending = "\n" if producer == "echo" else ""
    expand = False
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
        word = _bare(token)
        if producer == "echo" and not words and re.fullmatch(r"-[neE]+", word):
            for option in word[1:]:
                if option == "n":
                    ending = ""
                else:
                    expand = option == "e"
            continue
        words.append(word)
    if producer == "printf":
        return _printf_text(words)
    text = " ".join(words)
    if expand:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text + ending


def _printf_tokens(format_string: str) -> list[str | None] | None:
    tokens = PRINTF_TOKEN_RE.findall(format_string)
    if "".join(tokens) != format_string:
        return None
    return [
        None if token == "%s" else "%" if token == "%%"
        else PRINTF_ESCAPES[token[1]] if token.startswith("\\") else token
        for token in tokens
    ]


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
        heredoc_count = len(HEREDOC_RE.findall(_segment_text(segment)))
        for offset in range(heredoc_count):
            events.append(HeredocEvent(
                consumer_segment=segment,
                body=raw_bodies[cursor + offset],
                dynamic=bodies[cursor + offset] is None,
                group_has_write_target=group_has_write_target,
            ))
        cursor += heredoc_count
    return events, cursor


def _expanded_token_paths(token: str) -> list[str]:
    paths: list[str] = []
    for part in re.split(r"[<>|;&]+", _bare(token)):
        expanded = _expand_home(part.strip())
        if expanded:
            paths.append(expanded)
    return paths


def _segment_paths(segment: list[str]) -> list[str]:
    paths: list[str] = []
    for token in segment:
        paths.extend(_expanded_token_paths(token))
    return paths


def _expand_home(token: str) -> str:
    token = OPERAND_PREFIX_RE.sub("", token, count=1)
    match = HOME_TOKEN_RE.match(token)
    if not match:
        return token
    return "~" + token[match.end():]
