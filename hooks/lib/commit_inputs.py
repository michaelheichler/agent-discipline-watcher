"""Because a shell runs whatever it reads, from a -c string, a script file, a redirect, or a pipe, the commit gate reads that input too."""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import NamedTuple

from .script_files import names_commit, runs_as_shell, script_text
from .shell_syntax import SHELL_C_INTERPRETERS, _basename, _payload_command_index

SCRIPT_READERS = frozenset({"source", "."})
SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O"})
STDIN_PATHS = frozenset({"-", "/dev/stdin"})
POSITIONAL_RE = re.compile(r'"\$\{?([@*1-9])\}?"|\$\{?([@*1-9])\}?')
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


class _ShellArgs(NamedTuple):
    reads_command: bool
    from_stdin: bool
    operand: str | None
    rest: list[str]


def shell_input(command: Command, scope: InputScope) -> str | None:
    """None when the command runs no shell text, so the caller reads it as a plain command."""
    words = command.words
    index = _payload_command_index(words)
    word = words[index] if index < len(words) else ""
    name = word if word in SCRIPT_READERS else _basename(word)
    args = words[index + 1:]
    if name == "eval":
        return " ".join(args)
    if name in SHELL_C_INTERPRETERS:
        return _shell_script(_shell_args(args), command, scope)
    if name in SCRIPT_READERS:
        args = args[1:] if args[:1] == ["--"] else args
        return _file_script(args[0], args[1:], command, scope) if args else None
    if "/" in word and runs_as_shell(resolve_cwd(scope.cwd, word)):
        return _file_script(word, args, command, scope)
    return None


def resolve_cwd(cwd: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else cwd / path


def normalized(cwd: Path, raw: str) -> str:
    return os.path.normpath(resolve_cwd(cwd, raw))


def is_dynamic(word: str) -> bool:
    return "$" in word or "`" in word


def _shell_args(args: list[str]) -> _ShellArgs:
    index, reads_command, from_stdin = 0, False, False
    while index < len(args) and args[index].startswith(("-", "+")) and args[index] not in {"-", "--"}:
        letters = "" if args[index].startswith("--") else args[index][1:]
        reads_command, from_stdin = reads_command or "c" in letters, from_stdin or "s" in letters
        index += 2 if args[index] in SHELL_VALUE_OPTIONS else 1
    index += 1 if index < len(args) and args[index] == "--" else 0
    return _ShellArgs(reads_command, from_stdin, args[index] if index < len(args) else None, args[index + 1:])


def _shell_script(shell: _ShellArgs, command: Command, scope: InputScope) -> str | None:
    if shell.reads_command:
        return _with_positional(shell.operand or "", shell.rest[1:])
    if shell.from_stdin or shell.operand is None:
        positional = shell.rest if shell.operand is None else [shell.operand, *shell.rest]
        return _stdin_script(0, positional, command, scope)
    return _file_script(shell.operand, shell.rest, command, scope)


def _file_script(word: str, positional: list[str], command: Command, scope: InputScope) -> str | None:
    fd = _fd_of(word)
    if fd is not None:
        return _stdin_script(fd, positional, command, scope)
    return _script_file(word, positional, command, scope)


def _stdin_script(fd: int, positional: list[str], command: Command, scope: InputScope) -> str | None:
    """Through the redirect first and the pipe after, because bash binds a redirect over the pipe."""
    source = command.inputs.get(fd)
    if source is not None and source.text is not None:
        return _with_positional(source.text, positional)
    if source is not None and source.path is not None and _fd_of(source.path) != fd:
        return _file_script(source.path, positional, command, scope)
    return _with_positional(_feed_script(scope), positional) if scope.feed is not None else None


def _feed_script(scope: InputScope) -> str:
    """Because cat hands over exactly the files it names, those files stand in for the shell's input."""
    feed = scope.feed
    index = _payload_command_index(feed.words)
    if index < len(feed.words) and _basename(feed.words[index]) == "cat":
        files = [word for word in feed.words[index + 1:] if not word.startswith("-") or word == "-"]
        alone = InputScope(scope.cwd, None, scope.touched)
        return "\n".join(_file_script(word, [], feed, alone) or "" for word in files or ["-"])
    if _mentions_commit(feed, scope.cwd):
        raise UnreadableCommit(PIPED_SHELL)
    return ""


def _mentions_commit(feed: Command, cwd: Path) -> bool:
    texts = [*feed.words, *(source.text or "" for source in feed.inputs.values())]
    paths = [*feed.words[1:], *(source.path for source in feed.inputs.values() if source.path)]
    return any("commit" in text for text in texts) or any(names_commit(resolve_cwd(cwd, path)) for path in paths)


def _script_file(word: str, positional: list[str], command: Command, scope: InputScope) -> str | None:
    if is_dynamic(word):
        raise UnreadableCommit(DYNAMIC_SCRIPT)
    path = Path(normalized(scope.cwd, word))
    if any(str(candidate) in scope.touched for candidate in (path, *path.parents)):
        raise UnreadableCommit(STALE_SCRIPT)
    text = script_text(path)
    if text is not None:
        return _with_positional(text, positional)
    if any("commit" in part for part in command.words) or names_commit(path):
        raise UnreadableCommit(UNREAD_SCRIPT)
    return None


def _with_positional(text: str, positional: list[str]) -> str:
    """Substituted, because "$@" runs the given words as a command while echo "$@" only prints them."""
    return POSITIONAL_RE.sub(lambda match: _positional_value(match, positional), text) if positional else text


def _positional_value(match: re.Match, positional: list[str]) -> str:
    name = match.group(1) or match.group(2)
    if name in "@*":
        return shlex.join(positional)
    index = int(name) - 1
    return shlex.quote(positional[index]) if index < len(positional) else "''"


def _fd_of(word: str | None) -> int | None:
    if word in STDIN_PATHS:
        return 0
    match = FD_PATH_RE.fullmatch(word or "")
    return int(match.group(1)) if match else None
