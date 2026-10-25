"""Resolves which paths a shell segment actually writes, because treating every path token in a mutating segment as a target blocks reads the agent is entitled to."""
from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import NamedTuple

from lib.archive_commands import git_apply_read, patch_plan, stdin_source, tar_read, unzip_read
from lib.archive_members import ArchiveRead
from lib.flag_outputs import FLAG_WRITERS, flag_targets
from lib.inplace_targets import sed_reads_only, sed_script_known
from lib.shell_expansion import Expansions
from lib.shell_parse import _bare, _basename, _command_word_index, _expand_home, _is_file_target, _target_words
from lib.shell_syntax import _without_redirects
from lib.xargs_feed import CALLBACK_READERS, READER_HAZARDS

DESTINATION_LAST_ARG_VERBS = frozenset({"cp", "mv", "ln", "sed", "install", "rsync"})
DESTINATION_ALL_ARGS_VERBS = frozenset({"rm", "unlink", "shred", "truncate", "chmod", "chown", "touch", "sponge", "mkfifo"})
ARGUMENT_VERBS = DESTINATION_LAST_ARG_VERBS | DESTINATION_ALL_ARGS_VERBS | {"dd"}
TARGET_DIR_VERBS = frozenset({"cp", "mv", "ln", "install"})
XARGS_VALUE_FLAGS = frozenset({"-I", "-L", "-n", "-P", "-d", "-E", "-s", "-a"})
FIND_CALLBACKS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
FIND_FILE_OUTPUTS = frozenset({"-fprint", "-fprint0", "-fprintf", "-fls"})
RIPGREP_CONFIG = "RIPGREP_CONFIG_PATH"
FIND_CALL_ENDS = frozenset({";", "+"})
TARGET_DIR_FLAGS = frozenset({"-t", "--target-directory"})
TARGET_DIR_PREFIX = "--target-directory="
DD_OUTPUT_PREFIX = "of="
COPY_VERBS = frozenset({"cp", "mv", "ln", "install", "rsync"})
GIT_PATH_COMMANDS = frozenset({"checkout", "restore", "rm"})
GIT_CHANGING_COMMANDS = GIT_PATH_COMMANDS | {"mv", "apply", "stash"}
GIT_VALUE_FLAGS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
GIT_BASE_FLAGS = frozenset({"-C", "--work-tree"})
WORK_TREE_PREFIX = "--work-tree="
GLOB_CHARS = frozenset("*?[")
PATHSPEC_FILE_FLAG = "--pathspec-from-file"
GIT_MERGE_FILE = "merge-file"
MERGE_PRINT_FLAGS = frozenset({"-p", "--stdout", "--object-id"})
MERGE_VALUE_FLAGS = frozenset({"-L"})
GIT_DRY_APPLY_FLAGS =frozenset({"--check", "--stat", "--numstat", "--summary"})
UNZIP_READ_FLAGS = frozenset({"-l", "-t", "-p", "-v", "-Z", "-z"})
UNZIP_READ_LETTERS = frozenset("ltpvZz")
TAR_EXTRACT_FLAGS = frozenset({"--extract", "--get"})
TAR_STDOUT_FLAG = "--to-stdout"
TAR_COMMAND_FLAG = "--to-command"
RESTORE_STAGED = frozenset({"--staged", "-S"})
RESTORE_WORKTREE = frozenset({"--worktree", "-W", "-SW", "-WS"})
RESTORE_PLAIN_FLAGS = frozenset({"--staged", "-S", "-q", "--quiet"})
SED_SCRIPT_TARGET = "sed script"
Slot = tuple[int, str]


class GitLookup(NamedTuple):
    """Strict when a failed lookup must close the gate, because git rm and folder pathspecs reach files no word names."""

    base: str
    pathspecs: tuple[str, ...]
    tree: str | None
    strict: bool


class GatedTargets(NamedTuple):
    """Unresolved, because a patch or archive names no paths."""

    paths: tuple[str, ...]
    unresolved: bool
    lookup: GitLookup | None = None
    indexable: bool = False
    archive: ArchiveRead | None = None


