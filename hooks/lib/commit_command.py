"""Because a commit can hide behind a newline, a wrapper, a shell payload, a script, or an alias, the gate reads a command the way bash and git would."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from .commit_inputs import (
    PLAIN_COMMIT, Command, Input, InputScope, UnreadableCommit, is_dynamic, normalized, resolve_cwd, shell_input,
)
from .shell_operators import SEPARATORS
from .shell_syntax import WRAPPER_COMMANDS, _basename, _payload_command_index
from .shell_text import INLINE_INPUT, Redirect, shell_text, split_redirects

__all__ = ["GitCall", "UnreadableCommit", "git_calls", "SHELL_ALIAS"]

GIT_TIMEOUT_SECONDS = 30
MAX_NESTING = 6
MAX_ALIAS_DEPTH = 8
SHELL_ALIAS = "!"
PIPES = frozenset({"|", "|&"})
DIRECTORY_VERBS = frozenset({"cd", "pushd", "popd"})
OUTPUT_OPERATORS = frozenset({">", ">>", ">|", "<>"})
GIT_VALUE_FLAGS = frozenset({"-c", "--namespace", "--config-env"})
PATH_FLAGS = frozenset({"-C", "--work-tree", "--git-dir"})
GIT_LOCATION_ENV_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"})
DECLARERS = frozenset({"export", "declare", "typeset", "local", "readonly"})
CONFIG_ENV_PREFIXES = ("GIT_", "HOME", "XDG_CONFIG_HOME")
CHDIR_FLAGS = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir")}
COMMAND_RUNNERS = frozenset({
    "caffeinate", "doas", "find", "flock", "ionice", "parallel", "setsid", "stdbuf", "unbuffer", "watch", "xargs",
})
READ_ONLY_COMMANDS = frozenset({
    "[", "basename", "cat", "cd", "cmp", "cut", "date", "dirname", "echo", "false", "file", "grep", "head", "ls",
    "popd", "printf", "pushd", "pwd", "readlink", "realpath", "rg", "sleep", "sort", "stat", "tail", "test", "tr",
    "true", "type", "uniq", "wc", "which",
})
WORKTREE_SAFE_GIT = frozenset({
    "add", "blame", "branch", "commit", "config", "describe", "diff", "fetch", "grep", "log", "ls-files", "push",
    "reflog", "remote", "rev-parse", "shortlog", "show", "stage", "status", "tag",
})
RESERVED_WORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "do", "while", "until", "coproc"})
BUILTIN_VERBS = frozenset("""
    add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore checkout cherry
    cherry-pick clean clone commit commit-tree config count-objects describe diff diff-files diff-index diff-tree
    difftool fetch for-each-ref format-patch fsck gc grep hash-object help init log ls-files ls-remote ls-tree
    maintenance merge merge-base mv notes prune pull push range-diff read-tree rebase reflog remote repack replace
    rerere reset restore rev-list rev-parse revert rm shortlog show show-ref sparse-checkout stage stash status
    submodule switch symbolic-ref tag update-index update-ref var version whatchanged worktree write-tree
