"""Shell command tokenizing: split a Bash command into segments and locate the literal targets it writes."""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath
from typing import NamedTuple

# Matches only the exact descriptor 2, because a bare stderr redirect writes no target file.
STDERR_DESCRIPTOR = "2"
REDIRECT_HEAD_RE = re.compile(r"^(\d*)(>>?)")
HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s()<>|&;'\"]+))")
DYNAMIC_RE = re.compile(r"[$`]")
LITERAL_PRODUCERS = frozenset({"echo", "printf"})
ECHO_FLAGS = frozenset({"-n", "-e", "-E", "-ne", "-en"})
SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&", "(", ")"})
PIPE_OPERATORS = frozenset({"|", "|&"})
HOME_TOKEN_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
# Strips the of= and if= style operands used by dd, because the path hides behind the key.
OPERAND_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Matched only in command position, because naming a script inside a quoted string is not running it.
INTERPRETERS = frozenset({
    "python", "python3", "sh", "bash", "zsh", "dash", "command", "env", "exec", "sudo", "time", "nohup",
})
# Excludes true interpreters, because stepping past one here would let a wrapper hide inline code from detection.
WRAPPER_COMMANDS = frozenset({"env", "sudo", "nohup", "time", "command", "exec"})
# Value-taking wrapper flags, because skipping only the wrapper word would treat sudo -u or env -u as the command.
# env -S/--split-string is not listed here, because its argument is a command line that must be re-parsed rather than skipped.
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
TEE_APPEND_FLAGS = frozenset({"-a", "--append"})
INTERPRETER_CODE_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-c"}), "python3": frozenset({"-c"}), "python2": frozenset({"-c"}),
    "node": frozenset({"-e", "--eval", "-p", "--print"}), "nodejs": frozenset({"-e", "--eval", "-p", "--print"}),
    "ruby": frozenset({"-e"}),
    "perl": frozenset({"-e", "-E"}),
    "php": frozenset({"-r"}),
    "sh": frozenset({"-c"}), "bash": frozenset({"-c"}), "zsh": frozenset({"-c"}), "dash": frozenset({"-c"}), "ksh": frozenset({"-c"}),
}
VERSIONED_PYTHON_RE = re.compile(r"^(python[23])\.\d+$")
QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
PROCESS_SUBSTITUTION_RE = re.compile(r"[<>]\(")


class LiteralWrite(NamedTuple):
    """Carries the append flag next to the text, because downstream scanning treats an overwrite and an append as different shapes."""
    path: str
    text: str
    append: bool


class InterpreterInvocation(NamedTuple):
    """Carries None for the payload when it is dynamic, because a guessed literal would misreport what the interpreter actually receives."""
    interpreter: str
    flag: str
    payload: str | None


class HeredocEvent(NamedTuple):
    """Carries the consumer segment and group write-target flag next to the body, because a shared line must not blur one heredoc's context into another's."""
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
    """Stays a path-and-text pair, because existing callers would break if the append flag were forced into their tuples."""
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
            body = "\n".join(collected)
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
        writes.append((_bare(rest), match.group(2) == ">>"))
    return writes


def _tee_writes(segment: list[str]) -> list[tuple[str, bool]]:
    index = _command_word_index(segment)
    if index >= len(segment) or _basename(segment[index]) != "tee":
        return []
    args = segment[index + 1:]
    append = any(_bare(token) in TEE_APPEND_FLAGS for token in args)
    return [(_bare(token), append) for token in args if not _bare(token).startswith("-")]


def _is_file_target(path: str) -> bool:
    return bool(path) and not path.startswith("&") and not path.startswith("/dev/")


def _command_word_index(segment: list[str]) -> int:
    """Step past env assignments and wrapper interpreters, because the word after them is what actually runs."""
    return _skip_prefixes(segment, INTERPRETERS)