class _GitSource(NamedTuple):
    """Kept with the call, because git apply may read its patch from a stdin redirect."""

    plain_call: bool
    stdin: str | None


class _GitCall(NamedTuple):
    command: str
    base: str
    rest: list[str]
    indexable: bool


class TargetWords(NamedTuple):
    """Unknown raw words beside the paths, because the gate must name what it cannot resolve."""

    paths: list[str]
    unknown: list[str]


NO_TARGETS = GatedTargets((), False)
UNRESOLVED = GatedTargets((), True)


def writes_by_verb(segment: list[str]) -> bool:
    """The callback verb under xargs and find, because a fed one runs it on words the text holds."""
    index = _command_word_index(segment)
    verb = _basename(segment[index]) if index < len(segment) else ""
    args = [_bare(token) for token in _without_redirects(segment[index + 1:])]
    if verb == "find":
        return bool(_find_writes(args, READER_HAZARDS))
    if verb == "git":
        return _merged_file(segment[index + 1:]) is not None
    if verb == "sed":
        return not sed_reads_only(segment)
    if verb == "xargs":
        call = _xargs_call(args)
        verb = _basename(call[0]) if call else ""
    return verb in ARGUMENT_VERBS or verb in FLAG_WRITERS


def mutation_targets(segment: list[str], expansions: Expansions) -> list[str]:
    """Because a copy's source argument is not its destination, a protected path used as input must not block a read."""
    paths = [_expand_home(path) for path in _mutation_words(segment, expansions).paths if _is_file_target(path)]
    return paths + [alias for path in paths for alias in expansions.aliases(path)]


def unknown_targets(segment: list[str], expansions: Expansions) -> list[str]:
    """Because the shell fixes these destinations only at run time, each one is an unknown write."""
    return _mutation_words(segment, expansions).unknown


def _mutation_words(segment: list[str], expansions: Expansions) -> TargetWords:
    """Because an unproven argument may expand to an option such as -t that moves the write, each one counts."""
    found = [(word, expansions.path(word)) for word in _target_words(segment)]
    calls = expansions.calls(segment)
    for call in [segment] if calls is None else calls:
        found += _verb_words(call, expansions)
    tree = expansions.tree(segment)
    if tree is not None:
        found += [(path, path) for path in tree.named] + [(word, None) for word in tree.unknown]
    return TargetWords([path for _, path in found if path is not None], [word for word, path in found if path is None])


def _verb_words(segment: list[str], expansions: Expansions) -> list[tuple[str, str | None]]:
    index = _command_word_index(segment)
    verb = _basename(segment[index]) if index < len(segment) else ""
    if verb in FLAG_WRITERS and FLAG_WRITERS[verb].config_names & expansions.touched:
        return [(f"{verb} config", None)]
    if verb == "git":
        return _merge_words(segment[index + 1:], expansions)
    if verb in FLAG_WRITERS:
        flagged = flag_targets(verb, _without_redirects(segment[index + 1:]), expansions.path)
        return [(path, path) for path in flagged.paths] + [(word, None) for word in flagged.unknown]
    reading_sed = verb == "sed" and sed_reads_only(segment)
    args = _without_redirects(segment[index + 1:]) if verb in ARGUMENT_VERBS and not reading_sed else []
    words = [expansions.pattern(token) for token in args]
    found: list[tuple[str, str | None]] = [(token, None) for token, word in zip(args, words) if word is None]
    if verb == "sed" and not sed_script_known(segment):
        found.append((SED_SCRIPT_TARGET, None))
    for position, prefix in [] if None in words else _destination_slots(verb, words):
        value = words[position] if verb in DESTINATION_ALL_ARGS_VERBS else expansions.path(args[position])
        found.append((args[position], None if value is None else value[len(prefix):]))
    return found


def generated_paths(segment: list[str], expansions: Expansions) -> list[str]:
    """Because curl -o, sort -o, and git merge-file land files the post-run scan must read, the journal names them."""
    calls = expansions.calls(segment) or [segment]
    return [path for call in calls for path in _generated(call, expansions)]


