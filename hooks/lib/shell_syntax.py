from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath
from typing import NamedTuple

DYNAMIC_RE = re.compile(r"[$`]")
SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&", "(", ")"})
PIPE_OPERATORS = frozenset({"|", "|&"})
# Matched only in command position, because naming a script inside a quoted string is not running it.
INTERPRETERS = frozenset({
    "python", "python3", "sh", "bash", "zsh", "dash", "command", "env", "exec", "sudo", "time", "nohup",
})
# Excludes true interpreters, because stepping past one here would let a wrapper hide inline code from detection.
WRAPPER_COMMANDS = frozenset({"env", "sudo", "nohup", "time", "command", "exec"})
# Skip ordinary wrapper flag values but reparse env split strings because only the latter can contain commands.
WRAPPER_VALUE_FLAGS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-a", "--argv0"}),
    "sudo": frozenset({
        "-u", "--user", "-g", "--group", "-h",
        "-C", "--close-from", "-D", "--chdir", "-R", "--chroot",
        "-T", "--command-timeout", "-p", "--prompt", "-r", "--role", "-t", "--type",
    }),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "exec": frozenset({"-a"}),
}
ENV_SPLIT_STRING_FLAGS = frozenset({"-S", "--split-string"})
INTERPRETER_CODE_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-c"}), "python3": frozenset({"-c"}), "python2": frozenset({"-c"}),
    "node": frozenset({"-e", "--eval", "-p", "--print"}), "nodejs": frozenset({"-e", "--eval", "-p", "--print"}),
    "ruby": frozenset({"-e"}),
    "perl": frozenset({"-e", "-E"}),
    "php": frozenset({"-r"}),
    "sh": frozenset({"-c"}), "bash": frozenset({"-c"}), "zsh": frozenset({"-c"}), "dash": frozenset({"-c"}), "ksh": frozenset({"-c"}),
}
SHELL_C_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Because a fused file operand must not defeat this match, the file half is optional here.
LEADING_REDIRECT_RE = re.compile(r"^(\d*)(>>?|>\||<<?)")
VERSIONED_PYTHON_RE = re.compile(r"^(python[23])\.\d+$")
QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
PROCESS_SUBSTITUTION_RE = re.compile(r"[<>]\(")


class InterpreterInvocation(NamedTuple):
    """Carries None for the payload when it is dynamic, because a guessed literal would misreport what the interpreter actually receives."""
    interpreter: str
    flag: str
    payload: str | None


def _command_word_index(segment: list[str]) -> int:
    """Step past env assignments and wrapper interpreters, because the word after them is what actually runs."""
    return _skip_prefixes(segment, INTERPRETERS)


def _payload_command_index(segment: list[str]) -> int:
    """Stops at an interpreter rather than stepping past it, because interpreter_invocation needs the interpreter itself in command position."""
    return _skip_prefixes(segment, WRAPPER_COMMANDS)


def _skip_prefixes(segment: list[str], names: frozenset[str]) -> int:
    """Walk past redirects, assignments, and named wrappers, including their flags, because a leading redirect or an inserted env -i must not hide the verb."""
    index = 0
    while index < len(segment):
        redirect_index = _skip_leading_redirect(segment, index)
        if redirect_index is not None:
            index = redirect_index
            continue
        token = segment[index]
        if not _is_quoted(token):
            name, separator, _ = token.partition("=")
            if separator and name:
                index += 1
                continue
        command_name = _basename(token)
        if command_name in names:
            if command_name in WRAPPER_COMMANDS:
                index = _skip_wrapper_options(segment, index)
            else:
                index += 1
            continue
        return index
    return len(segment)


def _skip_leading_redirect(segment: list[str], index: int) -> int | None:
    """Return the index past one redirect operator and its file operand, or None when the token here is not a redirect, because a command word can sit behind a redirect that precedes it on the line."""
    token = segment[index]
    if _is_quoted(token):
        return None
    match = LEADING_REDIRECT_RE.match(token)
    if not match:
        return None
    rest = token[match.end():]
    index += 1
    if not rest and index < len(segment):
        index += 1
    return index


