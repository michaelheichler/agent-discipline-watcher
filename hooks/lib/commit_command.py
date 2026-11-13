"""Because a commit can hide behind a newline, a wrapper, a shell payload, a script, or an alias, the gate reads a command the way bash and git would."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field, replace
from itertools import takewhile
from pathlib import Path
from typing import NamedTuple

from .commit_functions import Function, extract_functions, with_positional
from .commit_inputs import (
    PLAIN_COMMIT, SCRIPT_READERS, Command, Input, InputScope, UnreadableCommit, is_dynamic, normalized, shell_input,
)
from .commit_segments import (
    alias_definitions as _alias_definitions, bind_input as _bind_input, command_words as _command_words,
    is_assignment as _is_assignment, segments as _segments,
)
from .commit_writes import changes_files as _changes_files
from .path_policy import anchored
from .shell_operators import SEPARATORS
from .shell_syntax import WRAPPER_COMMANDS, _basename, _payload_command_index
from .shell_text import heredoc_value, split_redirects

__all__ = ["GitCall", "UnreadableCommit", "git_calls", "SHELL_ALIAS"]

GIT_TIMEOUT_SECONDS = 30
MAX_NESTING = 6
MAX_ALIAS_DEPTH = 8
MAX_FUNCTION_DEPTH = 32
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
BUILTIN_VERBS = frozenset("""
    add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore checkout cherry
    cherry-pick clean clone commit commit-tree config count-objects describe diff diff-files diff-index diff-tree
    difftool fetch for-each-ref format-patch fsck gc grep hash-object help init log ls-files ls-remote ls-tree
    maintenance merge merge-base mv notes prune pull push range-diff read-tree rebase reflog remote repack replace
    rerere reset restore rev-list rev-parse revert rm shortlog show show-ref sparse-checkout stage stash status
    submodule switch symbolic-ref tag update-index update-ref var version whatchanged worktree write-tree