def _generated(call: list[str], expansions: Expansions) -> list[str]:
    index = _command_word_index(call)
    verb = _basename(call[index]) if index < len(call) else ""
    if verb == "git":
        return [path for _, path in _merge_words(call[index + 1:], expansions) if path is not None]
    return flag_targets(verb, _without_redirects(call[index + 1:]), expansions.path).paths if verb in FLAG_WRITERS else []


def _merge_words(args: list[str], expansions: Expansions) -> list[tuple[str, str | None]]:
    merged = _merged_file(_without_redirects(args))
    if merged is None:
        return []
    unproven = [token for token in args if expansions.pattern(token) is None]
    if unproven:
        return [(token, None) for token in unproven]
    base, raw = merged
    path = expansions.path(raw)
    return [(raw, None if path is None else os.path.join(base, path))]


def _merged_file(args: list[str]) -> tuple[str, str] | None:
    """Because git merge-file writes its result into the first file unless -p prints it, that file is the target."""
    bare = [_bare(token) for token in args]
    base, position = _git_base(bare)
    if position >= len(bare) or bare[position] != GIT_MERGE_FILE or MERGE_PRINT_FLAGS.intersection(bare[position + 1:]):
        return None
    operands = _merge_operands(args[position + 1:])
    return (base, operands[0]) if operands else None


def _merge_operands(rest: list[str]) -> list[str]:
    operands: list[str] = []
    position = 0
    while position < len(rest):
        word = _bare(rest[position])
        if word == "--":
            return operands + rest[position + 1:]
        operands += [] if word.startswith("-") else [rest[position]]
        position += 2 if word in MERGE_VALUE_FLAGS else 1
    return operands


def callback_writes(segment: list[str], expansions: Expansions) -> list[str]:
    """Because xargs and find hand a callback paths the text never names, a writing callback leaves its targets unknown."""
    index = _command_word_index(segment)
    verb = _basename(segment[index]) if index < len(segment) else ""
    args = [_bare(token) for token in _without_redirects(segment[index + 1:])]
    hazards = {**READER_HAZARDS, "rg": None} if RIPGREP_CONFIG in expansions.touched else READER_HAZARDS
    calls = expansions.calls(segment)
    if calls is not None:
        readers = [[_bare(word) for word in call] for call in calls if _basename(_bare(call[0])) in CALLBACK_READERS]
        return [f"{verb} {call[0]}" for call in readers if not _reads_only(call, hazards, fed=False)]
    if verb == "xargs":
        call = _xargs_call(args)
        return [] if not call or _reads_only(call, hazards, fed=True) else [f"xargs {call[0]}"]
    return _find_writes(args, hazards) if verb == "find" else []


def _xargs_call(args: list[str]) -> list[str]:
    position = 0
    while position < len(args) and args[position].startswith("-"):
        position += 2 if args[position] in XARGS_VALUE_FLAGS else 1
    return args[position:]


def _find_writes(args: list[str], hazards: dict[str, tuple[str, ...] | None]) -> list[str]:
    writes = ["find -delete"] if "-delete" in args else []
    for position, word in enumerate(args[:-1]):
        call = args[position + 1:]
        call = call[:next((end for end, part in enumerate(call) if part in FIND_CALL_ENDS), len(call))]
        if word in FIND_CALLBACKS and not _reads_only(call, hazards, fed=False):
            writes.append(f"find {word} {args[position + 1]}")
        if word in FIND_FILE_OUTPUTS:
            writes.append(f"find {word} {args[position + 1]}")
    return writes


def _reads_only(call: list[str], hazards: dict[str, tuple[str, ...] | None], fed: bool) -> bool:
    """Because stdin can add flags to an xargs reader, one with a writing flag needs -- before them."""
    name = _basename(call[0])
    if name not in CALLBACK_READERS or name not in hazards:
        return name in CALLBACK_READERS
    flags = hazards[name]
    options = call[1:call.index("--")] if "--" in call else call[1:]
    flagged = flags is None or any(_flagged(word, flags) for word in options)
    return not flagged and (not fed or "--" in call)