def _skip_wrapper_options(segment: list[str], index: int) -> int:
    """Consume the wrapper word and the flags it owns, because env -i and sudo -u are options, not the child command."""
    value_flags = WRAPPER_VALUE_FLAGS.get(_basename(segment[index]), frozenset())
    index += 1
    while index < len(segment):
        token = segment[index]
        bare = _bare(token)
        if bare == "--":
            return index + 1
        if not _is_quoted(token):
            name, separator, _ = token.partition("=")
            if separator and name and not bare.startswith("-"):
                index += 1
                continue
        if not bare.startswith("-"):
            return index
        if "=" in bare or not _wrapper_consumes_value(bare, value_flags):
            index += 1
            continue
        index += 2
    return index


def _wrapper_consumes_value(bare: str, value_flags: frozenset[str]) -> bool:
    """Treat a short cluster as value-taking when any letter matches, because sudo -un still consumes the user name."""
    if bare in value_flags:
        return True
    if bare.startswith("--") or len(bare) < 2:
        return False
    value_letters = {flag[1] for flag in value_flags if len(flag) == 2}
    return any(letter in value_letters for letter in bare[1:])


def _interpreter_code_flags(name: str) -> frozenset[str] | None:
    """Resolve flags for a versioned interpreter basename, because python3.12 is the same runtime as python3."""
    flags = INTERPRETER_CODE_FLAGS.get(name)
    if flags is not None:
        return flags
    match = VERSIONED_PYTHON_RE.fullmatch(name)
    if match is None:
        return None
    return INTERPRETER_CODE_FLAGS.get(match.group(1))


def interpreter_invocation(segment: list[str]) -> InterpreterInvocation | None:
    """Reads only the command-position word, because a quoted mention of an interpreter elsewhere in the segment invokes nothing."""
    index = _payload_command_index(segment)
    if index >= len(segment):
        return None
    name = _basename(segment[index])
    flags = _interpreter_code_flags(name)
    if flags is None:
        return None
    matched = _flag_payload_token(segment[index + 1:], flags)
    if matched is None:
        return None
    flag, payload_token = matched
    if payload_token is None:
        return None
    payload = _bare(payload_token) if _is_literal_token(payload_token) else None
    return InterpreterInvocation(name, flag, payload)


def _flag_payload_token(args: list[str], flags: frozenset[str]) -> tuple[str, str | None] | None:
    """Matches a code flag whether it is clustered, quoted, or fused with its payload, because bash -lc and python3 -c'code' still pass that payload to the interpreter."""
    long_flags = [flag for flag in flags if flag.startswith("--")]
    short_flags = [flag for flag in flags if len(flag) == 2 and flag.startswith("-")]
    for i, arg in enumerate(args):
        bare = _bare(arg)
        if bare in flags:
            return bare, args[i + 1] if i + 1 < len(args) else None
        for flag in long_flags:
            prefix = flag + "="
            if bare.startswith(prefix):
                return flag, bare[len(prefix):]
        next_arg = args[i + 1] if i + 1 < len(args) else None
        for flag in short_flags:
            letter = flag[1]
            if len(bare) > 2 and bare.startswith("-") and not bare.startswith("--") and bare[-1] == letter and bare[1:-1].isalpha():
                return flag, next_arg
        for flag in short_flags:
            if bare.startswith(flag) and len(bare) > len(flag):
                return flag, bare[len(flag):]
    return None


def _is_literal_token(token: str) -> bool:
    if token.startswith("'") and token.endswith("'") and len(token) >= 2:
        return True
    return not DYNAMIC_RE.search(token)