""".split())
PUNCTUATION_RUN_RE = re.compile(r"[;&|()\n]+")
SHELL_OPERATOR_RE = re.compile(r"&&|\|\||\|&|[;&|()]|\n")
VARIABLE_RE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
CAT_HEREDOC_RE = re.compile(r"\$\(\s*cat\s*<<-?\s*(['\"]?)([^\s'\"()]+)\1[ \t]*\n(?P<body>.*?)\n?\2[ \t]*\n\s*\)", re.DOTALL)

UNREADABLE_QUOTING = f"The commit gate cannot read the quoting in this command, so it cannot see what the commit records. {PLAIN_COMMIT}"
TOO_DEEP = f"This command nests shells or scripts deeper than the commit gate reads. {PLAIN_COMMIT}"
HIDDEN_COMMIT = f"This command runs git commit through another program, so the commit gate cannot scan it. {PLAIN_COMMIT}"
DYNAMIC_PROGRAM = f"This command takes its program or git subcommand from a variable or substitution, so the commit gate cannot see whether it commits. {PLAIN_COMMIT}"
LOCATION_OVERRIDE = (
    "GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, or another git location variable moves the commit's repository or index, "
    "so the commit gate cannot tell which index it records. Commit without them."
)
DIRECTORY_MOVE = "env -C or sudo -D moves the commit into another directory. Run cd in its own step, then commit."


class GitCall(NamedTuple):
    cwd: Path
    verb: str
    args: list[str]


def git_calls(command: str | list[str], cwd: Path) -> list[GitCall]:
    return _calls(command, cwd, 0, set())


def _calls(command: str | list[str], cwd: Path, depth: int, touched: set[str]) -> list[GitCall]:
    if depth > MAX_NESTING:
        raise UnreadableCommit(TOO_DEEP)
    walk = _Walk(cwd, depth, touched)
    for segment in _segments(command):
        walk.step(segment)
    return walk.calls


@dataclass(slots=True)
class _Walk:
    """Because cd, a subshell, a redirect, a variable, an alias, a pipe, and an earlier write change what a later command does, the walk carries them."""

    cwd: Path
    depth: int
    touched: set[str]
    groups: list[Path] = field(default_factory=list)
    pushed: list[Path] = field(default_factory=list)
    calls: list[GitCall] = field(default_factory=list)
    previous: Command | None = None
    feed: Command | None = None
    fds: dict[int, Input] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    relocated: bool = False
    commit_variable: bool = False

    def step(self, segment: list[str]) -> None:
        if segment in (["("], [")"]):
            self._group(segment[0])
            return
        if len(segment) == 1 and segment[0] in SEPARATORS:
            self.feed = self.previous if segment[0] in PIPES else None
            return
        if segment:
            command = self._read(segment)
            self._command(command)
            self._note_writes(command)
            self.previous, self.feed = command, None

    def _group(self, token: str) -> None:
        if token == "(":
            self.groups.append(self.cwd)
            return
        self.cwd = self.groups.pop() if self.groups else self.cwd

    def _read(self, segment: list[str]) -> Command:
        words, redirects = split_redirects(_command_words(segment))
        inputs = dict(self.fds)
        for redirect in redirects:
            _bind_input(inputs, redirect._replace(target=_expanded(redirect.target, self.variables)))
        outputs = [_expanded(redirect.target, self.variables) for redirect in redirects if redirect.operator in OUTPUT_OPERATORS]
        return Command(_expanded_words(words, self.variables), inputs, outputs)

    def _command(self, command: Command) -> None:
        words = command.words
        index = _payload_command_index(words)
        verb = words[index] if index < len(words) else ""
        if verb in DIRECTORY_VERBS:
            self._change_directory(verb, words[index + 1:])
            return
        if verb == "alias":
            self.aliases.update(_alias_definitions(words[index + 1:]))
            return
        if verb in self.aliases:
            self._expand_alias(verb, words[index + 1:])
            return
        if words == ["exec"]:
            self.fds = command.inputs
            return
        self._run(command)

    def _run(self, command: Command) -> None:
        assigned = _assignments(command.words)
        self.variables.update(assigned)
        self.relocated = self.relocated or any(name in GIT_LOCATION_ENV_VARS for name, _value in assigned)
        self.commit_variable = self.commit_variable or any("commit" in value for _name, value in assigned)
        found = _segment_calls(command, self)
        if self.relocated and any(call.verb == "commit" for call in found):
            raise UnreadableCommit(LOCATION_OVERRIDE)
        self.calls.extend(found)

    def _note_writes(self, command: Command) -> None:
        """Because a script read before the command runs is stale once an earlier step rewrites it, every path a writing step names is kept."""
        written = [*command.outputs]
        if _changes_files(command.words):
            written.extend(word for word in command.words if not word.startswith("-"))
        self.touched.update(normalized(self.cwd, word) for word in written)

    def _expand_alias(self, verb: str, args: list[str]) -> None:
        """Popped while it expands, because bash never expands an alias inside its own text."""
        value = self.aliases.pop(verb)
        try:
            for segment in _segments(f"{value} {shlex.join(args)}"):
                self.step(segment)
        finally:
            self.aliases[verb] = value

    def _change_directory(self, verb: str, args: list[str]) -> None:
        if verb == "popd":
            self.cwd = self.pushed.pop() if self.pushed else self.cwd
            return
        if verb == "pushd":
            self.pushed.append(self.cwd)
        self.cwd = resolve_cwd(self.cwd, args[-1]) if args else self.cwd


def _segment_calls(command: Command, walk: _Walk) -> list[GitCall]:
    words = command.words
    payload = shell_input(command, InputScope(walk.cwd, walk.feed, walk.touched))
    if payload is not None:
        if walk.commit_variable and is_dynamic(next(iter(payload.split()), "")):
            raise UnreadableCommit(DYNAMIC_PROGRAM)
        found = _calls(payload, walk.cwd, walk.depth + 1, walk.touched)
        if any(call.verb == "commit" for call in found):
            _refuse_location_override(words[:_payload_command_index(words)])
        return found
    call = _git_call(words, walk.cwd)
    if call is None:
        _refuse_hidden_commit(words, walk.commit_variable)
        return []
    nested = (found for payload in _git_payloads(call) for found in _calls(payload, walk.cwd, walk.depth + 1, walk.touched))
    if any(found.verb == "commit" for found in nested):
        raise UnreadableCommit(HIDDEN_COMMIT)
    return [call]


def _command_words(segment: list[str]) -> list[str]:
    index = 0
    while index < len(segment) and (segment[index] in RESERVED_WORDS or segment[index] == "function"):
        index += 2 if segment[index] == "function" else 1
    return segment[index:]


def _bind_input(inputs: dict[int, Input], redirect: Redirect) -> None:
    if redirect.operator in {"<", "<>"}:
        inputs[redirect.fd] = Input(path=redirect.target)
        return
    if redirect.operator == INLINE_INPUT:
        inputs[redirect.fd] = Input(text=redirect.target)
        return
    if redirect.operator == "<&" and redirect.target.isdigit() and int(redirect.target) in inputs:
        inputs[redirect.fd] = inputs[int(redirect.target)]


def _expanded(word: str, variables: dict[str, str]) -> str:
    """A $(cat <<EOF) word becomes its body, because that is the text bash hands the command."""
    heredoc = CAT_HEREDOC_RE.fullmatch(word)
    if heredoc:
        return heredoc.group("body")
    return VARIABLE_RE.sub(lambda match: variables.get(match.group(1) or match.group(2), match.group()), word)


def _expanded_words(words: list[str], variables: dict[str, str]) -> list[str]:
    """Split only in command position, because bash word-splits an unquoted $cmd while a quoted message stays whole."""
    expanded = [_expanded(word, variables) for word in words]
    index = _payload_command_index(expanded)
    if index < len(expanded) and expanded[index] != words[index] and " " in expanded[index]:
        return [*expanded[:index], *expanded[index].split(), *expanded[index + 1:]]
    return expanded


def _changes_files(words: list[str]) -> bool:
    index = _payload_command_index(words)
    if index >= len(words):
        return False
    name = _basename(words[index])
    if name == "git":
        return next((word for word in words[index + 1:] if not word.startswith("-")), "") not in WORKTREE_SAFE_GIT
    return name not in READ_ONLY_COMMANDS


def _git_payloads(call: GitCall) -> list[str]:
    """Because git runs these commands itself, once per commit or submodule, a commit inside them has no single index."""
    if call.verb == "rebase":
        return [value for index, arg in enumerate(call.args) if (value := _exec_value(call.args, index, arg)) is not None]
    runner = {"submodule": "foreach", "bisect": "run"}.get(call.verb)
    if runner not in call.args:
        return []
    return [" ".join(arg for arg in call.args[call.args.index(runner) + 1:] if not arg.startswith("-"))]


def _exec_value(args: list[str], index: int, arg: str) -> str | None:
    name, separator, inline = arg.partition("=")
    if separator and len(name) > 3 and "--exec".startswith(name):
        return inline
    if arg == "-x" or (len(arg) > 3 and "--exec".startswith(arg)):
        return args[index + 1] if index + 1 < len(args) else ""
    return arg[2:] if arg.startswith("-x") and len(arg) > 2 else None


def _git_call(words: list[str], cwd: Path) -> GitCall | None:
    index = _payload_command_index(words)
    if index >= len(words) or _basename(words[index]) != "git":
        return None
    prefix = words[:index]
    call = _resolved(words[index:], cwd, prefix, 0)
    if call is not None and call.verb == "commit":
        _refuse_location_override(prefix)
    return call


def _resolved(git_words: list[str], cwd: Path, prefix: list[str], depth: int) -> GitCall | None:
    located = _located_verb(git_words, cwd)
    if located is None:
        return None
    location, cursor = located
    verb, args, flags = git_words[cursor], git_words[cursor + 1:], git_words[1:cursor]
    if is_dynamic(verb):
        raise UnreadableCommit(DYNAMIC_PROGRAM)
    alias = None if verb in BUILTIN_VERBS else _alias(verb, flags, cwd, prefix)
    if alias is None:
        return GitCall(location, verb, args)
    if alias.startswith("!"):
        return GitCall(location, _shell_alias(verb, alias), args)
    if depth >= MAX_ALIAS_DEPTH:
        raise UnreadableCommit(f"git {verb} expands through more aliases than the commit gate follows. {PLAIN_COMMIT}")
    return _resolved(["git", *flags, *_alias_words(verb, alias), *args], cwd, prefix, depth + 1)


def _located_verb(git_words: list[str], cwd: Path) -> tuple[Path, int] | None:
    current, pinned, cursor = cwd, False, 1
    while cursor < len(git_words) and git_words[cursor].startswith("-"):
        step = _skip_git_flag(git_words, cursor, current)
        if step is None:
            return None
        cursor, candidate, pins = step
        current = candidate if pins or not pinned else current
        pinned = pinned or pins
    return (current, cursor) if cursor < len(git_words) else None


def _skip_git_flag(words: list[str], cursor: int, current: Path) -> tuple[int, Path, bool] | None:
    token = words[cursor]
    if token.startswith("-C") and len(token) > 2:
        return cursor + 1, resolve_cwd(current, token[2:]), False
    name, separator, inline = token.partition("=")
    if separator and name in PATH_FLAGS:
        return cursor + 1, _flag_cwd(name, current, inline), name == "--work-tree"
    if token in PATH_FLAGS:
        if cursor + 1 >= len(words):
            return None
        return cursor + 2, _flag_cwd(token, current, words[cursor + 1]), token == "--work-tree"
    if token in GIT_VALUE_FLAGS:
        return cursor + 2, current, False
    return cursor + 1, current, False


def _flag_cwd(flag: str, current: Path, value: str) -> Path:
    resolved = resolve_cwd(current, value)
    if flag == "--git-dir" and resolved.name == ".git":
        return resolved.parent
    return resolved


def _alias(verb: str, flags: list[str], cwd: Path, prefix: list[str]) -> str | None:
    """Asked with the call's own flags and environment, because -c, --config-env, and GIT_CONFIG_* can define the alias."""
    try:
        done = subprocess.run(
            ["git", *flags, "config", "--get", f"alias.{verb}"], cwd=cwd, env=_alias_env(verb, prefix),
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UnreadableCommit(f"The commit gate could not check whether git {verb} is an alias: {exc}. {PLAIN_COMMIT}") from exc
    return done.stdout.strip() if done.returncode == 0 else None


def _alias_env(verb: str, prefix: list[str]) -> dict[str, str]:
    assigned = dict(token.split("=", 1) for token in prefix if _is_assignment(token))
    if any(name.startswith(CONFIG_ENV_PREFIXES) and is_dynamic(value) for name, value in assigned.items()):
        raise UnreadableCommit(f"This command sets git configuration from a shell variable, so the commit gate cannot resolve git {verb}. {PLAIN_COMMIT}")
    return {**os.environ, **assigned}


def _shell_alias(verb: str, alias: str) -> str:
    if "commit" in alias:
        raise UnreadableCommit(f"git {verb} is a shell alias that runs commit, so the commit gate cannot read it. {PLAIN_COMMIT}")
    return SHELL_ALIAS


def _alias_words(verb: str, alias: str) -> list[str]:
    try:
        return shlex.split(alias)
    except ValueError as exc:
        raise UnreadableCommit(f"The commit gate cannot read the quoting of the git {verb} alias. {PLAIN_COMMIT}") from exc


def _refuse_location_override(prefix: list[str]) -> None:
    if any(token.partition("=")[0] in GIT_LOCATION_ENV_VARS for token in prefix if _is_assignment(token)):
        raise UnreadableCommit(LOCATION_OVERRIDE)
    if _moves_directory(prefix):
        raise UnreadableCommit(DIRECTORY_MOVE)


def _moves_directory(prefix: list[str]) -> bool:
    wrapper = ""
    for token in prefix:
        wrapper = _basename(token) if _basename(token) in WRAPPER_COMMANDS else wrapper
        if token.startswith(CHDIR_FLAGS.get(wrapper, ())):
            return True
    return False


def _assignments(words: list[str]) -> list[tuple[str, str]]:
    """Counted on a plain or declared assignment, because either can hand a later command its program or location."""
    if words[:1] and words[0] in DECLARERS:
        declared = words[1:]
    elif words and all(_is_assignment(word) for word in words):
        declared = words
    else:
        return []
    return [(name, value) for name, separator, value in (word.partition("=") for word in declared) if separator]


def _alias_definitions(args: list[str]) -> dict[str, str]:
    return {name: value for name, separator, value in (arg.partition("=") for arg in args) if separator}


def _refuse_hidden_commit(words: list[str], commit_variable: bool) -> None:
    names = [_basename(word) for word in words[_payload_command_index(words):]]
    if not names:
        return
    if is_dynamic(names[0]) and ("commit" in names or commit_variable):
        raise UnreadableCommit(DYNAMIC_PROGRAM)
    programs = [index for index, name in enumerate(names) if name == "git" or is_dynamic(name)]
    if names[0] in COMMAND_RUNNERS and programs and "commit" in names[programs[0]:]:
        raise UnreadableCommit(HIDDEN_COMMIT)


def _is_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator and name and name.isidentifier())


def _segments(command: str | list[str]) -> list[list[str]]:
    if isinstance(command, list):
        return _split_segments(command)
    text = shell_text(command)
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, ""
        tokens = [operator for token in lexer for operator in _operators(token)]
    except ValueError:
        if "commit" in text:
            raise UnreadableCommit(UNREADABLE_QUOTING) from None
        return []
    return _split_segments(tokens)


def _operators(token: str) -> list[str]:
    """Split, because shlex returns a run such as ); or )&& as one token, and a newline ends a command like ; does."""
    if not PUNCTUATION_RUN_RE.fullmatch(token):
        return [token]
    return [";" if operator == "\n" else operator for operator in SHELL_OPERATOR_RE.findall(token)]


def _split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            segments.extend([current, [token]])
            current = []
            continue
        current.append(token)
    segments.append(current)
    return segments