def _flagged(word: str, flags: tuple[str, ...]) -> bool:
    if word.startswith("--"):
        return any(word == flag or word.startswith(flag + "=") for flag in flags if flag.startswith("--"))
    return word.startswith("-") and any(flag[1] in word[1:] for flag in flags if len(flag) == 2)


def _destination_slots(verb: str, words: list[str]) -> list[Slot]:
    """Indexes, because only the raw word shows whether a glob in it was quoted."""
    positional = [position for position, word in enumerate(words) if not word.startswith("-")]
    if verb == "dd":
        return [(position, DD_OUTPUT_PREFIX) for position in positional if words[position].startswith(DD_OUTPUT_PREFIX)]
    if verb in DESTINATION_ALL_ARGS_VERBS:
        return [(position, "") for position in positional]
    target = _target_slot(words) if verb in TARGET_DIR_VERBS else None
    if target is not None:
        return [target]
    return [(positional[-1], "")] if verb in DESTINATION_LAST_ARG_VERBS and positional else []


def _target_slot(words: list[str]) -> Slot | None:
    """Because -t/--target-directory names the real destination for GNU cp, mv, and ln, the last positional argument must defer to it."""
    for position, word in enumerate(words):
        if word.startswith(TARGET_DIR_PREFIX):
            return position, TARGET_DIR_PREFIX
        if word in TARGET_DIR_FLAGS and position + 1 < len(words):
            return position + 1, ""
    return None


def _target_directory(args: list[str]) -> str | None:
    """Raw tokens, because temp_copies reads a cp destination before any expansion."""
    for position, token in enumerate(args):
        bare = _bare(token)
        if bare.startswith(TARGET_DIR_PREFIX):
            return bare[len(TARGET_DIR_PREFIX):]
        if bare in TARGET_DIR_FLAGS and position + 1 < len(args):
            return _bare(args[position + 1])
    return None


def _drop_target_dir(args: list[str]) -> list[str]:
    kept = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        bare = _bare(token)
        if bare.startswith(TARGET_DIR_PREFIX):
            continue
        if bare in TARGET_DIR_FLAGS:
            skip_next = True
            continue
        kept.append(token)
    return kept


def gated_test_targets(segment: list[str], expansions: Expansions) -> GatedTargets:
    """Kept apart, because only the test gate judges these verbs."""
    calls = expansions.calls(segment)
    if calls is not None:
        gated = [gated_test_targets(call, expansions) for call in calls]
        return GatedTargets(tuple(path for targets in gated for path in targets.paths), any(targets.unresolved for targets in gated))
    index = _command_word_index(segment)
    verb = _basename(segment[index]) if index < len(segment) else ""
    if verb in COPY_VERBS or verb == "git":
        return _copy_or_git(segment, index, expansions)
    if verb in {"tar", "unzip"}:
        return _archive_targets(verb, segment[index + 1:])
    return _patch_targets(segment[index + 1:]) if verb == "patch" else NO_TARGETS


def _copy_or_git(segment: list[str], index: int, expansions: Expansions) -> GatedTargets:
    verb = _basename(segment[index])
    args = _without_redirects(segment[index + 1:])
    words = [expansions.pattern(token) for token in args]
    if None in words:
        return UNRESOLVED if verb in COPY_VERBS or _git_changes_paths(args, expansions) else NO_TARGETS
    if verb == "git":
        return _git_targets(words, _GitSource(plain_call=index == 0, stdin=stdin_source(segment[index + 1:])))
    return _copy_gate(verb, args, expansions)


def _git_changes_paths(args: list[str], expansions: Expansions) -> bool:
    """Judged by the subcommand alone, because a commit message built from $(...) changes no tracked path."""
    _, position = _git_base([_bare(token) for token in args])
    if position >= len(args):
        return False
    subcommand = expansions.pattern(args[position])
    return subcommand is None or subcommand in GIT_CHANGING_COMMANDS


def _positional(words: list[str]) -> list[str]:
    return [word for word in words if not word.startswith("-")]


