"""Because the commit gate scans the index before the command runs, content staged or read from the worktree by that same command escapes the scan."""
from __future__ import annotations

from .commit_command import SHELL_ALIAS, GitCall

INDEX_WRITERS = frozenset({
    "add", "am", "apply", "checkout", "cherry-pick", "merge", "mv", "pull", "read-tree",
    "rebase", "reset", "restore", "revert", "rm", "stage", "stash", "update-index",
    # Because a shell alias can run any staging command, it counts as one.
    SHELL_ALIAS,
})
WORKTREE_LONG_OPTIONS = frozenset({
    "--all", "--include", "--interactive", "--only", "--patch", "--pathspec-from-file",
})
VALUE_LONG_OPTIONS = frozenset({
    "--author", "--cleanup", "--date", "--file", "--fixup", "--message", "--reedit-message",
    "--reuse-message", "--squash", "--template", "--trailer",
})
WORKTREE_SHORT_FLAGS = frozenset("aiop")
VALUE_SHORT_FLAGS = frozenset("CFcmt")
ATTACHED_VALUE_SHORT_FLAGS = frozenset("Su")


def takes_content_outside_index(calls: list[GitCall]) -> bool:
    staged_earlier = False
    for call in calls:
        if call.verb == "commit" and (staged_earlier or _commit_reads_worktree(call.args)):
            return True
        staged_earlier = staged_earlier or call.verb in INDEX_WRITERS
    return False


def _commit_reads_worktree(args: list[str]) -> bool:
    cursor = 0
    while cursor < len(args):
        token = args[cursor]
        if token == "--":
            return cursor + 1 < len(args)
        if not token.startswith("-") or token == "-":
            return True
        reads, takes_next = _long_option(token) if token.startswith("--") else _short_bundle(token[1:])
        if reads:
            return True
        cursor += 2 if takes_next else 1
    return False


def _long_option(token: str) -> tuple[bool, bool]:
    """Matched by prefix, because git accepts any unambiguous prefix, so --al means --all."""
    name, separator, _value = token.partition("=")
    if any(option.startswith(name) for option in WORKTREE_LONG_OPTIONS):
        return True, False
    return False, not separator and any(option.startswith(name) for option in VALUE_LONG_OPTIONS)


def _short_bundle(flags: str) -> tuple[bool, bool]:
    for index, flag in enumerate(flags):
        if flag in WORKTREE_SHORT_FLAGS:
            return True, False
        if flag in ATTACHED_VALUE_SHORT_FLAGS:
            return False, False
        if flag in VALUE_SHORT_FLAGS:
            return False, index == len(flags) - 1
    return False, False