def has_process_substitution(segment: str) -> bool:
    """Masks quoted spans first, because a literal mention of <( inside a string must not read as real process substitution."""
    masked = QUOTED_SPAN_RE.sub(lambda match: "'" * len(match.group()), segment)
    return bool(PROCESS_SUBSTITUTION_RE.search(masked))


CLOBBER_HEAD_RE = re.compile(r"^\d*>$")


def _tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        raw = list(lexer)
    except ValueError:
        raw = command.split()
    raw = _merge_adjacent_fragments(command, raw)
    return _expand_env_split_strings(_merge_clobber_operator(raw))


def _merge_adjacent_fragments(command: str, tokens: list[str]) -> list[str]:
    """Join fragments that touch with no whitespace between them into one token, because Bash concatenates a quoted span directly against a neighboring quoted or bare span into a single word, while shlex leaves each quoted span as its own token."""
    merged: list[str] = []
    search_from = 0
    prev_end: int | None = None
    prev_is_word = False
    for token in tokens:
        start = command.find(token, search_from)
        if start == -1:
            start = search_from
        end = start + len(token)
        is_word = token not in SEPARATORS
        if is_word and prev_is_word and start == prev_end:
            merged[-1] += token
        else:
            merged.append(token)
        prev_end = end
        prev_is_word = is_word
        search_from = end
    return merged


def _is_unquoted_assignment(token: str) -> bool:
    if _is_quoted(token):
        return False
    name, separator, _ = token.partition("=")
    return bool(separator and name)


def _expand_command_position_token(
    tokens: list[str], index: int, result: list[str],
) -> tuple[int, bool]:
    token = tokens[index]
    if _is_unquoted_assignment(token):
        result.append(token)
        return index + 1, True
    command_name = _basename(token)
    if command_name == "env":
        result.append(token)
        return _expand_env_flags(tokens, index + 1, result), True
    if command_name in WRAPPER_COMMANDS:
        result.append(token)
        child = _skip_wrapper_options(tokens, index)
        result.extend(tokens[index + 1:child])
        return child, True
    result.append(token)
    return index + 1, False


def _copy_env_flag(tokens: list[str], index: int, result: list[str]) -> int:
    token = tokens[index]
    bare = _bare(token)
    result.append(token)
    if "=" in bare or not _wrapper_consumes_value(bare, WRAPPER_VALUE_FLAGS["env"]):
        return index + 1
    if index + 1 >= len(tokens) or tokens[index + 1] in SEPARATORS:
        return index + 1
    result.append(tokens[index + 1])
    return index + 2


def _expand_env_split_strings(tokens: list[str]) -> list[str]:
    """Re-parse env -S/--split-string payloads in command position, because that argument is a command line rather than a wrapper value to skip."""
    result: list[str] = []
    index = 0
    command_position = True
    while index < len(tokens):
        token = tokens[index]
        if token in SEPARATORS:
            result.append(token)
            command_position = True
            index += 1
            continue
        if not command_position:
            result.append(token)
            index += 1
            continue
        index, command_position = _expand_command_position_token(tokens, index, result)
    return result


def _expand_env_flags(tokens: list[str], index: int, result: list[str]) -> int:
    """Copy env flags, splicing any -S/--split-string payload into argv, because that payload is the child command line."""
    while index < len(tokens):
        if tokens[index] in SEPARATORS:
            return index
        payload, consumed, keep_prefix = _env_split_string_at(tokens, index)
        if payload is not None:
            replacement = ([keep_prefix] if keep_prefix else []) + _tokens(payload)
            tokens[index:index + consumed] = replacement
            continue
        token = tokens[index]
        bare = _bare(token)
        if bare == "--":
            result.append(token)
            return index + 1
        if _is_unquoted_assignment(token) and not bare.startswith("-"):
            result.append(token)
            index += 1
            continue
        if not bare.startswith("-"):
            return index
        index = _copy_env_flag(tokens, index, result)
    return index