def _copy_gate(verb: str, args: list[str], expansions: Expansions) -> GatedTargets:
    """Unresolved on a live glob in the destination, because the shell picks that folder only at run time."""
    words = [expansions.pattern(token) or "" for token in args]
    slot = _target_slot(words) if verb != "rsync" else None
    positional = [position for position, word in enumerate(words) if not word.startswith("-")]
    destination = slot[0] if slot else (positional[-1] if len(positional) > 1 else None)
    if destination is not None and expansions.path(args[destination]) is None:
        return UNRESOLVED
    return GatedTargets(tuple(_expand_home(path) for path in _copy_targets(verb, words, slot)), False)


def _copy_targets(verb: str, words: list[str], slot: Slot | None) -> list[str]:
    """Join each source, because a test name survives a copy."""
    taken = {slot[0]} if slot else set()
    sources = [word for position, word in enumerate(words) if not word.startswith("-") and position not in taken]
    if slot is None:
        if len(sources) < 2:
            return sources
        target_dir, sources = sources[-1], sources[:-1]
    else:
        target_dir = words[slot[0]][len(slot[1]):]
    joined = [os.path.join(target_dir, PurePosixPath(source).name) for source in sources]
    return [target_dir, *joined, *(sources if verb == "mv" else [])]


def _git_base(words: list[str]) -> tuple[str, int]:
    """Join -C and --work-tree, because pathspecs resolve below them."""
    position = 0
    base = ""
    while position < len(words) and words[position].startswith("-"):
        flag = words[position]
        base = os.path.join(base, _base_value(flag, words[position + 1:position + 2]))
        position += 2 if flag in GIT_VALUE_FLAGS else 1
    return base, position


def _base_value(flag: str, following: list[str]) -> str:
    if flag.startswith(WORK_TREE_PREFIX):
        return flag[len(WORK_TREE_PREFIX):]
    return following[0] if flag in GIT_BASE_FLAGS and following else ""


def _git_targets(words: list[str], source: _GitSource) -> GatedTargets:
    base, position = _git_base(words)
    command, rest = (words[position], words[position + 1:]) if position < len(words) else ("", [])
    if command in GIT_PATH_COMMANDS:
        return _pathspec_targets(_GitCall(command, base, rest, source.plain_call and _directory_flags_only(words[:position])))
    if command == "mv":
        return GatedTargets(tuple(_expand_home(os.path.join(base, path)) for path in _copy_targets("mv", rest, None)), False)
    dry_apply = bool(GIT_DRY_APPLY_FLAGS.intersection(rest)) and "--apply" not in rest
    if command == "apply" and not dry_apply:
        return _read_targets(_based(git_apply_read(rest, source.stdin), base))
    if command == "stash" and rest[:1] in (["pop"], ["apply"]):
        return UNRESOLVED
    return NO_TARGETS


def _based(read: ArchiveRead | None, base: str) -> ArchiveRead | None:
    """Joined under -C, because git reads the patch and lands its files below that folder."""
    if read is None or not base:
        return read
    return read._replace(source=os.path.join(base, read.source), directory=os.path.join(base, read.directory))


def _read_targets(read: ArchiveRead | None) -> GatedTargets:
    return UNRESOLVED if read is None else GatedTargets((), False, archive=read)


def _patch_targets(raw: list[str]) -> GatedTargets:
    plan = patch_plan([_bare(token) for token in _without_redirects(raw)], stdin_source(raw))
    return UNRESOLVED if plan is None else GatedTargets(plan.paths, False, archive=plan.read)


def _directory_flags_only(flags: list[str]) -> bool:
    """Because only -C keeps git reading this repo's index, any other global option leaves the lookup closed."""
    return len(flags) % 2 == 0 and all(flag == "-C" for flag in flags[::2])


