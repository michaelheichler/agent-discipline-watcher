"""Because a later script read can go stale, separate filesystem writers from shell reads."""
from __future__ import annotations

from itertools import takewhile

from .commit_inputs import SCRIPT_READERS
from .shell_syntax import _basename, _payload_command_index

READ_ONLY_COMMANDS = frozenset({
    "[", "basename", "cat", "cd", "cmp", "cut", "date", "dirname", "echo", "false", "file", "grep", "head", "ls",
    "popd", "printf", "pushd", "pwd", "readlink", "realpath", "rg", "sleep", "sort", "stat", "tail", "test", "tr",
    "true", "type", "uniq", "wc", "which", ".", "source", "[[", "case", "esac", "fi", "done",
    "local", "declare", "typeset", "export", "readonly", "unset", "set", "shift", "return", "break", "continue", ":",
})
SYNTAX_CHECK_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
NODE_NAMES = frozenset({"node", "nodejs"})
NODE_CHECK_FLAGS = frozenset({"--check", "-c"})
WORKTREE_SAFE_GIT = frozenset({
    "blame", "branch", "commit", "config", "describe", "diff", "fetch", "grep", "log", "ls-files", "push",
    "reflog", "remote", "rev-parse", "shortlog", "show", "stage", "status", "tag",
})


def changes_files(words: list[str]) -> bool:
    index = _payload_command_index(words)
    if index >= len(words):
        return False
    name = words[index] if words[index] in SCRIPT_READERS else _basename(words[index])
    if name == "git":
        return next((word for word in words[index + 1:] if not word.startswith("-")), "") not in WORKTREE_SAFE_GIT
    return name not in READ_ONLY_COMMANDS and not _syntax_check(name, words[index + 1:])


def _syntax_check(name: str, args: list[str]) -> bool:
    options = list(takewhile(lambda arg: arg.startswith("-") and arg != "-", args))
    if name in SYNTAX_CHECK_SHELLS:
        return any(not option.startswith("--") and "n" in option[1:] for option in options)
    return name in NODE_NAMES and any(option in NODE_CHECK_FLAGS for option in options)