def _payload_command_index(segment: list[str]) -> int:
    """Stops at an interpreter rather than stepping past it, because interpreter_invocation needs the interpreter itself in command position."""
    return _skip_prefixes(segment, WRAPPER_COMMANDS)


def _skip_prefixes(segment: list[str], names: frozenset[str]) -> int:
    """Walk past assignments and named wrappers, including their flags, because quoting or inserting env -i must not hide the verb."""
    index = 0
    while index < len(segment):
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


def _literal_contents(segments: list[list[str]]) -> list[str | None]:
    contents = []
    for segment in segments:
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in LITERAL_PRODUCERS:
            contents.append(_producer_text(segment[index + 1:]))
    return contents


def _producer_text(args: list[str]) -> str | None:
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
        if not words and _bare(token) in ECHO_FLAGS:
            continue
        words.append(_bare(token))
    return " ".join(words).replace("\\n", "\n").replace("\\t", "\t")


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
    return _expand_env_split_strings(_merge_clobber_operator(raw))


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
        if not _is_quoted(token):
            name, separator, _ = token.partition("=")
            if separator and name:
                result.append(token)
                index += 1
                continue
        command_name = _basename(token)
        if command_name == "env":
            result.append(token)
            index = _expand_env_flags(tokens, index + 1, result)
            continue
        if command_name in WRAPPER_COMMANDS:
            result.append(token)
            child = _skip_wrapper_options(tokens, index)
            result.extend(tokens[index + 1:child])
            index = child
            continue
        result.append(token)
        command_position = False
        index += 1
    return result


def _expand_env_flags(tokens: list[str], index: int, result: list[str]) -> int:
    """Copy env flags, splicing any -S/--split-string payload into argv, because that payload is the child command line."""
    value_flags = WRAPPER_VALUE_FLAGS["env"]
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
        if not _is_quoted(token):
            name, separator, _ = token.partition("=")
            if separator and name and not bare.startswith("-"):
                result.append(token)
                index += 1
                continue
        if not bare.startswith("-"):
            return index
        result.append(token)
        if "=" in bare or not _wrapper_consumes_value(bare, value_flags):
            index += 1
            continue
        if index + 1 < len(tokens) and tokens[index + 1] not in SEPARATORS:
            result.append(tokens[index + 1])
            index += 2
        else:
            index += 1
    return index


def _env_split_string_at(tokens: list[str], index: int) -> tuple[str | None, int, str | None]:
    """Return the split-string payload and how many tokens it occupies, because -S, --split-string, fused = forms, and a trailing S in a short cluster all name a command line."""
    bare = _bare(tokens[index])
    next_token = tokens[index + 1] if index + 1 < len(tokens) and tokens[index + 1] not in SEPARATORS else None
    if bare in ENV_SPLIT_STRING_FLAGS and next_token is not None:
        return _bare(next_token), 2, None
    if bare.startswith("--split-string="):
        return bare.partition("=")[2], 1, None
    if bare.startswith("-S") and not bare.startswith("--") and len(bare) > 2:
        rest = bare[2:]
        return rest[1:] if rest.startswith("=") else rest, 1, None
    letters = bare[1:]
    if next_token is not None and bare.startswith("-") and not bare.startswith("--") and letters.endswith("S") and letters[:-1].isalpha():
        return _bare(next_token), 2, bare[:-1]
    return None, 0, None


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


def _segment_paths(segment: list[str]) -> list[str]:
    paths = []
    for token in segment:
        for part in re.split(r"[<>|;&]+", _bare(token)):
            expanded = _expand_home(part.strip())
            if expanded:
                paths.append(expanded)
    return paths


def _expand_home(token: str) -> str:
    token = OPERAND_PREFIX_RE.sub("", token, count=1)
    match = HOME_TOKEN_RE.match(token)
    if not match:
        return token
    return "~" + token[match.end():]


def _basename(token: str) -> str:
    return PurePosixPath(_bare(token).strip(",")).name