def _pathspec_targets(call: _GitCall) -> GatedTargets:
    """Because only git knows which tracked files a folder or glob names, those go through a lookup."""
    options = call.rest[:call.rest.index("--")] if "--" in call.rest else call.rest
    if _unstages_only(call, options):
        return NO_TARGETS
    paths = call.rest[call.rest.index("--") + 1:] if "--" in call.rest else _positional(call.rest)
    tree = _source_tree(call, options)
    wide = [path for path in paths if GLOB_CHARS.intersection(path) or _is_directory_pathspec(path)]
    globbed = any(GLOB_CHARS.intersection(path) for path in paths)
    closed = (call.command == "checkout" and "--" not in call.rest) or not call.indexable or (tree is not None and globbed)
    unreadable = any(option.startswith(PATHSPEC_FILE_FLAG) for option in options) or any(path.startswith(":") for path in paths)
    if unreadable or (wide and closed):
        return UNRESOLVED
    named = tuple(_expand_home(os.path.join(call.base, path)) for path in paths if path not in wide)
    lookup = GitLookup(call.base, tuple(paths), tree, call.command == "rm" or bool(wide))
    return GatedTargets(named, False, lookup, call.indexable)


def _unstages_only(call: _GitCall, options: list[str]) -> bool:
    """Because restore --staged from HEAD only drops staged changes, it writes no file and adds no content a commit could carry."""
    if call.command != "restore" or not RESTORE_STAGED.intersection(options):
        return False
    worktree = RESTORE_WORKTREE.intersection(options)
    sourced = _option_value(options, ("-s", "--source")) is not None
    return not worktree and not sourced and all(option in RESTORE_PLAIN_FLAGS for option in options if option.startswith("-"))


def _source_tree(call: _GitCall, options: list[str]) -> str | None:
    """Because restore and checkout -- copy from the index unless told to use a tree, None stands for the index."""
    if call.command == "restore":
        source = _option_value(options, ("-s", "--source"))
        return source if source is not None else ("HEAD" if "--staged" in options or "-S" in options else None)
    trees = [word for word in options if not word.startswith("-")] if call.command == "checkout" else []
    return trees[0] if trees else None


def _option_value(options: list[str], flags: tuple[str, str]) -> str | None:
    for position, word in enumerate(options):
        if word.startswith(flags[1] + "="):
            return word[len(flags[1]) + 1:]
        if word in flags and position + 1 < len(options):
            return options[position + 1]
    return None


def _is_directory_pathspec(path: str) -> bool:
    """A dir, because it may hold tests no name shows."""
    return path in {"", ".", ".."} or path.endswith(("/", "/.", "/..")) or path.startswith(":")


def _archive_targets(verb: str, raw: list[str]) -> GatedTargets:
    """Members listed before the run, because an archive member may be a test."""
    words = [_bare(token) for token in _without_redirects(raw)]
    if verb == "tar":
        if not _tar_extracts(words) or _tar_to_stdout(words):
            return NO_TARGETS
        return _read_targets(tar_read(words, stdin_source(raw)))
    return NO_TARGETS if _unzip_reads(words) else _read_targets(unzip_read(words))


def _unzip_reads(words: list[str]) -> bool:
    """Read letters inside a cluster count too, because unzip -lq lists exactly like unzip -l."""
    clusters = [word[1:] for word in words if word.startswith("-") and not word.startswith("--")]
    return bool(UNZIP_READ_FLAGS.intersection(words)) or any(UNZIP_READ_LETTERS.intersection(cluster) for cluster in clusters)


def _tar_to_stdout(words: list[str]) -> bool:
    """Because -O sends every member to stdout, it creates no file, while --to-command runs a program per member."""
    if any(word.startswith(TAR_COMMAND_FLAG) for word in words):
        return False
    clusters = [word[1:] for word in words if word.startswith("-") and not word.startswith("--")]
    old_style = [words[0]] if words and not words[0].startswith("-") else []
    return TAR_STDOUT_FLAG in words or any("O" in cluster for cluster in clusters + old_style)


def _tar_extracts(words: list[str]) -> bool:
    if words and not words[0].startswith("-") and "x" in words[0]:
        return True
    return any(
        word in TAR_EXTRACT_FLAGS or (word.startswith("-") and not word.startswith("--") and "x" in word)
        for word in words
    )