""".split())
VARIABLE_RE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")

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
    stdin: str | None = None


def git_calls(command: str | list[str], cwd: Path) -> list[GitCall]:
    return _calls(command, _Walk(cwd, 0, set()))


def _calls(command: str | list[str], walk: _Walk) -> list[GitCall]:
    if walk.depth > MAX_NESTING:
        raise UnreadableCommit(TOO_DEEP)
    if isinstance(command, str):
        command, walk.declarations = extract_functions(command)
    for segment in _segments(command):
        walk.step(segment)
    return walk.calls


@dataclass(slots=True)
class _Walk:
    """Because cd, a subshell, a redirect, a variable, an alias, a pipe, and an earlier write change what a later command does, the walk carries them."""

    cwd: Path
    depth: int
    touched: set[str]
    groups: list[_Walk] = field(default_factory=list)
    pushed: list[Path] = field(default_factory=list)
    calls: list[GitCall] = field(default_factory=list)
    previous: Command | None = None
    feed: Command | None = None
    fds: dict[int, Input] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    functions: dict[str, Function] = field(default_factory=dict)
    exported_functions: set[str] = field(default_factory=set)
    ambiguous_functions: set[str] = field(default_factory=set)
    declarations: dict[str, Function] = field(default_factory=dict)
    function_stack: tuple[str, ...] = ()
    local_variables: set[str] = field(default_factory=set)
    relocated: bool = False
    commit_variable: bool = False
    inspected_command: bool = False

    def step(self, segment: list[str]) -> None:
        if segment in (["("], [")"]):
            self._group(segment[0])
            return
        if len(segment) == 1 and segment[0] in SEPARATORS:
            self.feed = self.previous if segment[0] in PIPES else None
            return
        if not segment:
            return
        self.inspected_command = False
        command, declaration = self._read(segment)
        if declaration is not None:
            previous = self.functions.get(declaration.name)
            if previous is not None and previous.body != declaration.body:
                self.ambiguous_functions.add(declaration.name)
            self.functions[declaration.name] = declaration
        else:
            self._command(command)
        self._note_writes(command, declaration is not None)
        self.previous, self.feed = command, None

    def _group(self, token: str) -> None:
        if token == "(":
            snapshot = self.nested()
            snapshot.local_variables = set(self.local_variables)
            snapshot.fds = dict(self.fds)
            self.groups.append(snapshot)
            return
        if not self.groups:
            return
        snapshot = self.groups.pop()
        self.cwd, self.variables = snapshot.cwd, snapshot.variables
        self.functions, self.aliases = snapshot.functions, snapshot.aliases
        self.exported_functions = snapshot.exported_functions
        self.ambiguous_functions = snapshot.ambiguous_functions
        self.local_variables, self.fds = snapshot.local_variables, snapshot.fds
        self.relocated, self.commit_variable = snapshot.relocated, snapshot.commit_variable

    def _read(self, segment: list[str]) -> tuple[Command, Function | None]:
        words, redirects = split_redirects(_command_words(segment))
        index = _payload_command_index(words)
        declaration = self.declarations.get(words[index]) if index < len(words) else None
        inputs = dict(self.fds)
        for redirect in redirects:
            _bind_input(inputs, redirect._replace(target=_expanded(redirect.target, self.variables)))
        outputs = [_expanded(redirect.target, self.variables) for redirect in redirects if redirect.operator in OUTPUT_OPERATORS]
        return Command(_expanded_words(words, self.variables), inputs, outputs), declaration

    def _command(self, command: Command) -> None:
        words = command.words
        index = _payload_command_index(words)
        verb = words[index] if index < len(words) else ""
        if verb in self.aliases:
            self._expand_alias(verb, words[index + 1:])
            self.inspected_command = True
            return
        if verb in self.functions and all(_is_assignment(word) for word in words[:index]):
            self._invoke_function(verb, command)
            self.inspected_command = True
            return
        if verb in DIRECTORY_VERBS:
            self._change_directory(verb, words[index + 1:])
            return
        if verb == "alias":
            self.aliases.update(_alias_definitions(words[index + 1:]))
            return
        if words == ["exec"]:
            self.fds = command.inputs
            return
        self._run(command)

    def _run(self, command: Command) -> None:
        self._export_functions(command.words)
        assigned = _assignments(command.words)
        self.variables.update(assigned)
        if command.words[:1] == ["local"]:
            self.local_variables.update(word.partition("=")[0] for word in command.words[1:])
        self.relocated = self.relocated or any(name in GIT_LOCATION_ENV_VARS for name, _value in assigned)
        self.commit_variable = self.commit_variable or any("commit" in value for _name, value in assigned)
        found = _segment_calls(command, self)
        if self.relocated and any(call.verb == "commit" for call in found):
            raise UnreadableCommit(LOCATION_OVERRIDE)
        self.calls.extend(found)

    def _note_writes(self, command: Command, declaration: bool = False) -> None:
        """Because a script read before the command runs is stale once an earlier step rewrites it, every path a writing step names is kept."""
        written = [*command.outputs]
        if not self.inspected_command and not declaration and _changes_files(command.words):
            written.extend(word for word in command.words if not word.startswith("-"))
        self.touched.update(normalized(self.cwd, word) for word in written if word)

    def nested(self, shell_depth: int = 0) -> _Walk:
        return _Walk(
            self.cwd, self.depth + shell_depth, self.touched,
            variables=dict(self.variables), aliases=dict(self.aliases), functions=dict(self.functions),
            exported_functions=set(self.exported_functions), ambiguous_functions=set(self.ambiguous_functions),
            function_stack=self.function_stack, relocated=self.relocated, commit_variable=self.commit_variable,
        )

    def absorb(self, child: _Walk, function: bool = False) -> None:
        self.cwd = child.cwd
        self.functions = child.functions
        self.aliases = child.aliases
        self.exported_functions = child.exported_functions
        self.ambiguous_functions = child.ambiguous_functions
        self.variables.update((name, value) for name, value in child.variables.items()
                              if not function or name not in child.local_variables)
        if not function:
            self.local_variables.update(child.local_variables)
        self.relocated = self.relocated or child.relocated
        self.commit_variable = self.commit_variable or child.commit_variable

    def shell_child(self, shared: bool) -> _Walk:
        child = self.nested(shell_depth=1)
        if not shared:
            child.variables = {}
            child.aliases = {}
            child.functions = {name: function for name, function in self.functions.items() if name in self.exported_functions}
        return child

    def _export_functions(self, words: list[str]) -> None:
        if not words or words[0] not in {"export", "declare", "typeset"}:
            return
        flags = list(takewhile(lambda word: word.startswith("-"), words[1:]))
        exporting = words[0] == "export" or any("x" in flag for flag in flags)
        if not exporting or not any("f" in flag for flag in flags):
            return
        names = words[len(flags) + 1:]
        if any("n" in flag for flag in flags):
            self.exported_functions.difference_update(names)
            return
        self.exported_functions.update(name for name in names if name in self.functions)

    def _invoke_function(self, verb: str, command: Command) -> None:
        if verb in self.ambiguous_functions:
            raise UnreadableCommit(f"This function has different readable definitions, so the commit gate cannot resolve its call. {PLAIN_COMMIT}")
        if verb in self.function_stack or len(self.function_stack) >= MAX_FUNCTION_DEPTH:
            raise UnreadableCommit(TOO_DEEP)
        child = self.nested()
        child.function_stack = (*self.function_stack, verb)
        child.fds = command.inputs
        args = command.words[_payload_command_index(command.words) + 1:]
        found = _calls(with_positional(self.functions[verb].body, args), child)
        if any(call.verb == "commit" for call in found):
            _refuse_location_override(command.words[:_payload_command_index(command.words)])
        self.calls.extend(found)
        self.absorb(child, function=True)

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
        self.cwd = anchored(args[-1], self.cwd) if args else self.cwd


def _segment_calls(command: Command, walk: _Walk) -> list[GitCall]:
    words = command.words
    payload = shell_input(command, InputScope(walk.cwd, walk.feed, walk.touched))
    if payload is not None:
        return _shell_calls(payload, command, walk)
    call = _git_call(words, walk.cwd)
    if call is None:
        _refuse_hidden_commit(words, walk.commit_variable)
        return []
    nested = (found for payload in _git_payloads(call) for found in _calls(payload, walk.nested(shell_depth=1)))
    if any(found.verb == "commit" for found in nested):
        raise UnreadableCommit(HIDDEN_COMMIT)
    source = command.inputs.get(0)
    return [call._replace(stdin=source.text if source is not None else None)]


def _shell_calls(payload: str, command: Command, walk: _Walk) -> list[GitCall]:
    walk.inspected_command = True
    if walk.commit_variable and is_dynamic(next(iter(payload.split()), "")):
        raise UnreadableCommit(DYNAMIC_PROGRAM)
    words = command.words
    index = _payload_command_index(words)
    shared = index < len(words) and words[index] in {*SCRIPT_READERS, "eval", "trap"}
    child = walk.shell_child(shared)
    found = _calls(payload, child)
    if shared and words[index] != "trap":
        walk.absorb(child)
    commits = any(call.verb == "commit" for call in found)
    if commits and words[index] == "trap":
        raise UnreadableCommit(HIDDEN_COMMIT)
    if commits:
        _refuse_location_override(words[:index])
    return found


def _expanded(word: str, variables: dict[str, str]) -> str:
    """A $(cat <<EOF) word becomes its body, because that is the text bash hands the command."""
    heredoc = heredoc_value(word)
    if heredoc is not None:
        return heredoc
    return VARIABLE_RE.sub(lambda match: variables.get(match.group(1) or match.group(2), match.group()), word)


def _expanded_words(words: list[str], variables: dict[str, str]) -> list[str]:
    """Split only in command position, because bash word-splits an unquoted $cmd while a quoted message stays whole."""
    expanded = [_expanded(word, variables) for word in words]
    index = _payload_command_index(expanded)
    if index < len(expanded) and expanded[index] != words[index] and " " in expanded[index]:
        return [*expanded[:index], *expanded[index].split(), *expanded[index + 1:]]
    return expanded


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


@dataclass(frozen=True, slots=True)
class _GitContext:
    cwd: Path
    prefix: list[str]
    depth: int = 0


def _git_call(words: list[str], cwd: Path) -> GitCall | None:
    index = _payload_command_index(words)
    if index >= len(words) or _basename(words[index]) != "git":
        return None
    prefix = words[:index]
    call = _resolved(words[index:], _GitContext(cwd, prefix))
    if call is not None and call.verb == "commit":
        _refuse_location_override(prefix)
    return call


def _resolved(git_words: list[str], context: _GitContext) -> GitCall | None:
    located = _located_verb(git_words, context.cwd)
    if located is None:
        return None
    location, cursor = located
    verb, args, flags = git_words[cursor], git_words[cursor + 1:], git_words[1:cursor]
    if is_dynamic(verb):
        raise UnreadableCommit(DYNAMIC_PROGRAM)
    alias = None if verb in BUILTIN_VERBS else _alias(verb, flags, context)
    if alias is None:
        return GitCall(location, verb, args)
    if alias.startswith("!"):
        return GitCall(location, _shell_alias(verb, alias), args)
    if context.depth >= MAX_ALIAS_DEPTH:
        raise UnreadableCommit(f"git {verb} expands through more aliases than the commit gate follows. {PLAIN_COMMIT}")
    return _resolved(["git", *flags, *_alias_words(verb, alias), *args], replace(context, depth=context.depth + 1))


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
        return cursor + 1, anchored(token[2:], current), False
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
    resolved = anchored(value, current)
    if flag == "--git-dir" and resolved.name == ".git":
        return resolved.parent
    return resolved


def _alias(verb: str, flags: list[str], context: _GitContext) -> str | None:
    """Asked with the call's own flags and environment, because -c, --config-env, and GIT_CONFIG_* can define the alias."""
    try:
        done = subprocess.run(
            ["git", *flags, "config", "--get", f"alias.{verb}"], cwd=context.cwd, env=_alias_env(verb, context.prefix),
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


def _refuse_hidden_commit(words: list[str], commit_variable: bool) -> None:
    names = [_basename(word) for word in words[_payload_command_index(words):]]
    if not names:
        return
    if is_dynamic(names[0]) and ("commit" in names or commit_variable):
        raise UnreadableCommit(DYNAMIC_PROGRAM)
    programs = [index for index, name in enumerate(names) if name == "git" or is_dynamic(name)]
    if names[0] in COMMAND_RUNNERS and programs and "commit" in names[programs[0]:]:
        raise UnreadableCommit(HIDDEN_COMMIT)
