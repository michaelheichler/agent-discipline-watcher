"""Because a shell runs whatever it reads, from a -c string, a script file, a redirect, or a pipe, the commit gate reads that input too."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NamedTuple

from .commit_functions import with_positional as _with_positional
from .path_policy import anchored
from .script_directory import ScriptLocation, with_script_directory
from .script_files import names_commit, runs_as_shell, script_text
from .shell_syntax import SHELL_C_INTERPRETERS, _basename, _payload_command_index

SCRIPT_READERS = frozenset({"source", "."})
SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O"})
STDIN_PATHS = frozenset({"-", "/dev/stdin"})
FD_PATH_RE = re.compile(r"/dev/fd/(\d+)")

PLAIN_COMMIT = "Run git commit as its own plain command."
PIPED_SHELL = f"This command pipes text that names commit into a shell, so the commit gate cannot read it. {PLAIN_COMMIT}"
UNREAD_SCRIPT = f"This command runs a script the commit gate cannot read, and the command or the script names commit. {PLAIN_COMMIT}"
DYNAMIC_SCRIPT = f"This command runs a script from a path the commit gate cannot resolve. {PLAIN_COMMIT}"
STALE_SCRIPT = (
    "This command changes a script or its folder and then runs it in the same call, so the commit gate would read "
    "the old script. Change the script in its own tool call, then run it."
)


class UnreadableCommit(Exception):
    """Raised because a commit the gate cannot resolve must be denied rather than let through."""


class Input(NamedTuple):
    path: str | None = None
    text: str | None = None


class Command(NamedTuple):
    words: list[str]
    inputs: dict[int, Input]
    outputs: list[str]


class InputScope(NamedTuple):
    cwd: Path
    feed: Command | None
    touched: set[str]
    script_kind: str = ""


@dataclass(frozen=True, slots=True)
class _ScriptRead:
    positional: list[str]
    command: Command
    scope: InputScope


class _ShellArgs(NamedTuple):
    reads_command: bool
    from_stdin: bool
    operand: str | None
    rest: list[str]
    parse_only: bool = False


def shell_input(command: Command, scope: InputScope) -> str | None:
    """None when the command runs no shell text, so the caller reads it as a plain command."""
    words = command.words
    index = _payload_command_index(words)
    word = words[index] if index < len(words) else ""
    name = word if word in SCRIPT_READERS else _basename(word)
    args = words[index + 1:]
    if name in {"eval", "trap"}:
        return _inline_script(name, args)
    if name in SHELL_C_INTERPRETERS:
        return _shell_script(_shell_args(args), command, scope)
    if name in SCRIPT_READERS:
        args = args[1:] if args[:1] == ["--"] else args
        if not args:
            return None
        sourced = scope._replace(script_kind="sourced" if "/" in args[0] else "")
        return _file_script(args[0], _ScriptRead(args[1:], command, sourced))
    if "/" in word and runs_as_shell(anchored(word, scope.cwd)):
        return _file_script(word, _ScriptRead(args, command, scope._replace(script_kind="executed")))
    return None


def _inline_script(name: str, args: list[str]) -> str | None:
    if name == "eval":
        return " ".join(args)
    args = args[1:] if args[:1] == ["--"] else args
    return args[0] if args and not args[0].startswith("-") else None


def normalized(cwd: Path, raw: str) -> str:
    return os.path.normpath(anchored(raw, cwd))


def is_dynamic(word: str) -> bool:
    return "$" in word or "`" in word


def _shell_args(args: list[str]) -> _ShellArgs:
    index, reads_command, from_stdin, parse_only = 0, False, False, False
    while index < len(args) and args[index].startswith(("-", "+")) and args[index] not in {"-", "--"}:
        letters = "" if args[index].startswith("--") else args[index][1:]
        reads_command, from_stdin = reads_command or "c" in letters, from_stdin or "s" in letters
        parse_only = parse_only or (args[index].startswith("-") and "n" in letters)
        index += 2 if args[index] in SHELL_VALUE_OPTIONS else 1
    index += 1 if index < len(args) and args[index] == "--" else 0
    operand = args[index] if index < len(args) else None
    return _ShellArgs(reads_command, from_stdin, operand, args[index + 1:], parse_only)


def _shell_script(shell: _ShellArgs, command: Command, scope: InputScope) -> str | None:
    """None for a parse-only run, because bash -n executes no line of its script."""
    if shell.parse_only:
        return None
    if shell.reads_command:
        return _with_positional(shell.operand or "", shell.rest[1:])
    if shell.from_stdin or shell.operand is None:
        positional = shell.rest if shell.operand is None else [shell.operand, *shell.rest]
        return _stdin_script(0, _ScriptRead(positional, command, scope))
    return _file_script(shell.operand, _ScriptRead(shell.rest, command, scope._replace(script_kind="executed")))


def _file_script(word: str, read: _ScriptRead) -> str | None:
    descriptor = _fd_of(word)
    if descriptor is not None:
        return _stdin_script(descriptor, replace(read, scope=read.scope._replace(script_kind="")))
    return _script_file(word, read)


def _stdin_script(descriptor: int, read: _ScriptRead) -> str | None:
    """Through the redirect first and the pipe after, because bash binds a redirect over the pipe."""
    source = read.command.inputs.get(descriptor)
    if source is not None and source.text is not None:
        return _with_positional(source.text, read.positional)
    if source is not None and source.path is not None and _fd_of(source.path) != descriptor:
        return _file_script(source.path, read)
    return _with_positional(_feed_script(read.scope), read.positional) if read.scope.feed is not None else None


def _feed_script(scope: InputScope) -> str:
    """Because cat hands over exactly the files it names, those files stand in for the shell's input."""
    feed = scope.feed
    index = _payload_command_index(feed.words)
    if index < len(feed.words) and _basename(feed.words[index]) == "cat":
        files = [word for word in feed.words[index + 1:] if not word.startswith("-") or word == "-"]
        alone = InputScope(scope.cwd, None, scope.touched)
        return "\n".join(_file_script(word, _ScriptRead([], feed, alone)) or "" for word in files or ["-"])
    if _mentions_commit(feed, scope.cwd):
        raise UnreadableCommit(PIPED_SHELL)
    return ""


def _mentions_commit(feed: Command, cwd: Path) -> bool:
    texts = [*feed.words, *(source.text or "" for source in feed.inputs.values())]
    paths = [*feed.words[1:], *(source.path for source in feed.inputs.values() if source.path)]
    return any("commit" in text for text in texts) or any(names_commit(anchored(path, cwd)) for path in paths)


def _script_file(word: str, read: _ScriptRead) -> str | None:
    scope = read.scope
    if is_dynamic(word):
        raise UnreadableCommit(DYNAMIC_SCRIPT)
    path = Path(normalized(scope.cwd, word))
    if any(str(candidate) in scope.touched for candidate in (path, *path.parents)):
        raise UnreadableCommit(STALE_SCRIPT)
    text = script_text(path)
    if text is not None:
        if scope.script_kind:
            location = ScriptLocation(path, word, scope.script_kind == "executed")
            text = with_script_directory(text, location)
        return _with_positional(text, read.positional)
    if any("commit" in part for part in read.command.words) or names_commit(path):
        raise UnreadableCommit(UNREAD_SCRIPT)
    return None


def _fd_of(word: str | None) -> int | None:
    if word in STDIN_PATHS:
        return 0
    match = FD_PATH_RE.fullmatch(word or "")
    return int(match.group(1)) if match else None
