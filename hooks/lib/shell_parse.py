"""Shell command tokenizing: split a Bash command into segments and locate the literal targets it writes."""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

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


def write_paths(command: str) -> list[str]:
    """Because an undecidable write body is not the same as no write at all, keep the target even when its content is unreadable here."""
    return [
        path
        for line, _, _ in _logical_lines(command)
        for segment in _segments(line)
        for path in _write_paths(segment)
    ]


def write_targets(command: str) -> list[tuple[str, str]]:
    """Drop a write whose text is not knowable here, because a guessed body would misreport what the command actually sends."""
    rows: list[tuple[str, str]] = []
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


def _line_writes(line: str, bodies: list[str | None]) -> list[tuple[str, str]]:
    """Because an unrelated command on the same line can also write, a heredoc there must never stand in for this one's content."""
    rows: list[tuple[str, str]] = []
    cursor = 0
    for group in _pipeline_groups(line):
        heredoc_total = sum(len(HEREDOC_RE.findall(_segment_text(segment))) for segment in group)
        group_bodies = bodies[cursor:cursor + heredoc_total]
        cursor += heredoc_total
        targets = [path for segment in group for path in _write_paths(segment)]
        if not targets:
            continue
        contents = group_bodies if heredoc_total else _literal_contents(group)
        rows.extend(_paired_writes(targets, contents))
    return rows


def _paired_writes(targets: list[str], contents: list[str | None]) -> list[tuple[str, str]]:
    if not contents or None in contents:
        return []
    if len(contents) == 1:
        return [(path, contents[0]) for path in targets]
    if len(contents) == len(targets):
        return list(zip(targets, contents))
    return []


def _write_paths(segment: list[str]) -> list[str]:
    paths = _redirect_paths(segment)
    index = _command_word_index(segment)
    if index < len(segment) and _basename(segment[index]) == "tee":
        paths.extend(_bare(token) for token in segment[index + 1:] if not _bare(token).startswith("-"))
    return [path for path in paths if _is_file_target(path)]


def _redirect_paths(segment: list[str]) -> list[str]:
    paths = []
    for index, token in enumerate(segment):
        match = REDIRECT_HEAD_RE.match(token)
        if _is_quoted(token) or not match or match.group(1) == STDERR_DESCRIPTOR:
            continue
        rest = token[match.end():]
        if not rest and index + 1 < len(segment):
            rest = segment[index + 1]
        paths.append(_bare(rest))
    return paths


def _is_file_target(path: str) -> bool:
    return bool(path) and not path.startswith("&") and not path.startswith("/dev/")


def _command_word_index(segment: list[str]) -> int:
    """Step past env assignments and wrapper interpreters, because the word after them is what actually runs."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if _is_quoted(token):
            return index
        name, separator, _ = token.partition("=")
        if (separator and name) or _basename(token) in INTERPRETERS:
            index += 1
            continue
        return index
    return len(segment)


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


CLOBBER_HEAD_RE = re.compile(r"^\d*>$")


def _tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        raw = list(lexer)
    except ValueError:
        raw = command.split()
    return _merge_clobber_operator(raw)


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