def _env_split_string_at(tokens: list[str], index: int) -> tuple[str | None, int, str | None]:
    """Return the split-string payload and how many tokens it occupies, because -S, --split-string, fused = forms, and a trailing S in a short cluster all name a command line."""
    bare = _bare(tokens[index])
    next_token = tokens[index + 1] if index + 1 < len(tokens) and tokens[index + 1] not in SEPARATORS else None
    if bare in ENV_SPLIT_STRING_FLAGS and next_token is not None:
        return _bare(next_token), 2, None
    if bare.startswith("--split-string="):
        payload, consumed = _fused_split_string_payload(tokens, index, bare.partition("=")[2])
        return payload, consumed, None
    if bare.startswith("-S") and not bare.startswith("--") and len(bare) > 2:
        rest = bare[2:]
        payload, consumed = _fused_split_string_payload(
            tokens, index, rest[1:] if rest.startswith("=") else rest,
        )
        return payload, consumed, None
    letters = bare[1:]
    if next_token is not None and bare.startswith("-") and not bare.startswith("--") and letters.endswith("S") and letters[:-1].isalpha():
        return _bare(next_token), 2, bare[:-1]
    return None, 0, None


def _fused_split_string_payload(tokens: list[str], index: int, rest: str) -> tuple[str, int]:
    """Rejoin a fused remainder and strip wrapping quotes, because posix=False shlex leaves -S'…' quotes attached and splits on the spaces they were meant to protect."""
    payload = rest
    consumed = 1
    cursor = index + 1
    while payload and payload[0] in "'\"" and not _is_quoted(payload) and cursor < len(tokens) and tokens[cursor] not in SEPARATORS:
        payload = payload + " " + tokens[cursor]
        consumed += 1
        cursor += 1
    return _bare(payload), consumed


def _segments(command: str) -> list[list[str]]:
    """Split into shell segments of raw tokens, keeping quotes so that quoted text can be masked later."""
    segments: list[list[str]] = []
    current: list[str] = []
    for token in _tokens(command):
        if token in SEPARATORS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _pipeline_groups(command: str) -> list[list[list[str]]]:
    """Because ; && || & ( ) start an unrelated command, only a | may carry one segment's content into the next."""
    groups: list[list[list[str]]] = []
    group: list[list[str]] = []
    current: list[str] = []
    for token in _tokens(command):
        if token in PIPE_OPERATORS:
            if current:
                group.append(current)
            current = []
            continue
        if token in SEPARATORS:
            if current:
                group.append(current)
            current = []
            if group:
                groups.append(group)
            group = []
            continue
        current.append(token)
    if current:
        group.append(current)
    if group:
        groups.append(group)
    return groups


def _merge_clobber_operator(tokens: list[str]) -> list[str]:
    """Because the lexer has no notion of >| as one operator, its split halves would otherwise drop the write target."""
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            not _is_quoted(token) and CLOBBER_HEAD_RE.match(token)
            and index + 1 < len(tokens) and tokens[index + 1] == "|"
        ):
            merged.append(token)
            index += 2
            continue
        merged.append(token)
        index += 1
    return merged


def _is_quoted(token: str) -> bool:
    return len(token) > 1 and token[0] in "\"'" and token[-1] == token[0]


def _bare(token: str) -> str:
    return token[1:-1] if _is_quoted(token) else token


def _segment_text(segment: list[str]) -> str:
    """Join a segment with quoted tokens blanked, because text inside quotes is data rather than shell syntax."""
    return " ".join("''" if _is_quoted(token) else token for token in segment)


def _leading_assignments(segment: list[str]) -> list[str]:
    names = []
    for token in segment:
        if _is_quoted(token):
            break
        name, separator, _ = token.partition("=")
        if not separator or not name:
            break
        names.append(name)
    return names


def _words(segment: list[str]) -> list[str]:
    return [_bare(token) for token in segment]


def _basename(token: str) -> str:
    return PurePosixPath(_bare(token).strip(",")).name
