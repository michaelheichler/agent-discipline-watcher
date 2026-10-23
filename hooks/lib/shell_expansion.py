"""Because the shell acts on the expanded word, not on its spelling, the gates judge the evaluated word."""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterator
from typing import NamedTuple

from .shell_lines import command_lines
from .shell_operators import REDIRECT_HEAD_RE
from .shell_syntax import RESERVED_PREFIXES, SEPARATORS, _bare, _command_word_index, _is_quoted, _tokens

WORD_PART_RE = re.compile(r"""'([^']*)'|"((?:\\[\s\S]|[^"\\])*)"|\\([\s\S])|([^'"\\]+)""")
EXPANSION_RE = re.compile(r"""\\([$`"\\\n])|\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)|[$`]""", re.ASCII)
REFERENCE_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))", re.ASCII)
WELL_KNOWN_RE = re.compile(r"\$\(\s*(?:(pwd)|(git\s+rev-parse\s+--show-toplevel))\s*\)")
WELL_KNOWN_NAMES = ("PWD", "__adw_toplevel")
TOPLEVEL_RE = re.compile(r"\$\(\s*git\s+rev-parse\s+--show-toplevel\s*\)")
LEADING_ENV_RE = re.compile(
    r"""^(")?\$(?:\{(HOME|PWD|__adw_toplevel)\}|(HOME|PWD)\b)(?=/|(?(1)"(?:/|$)|$))""", re.ASCII,
)
ASSIGNMENT_RE = re.compile(r"([A-Za-z_]\w*)=(.*)", re.ASCII | re.DOTALL)
ASSIGNED_NAME_RE = re.compile(r"([A-Za-z_]\w*)(?:\[[^\]]*\])?\+?=", re.ASCII)
NAME_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
DEFAULT_ASSIGNMENT_RE = re.compile(r"\$\{([A-Za-z_]\w*):?=", re.ASCII)
PLAIN_VALUE_RE = re.compile(r"[\w./@%+,:=-]+")
# Because a function, alias, or hash entry can stand in for pwd or git.
REBINDING_RE = re.compile(r"(?:^|[\s;&|(){}`])(?:function\s|alias\b|unalias\b|hash\b|enable\b)|[^\s;&|()<>$`'\"]\s*\(\s*\)")
EARLIER_RUN_RE = re.compile(r"[;&|\n`]|[$<>]\(")
GIT_RESOLUTION_RE = re.compile(r"PATH|GIT_\w+", re.ASCII)
READ_ONLY_COMMANDS = frozenset({"echo", "printf", "test", "[", ":"})
NO_BANS: frozenset[str] = frozenset()
PATTERN_BANS = frozenset("{")
PATH_BANS = frozenset("{*?[")
OPENERS = frozenset({"if", "while", "until", "for", "select", "function", "{"})
CLOSERS = frozenset({"fi", "done", "}"})
PAREN_DEPTH = {"(": 1, ")": -1}
SUBSHELL_SEPARATORS = frozenset({"|", "|&", "&"})
CONTINUING_SEPARATORS = frozenset({"&&", "||", "|", "|&"})
UNCONDITIONAL_BEFORE = frozenset({";", "&", "\n"})
WIPING_COMMANDS = frozenset({"source", ".", "eval", "builtin", "let", "coproc", "trap", "case"})
DECLARING_FLAGS = {"export": "np", "readonly": "p", "declare": "xrg", "typeset": "xrg", "local": "xrg"}
UNSETTING_DECLARERS = frozenset({"declare", "typeset", "local"})
NAMING_COMMANDS = frozenset({"read", "mapfile", "readarray", "unset", "getopts"})
TARGET_FLAG_COMMANDS = {"printf": "-v", "wait": "-p"}
# Because (( M = 1 )) assigns without the spelling the walk reads.
ARITHMETIC = "(("
GIT_TIMEOUT_SECONDS = 2


class Tree(NamedTuple):
    """Because a recursive delete removes every file its folder holds, those files ride with its segment."""

    segment: tuple[str, ...]
    named: tuple[str, ...]
    files: tuple[str, ...]
    unknown: tuple[str, ...]


class Expansions(NamedTuple):
    """None for an unproven word, because a guessed word would skip the gate of its real path."""

    proven: dict[str, str]
    touched: frozenset[str] = frozenset()
    environment: bool = True
    toplevel: str | None = None
    links: tuple[tuple[str, str], ...] = ()
    cwd: str | None = None
    well_known: bool = True
    feeds: tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = ()
    trees: tuple[Tree, ...] = ()

    def calls(self, segment: list[str]) -> list[list[str]] | None:
        """Because xargs with a literal feed runs exactly these calls, they stand in for its segment."""
        key = tuple(segment)
        return next(([list(call) for call in calls] for fed, calls in self.feeds if fed == key), None)

    def tree(self, segment: list[str]) -> Tree | None:
        key = tuple(segment)
        return next((tree for tree in self.trees if tree.segment == key), None)

    def aliases(self, path: str) -> list[str]:
        """Because a write through a link lands on its target, the target faces the same gates."""
        name = os.path.normpath(path)
        made = [os.path.normpath(target + name[len(link):]) for link, target in self.links if name == link or name.startswith(link + os.sep)]
        return made + self._on_disk(path)

    def _on_disk(self, path: str) -> list[str]:
        """Only the path's own components, because the folders above cwd are the session's and not a route."""
        expanded = os.path.expanduser(path)
        if self.cwd is None or not expanded:
            return []
        parts = os.path.normpath(expanded).split(os.sep)
        base = os.sep if os.path.isabs(expanded) else self.cwd
        for index in range(len(parts) - 1 if os.path.isabs(expanded) else 0, len(parts)):
            prefix = os.path.join(base, *parts[:index + 1])
            if os.path.islink(prefix):
                return [os.path.join(os.path.realpath(prefix), *parts[index + 1:])]
        return []

    def path(self, word: str) -> str | None:
        """Unresolved on a glob, because the shell picks the matching file only at run time."""
        return self._evaluated(word, PATH_BANS)

    def pattern(self, word: str) -> str | None:
        """Globs kept, because the caller expands them against the repo itself."""
        return self._evaluated(word, PATTERN_BANS)

    def assigned(self, word: str) -> str | None:
        """No bans, because an assignment value meets neither brace nor pathname expansion."""
        return self._evaluated(word, NO_BANS)

    def _evaluated(self, word: str, bans: frozenset[str]) -> str | None:
        if word.startswith("="):
            return None
        word = WELL_KNOWN_RE.sub(_well_known_reference, word) if self.well_known else word
        word = LEADING_ENV_RE.sub(self._leading_spelling, word, count=1)
        built: list[str] = []
        cursor = 0
        for part in WORD_PART_RE.finditer(word):
            text = self._part_text(part, bans)
            if part.start() != cursor or text is None:
                return None
            built.append(text)
            cursor = part.end()
        return "".join(built) if cursor == len(word) else None

    def _leading_spelling(self, match: re.Match[str]) -> str:
        name = match.group(2) or match.group(3)
        spelling = self._leading_value(name) if self.environment and name not in self.touched else None
        return match.group() if spelling is None else spelling + (match.group(1) or "")

    def _leading_value(self, name: str) -> str | None:
        """Because later checks join ~ and . to home and cwd like a typed path, those two stay symbolic."""
        return {"HOME": "~", "PWD": ".", "__adw_toplevel": self.toplevel}[name]

    def _part_text(self, part: re.Match[str], bans: frozenset[str]) -> str | None:
        single, double, escaped, bare = part.groups()
        if single is not None:
            return single
        if escaped is not None:
            return "" if escaped == "\n" else escaped
        return self._expanded(double, NO_BANS) if double is not None else self._expanded(bare, bans)

    def _expanded(self, text: str, bans: frozenset[str]) -> str | None:
        pieces: list[str] = []
        cursor = 0
        for match in [*EXPANSION_RE.finditer(text), None]:
            literal = text[cursor:match.start() if match else len(text)]
            if bans.intersection(literal):
                return None
            pieces.append(literal)
            if match is None:
                return "".join(pieces)
            value = self._expansion(match)
            if value is None:
                return None
            pieces.append(value)
            cursor = match.end()
        return None

    def _expansion(self, match: re.Match[str]) -> str | None:
        escape, braced, plain = match.groups()
        if escape is not None:
            return "" if escape == "\n" else escape
        name = braced or plain
        return None if name is None else self._value(name)

    def _value(self, name: str) -> str | None:
        if name in self.proven:
            return self.proven[name]
        if not self.environment or name in self.touched:
            return None
        tmpdir = os.environ.get("TMPDIR", "") if name == "TMPDIR" else ""
        return tmpdir if PLAIN_VALUE_RE.fullmatch(tmpdir) else None


class _Proof(NamedTuple):
    """Because a later assignment must not move an earlier write, each read keeps the values it met."""

    values: dict[str, list[str]]
    touched: set[str]
    current: dict[str, str]
    seen: dict[str, set[str | None]]
    marks: set[str]
    links: dict[str, str]


class _Command(NamedTuple):
    word: str
    args: list[str]
    unconditional: bool
    so_far: Expansions


def expansions_for(command: str, cwd: str | os.PathLike[str] | None = None) -> Expansions:
    """Because a later builtin, branch, or computed name can change a variable, only unconditional literal assignments that every read met prove it."""
    well_known = REBINDING_RE.search(command) is None
    text = WELL_KNOWN_RE.sub(_well_known_reference, command) if well_known else command
    proof = _Proof({}, set(), {}, {}, {"wiped"} if ARITHMETIC in text else set(), {})
    for segment, unconditional in _walked_segments(text):
        _note(proof, segment, unconditional)
    touched = frozenset(proof.touched | set(proof.values))
    links, folder = tuple(proof.links.items()), None if cwd is None else os.fspath(cwd)
    if "wiped" in proof.marks:
        return Expansions({}, touched, False, None, links, folder, well_known)
    wants_root = cwd is not None and well_known and _git_runs_first(command, touched)
    proven = _proven(proof, single=not well_known)
    return Expansions(proven, touched, True, _repo_root(cwd) if wants_root else None, links, folder, well_known)


def _git_runs_first(command: str, touched: frozenset[str]) -> bool:
    """Because any earlier command, cd, or git setting can move the repo root, only a lone first run is known."""
    runs = list(TOPLEVEL_RE.finditer(command))
    if len(runs) != 1 or EARLIER_RUN_RE.search(command[:runs[0].start()]):
        return False
    return not any(GIT_RESOLUTION_RE.fullmatch(name) for name in touched)


def _well_known_reference(match: re.Match[str]) -> str:
    """Kept as a reference, because only a leading position lets the evaluator give it a value."""
    return "${" + WELL_KNOWN_NAMES[match.lastindex - 1] + "}"


def _repo_root(cwd: str | os.PathLike[str]) -> str | None:
    try:
        found = subprocess.run(
            ["git", "-C", os.fspath(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    root = found.stdout.strip()
    return root if found.returncode == 0 and PLAIN_VALUE_RE.fullmatch(root) else None


def _proven(proof: _Proof, single: bool = False) -> dict[str, str]:
    """Because a read before any assignment, or reads that met two values, leave no single destination, and a function body reads at call time."""
    met = {
        name: proof.seen.get(name, set(values)) for name, values in proof.values.items()
        if name not in proof.touched and not (single and len(set(values)) > 1)
    }
    return {name: next(iter(found)) for name, found in met.items() if len(found) == 1 and None not in found}


def _walked_segments(text: str) -> Iterator[tuple[list[str], bool]]:
    """Depth counted across lines, because a then or do on one line still guards the next."""
    depth, before = 0, "\n"
    for line in command_lines(text):
        before = before if before in CONTINUING_SEPARATORS else "\n"
        for segment, after in _split(_tokens(line.text)):
            depth += 1 if segment[:1] and segment[0] in OPENERS else 0
            yield segment, depth == 0 and before in UNCONDITIONAL_BEFORE and after not in SUBSHELL_SEPARATORS
            depth = max(0, depth - (1 if segment[:1] and segment[0] in CLOSERS else 0) + PAREN_DEPTH.get(after, 0))
            before = after


def _split(tokens: list[str]) -> list[tuple[list[str], str]]:
    """Because a line ending in && guards the next line, a trailing operator stays the last separator."""
    found: list[tuple[list[str], str]] = []
    segment: list[str] = []
    for token in tokens:
        if token not in SEPARATORS:
            segment.append(token)
            continue
        found.append((segment, token))
        segment = []
    return found + ([(segment, "\n")] if segment or not found else [])


def _note(proof: _Proof, segment: list[str], unconditional: bool) -> None:
    body = segment[next((index for index, token in enumerate(segment) if token not in RESERVED_PREFIXES), len(segment)):]
    index = _command_word_index(body)
    if not _reads_harmlessly(body, index):
        _note_reads(proof, segment)
    current = {name: value for name, value in proof.current.items() if name not in proof.touched}
    so_far = Expansions(current, frozenset(proof.touched | set(proof.values)), "wiped" not in proof.marks)
    if body and index == len(body):
        _assign_all(proof, _Command("", body, unconditional, so_far))
    else:
        proof.touched.update(_assigned_names(body[:index]))
        word = _bare(body[index]) if index < len(body) else ""
        _note_command(proof, _Command(word, body[index + 1:], unconditional, so_far))


def _assign_all(proof: _Proof, command: _Command) -> None:
    for token in command.args:
        match = ASSIGNMENT_RE.fullmatch(token)
        if match is None:
            proof.touched.update(_assigned_names([token]))
            continue
        _record(proof, match.group(1), command.so_far.assigned(match.group(2)) if command.unconditional else None)


def _note_reads(proof: _Proof, segment: list[str]) -> None:
    """Before the segment's own assignments, because bash expands a command's words before it runs."""
    for token in segment:
        for match in [] if token.startswith("'") and _is_quoted(token) else REFERENCE_RE.finditer(token):
            name = match.group(1) or match.group(2)
            proof.seen.setdefault(name, set()).add(proof.current.get(name))


def _assigned_names(tokens: list[str]) -> set[str]:
    """Because M+=x and M[0]=x change $M as well, every assignment form touches its name."""
    return {match.group(1) for match in map(ASSIGNED_NAME_RE.match, tokens) if match}


def _reads_harmlessly(body: list[str], index: int) -> bool:
    """Because a read with no write redirect and no writing verb names no destination, it may come first."""
    if any(REDIRECT_HEAD_RE.match(token) and not _is_quoted(token) for token in body):
        return False
    return index == len(body) or _bare(body[index]) in READ_ONLY_COMMANDS


def _record(proof: _Proof, name: str, value: str | None) -> None:
    if value is None or not PLAIN_VALUE_RE.fullmatch(value):
        proof.touched.add(name)
        return
    proof.values.setdefault(name, []).append(value)
    proof.current[name] = value


def _note_command(proof: _Proof, command: _Command) -> None:
    if command.word in WIPING_COMMANDS or any("${!" in arg for arg in command.args):
        proof.marks.add("wiped")
    handler = HANDLERS.get(command.word)
    if handler is not None:
        handler(proof, command)
    proof.touched.update(match.group(1) for arg in command.args for match in DEFAULT_ASSIGNMENT_RE.finditer(arg))


def _declare(proof: _Proof, command: _Command) -> None:
    """Allowed flags only, because declare -n or -u would make the variable hold something other than its text."""
    for arg in command.args:
        _declared(proof, command, command.so_far.assigned(arg))


def _declared(proof: _Proof, command: _Command, text: str | None) -> None:
    flags = text[1:] if text and text.startswith("-") else None
    match = ASSIGNMENT_RE.fullmatch(text or "")
    bad_flags = flags is not None and not set(flags) <= set(DECLARING_FLAGS[command.word])
    if text is None or bad_flags or (flags is None and match is None and not NAME_RE.fullmatch(text)):
        proof.marks.add("wiped")
        return
    if match is not None:
        _record(proof, match.group(1), match.group(2) if command.unconditional else None)
        return
    if flags is None and command.word in UNSETTING_DECLARERS:
        proof.touched.add(text)


def _touch_names(proof: _Proof, command: _Command) -> None:
    """Because read or unset with a computed name may write any variable, every argument counts."""
    for text in map(command.so_far.assigned, command.args):
        _touch(proof, text, True)


def _touch_loop_name(proof: _Proof, command: _Command) -> None:
    _touch(proof, command.so_far.assigned(command.args[0]) if command.args else "", True)


def _touch_flag_target(proof: _Proof, command: _Command) -> None:
    flag = TARGET_FLAG_COMMANDS[command.word]
    for position, arg in enumerate(command.args):
        if arg.startswith(flag):
            name = arg[len(flag):] or (command.args[position + 1] if position + 1 < len(command.args) else "")
            text = command.so_far.assigned(name)
            _touch(proof, text, text is not None and NAME_RE.fullmatch(text) is not None)


def _link(proof: _Proof, command: _Command) -> None:
    """Because a later write through the new name lands on the old file, each link joins the proof."""
    words = [command.so_far.path(arg) for arg in command.args]
    if None in words:
        return
    symbolic = any(word == "--symbolic" or (word.startswith("-") and not word.startswith("--") and "s" in word) for word in words)
    for link, target in _link_pairs([word for word in words if word is not None]):
        anchored = target.startswith("~") or os.path.isabs(target)
        proof.links[os.path.normpath(link)] = target if anchored or not symbolic else os.path.normpath(os.path.join(os.path.dirname(link), target))


def _link_pairs(words: list[str]) -> list[tuple[str, str]]:
    """Both readings of the last name, because ln puts the link inside it when it is a folder."""
    folder = next((words[index + 1] for index, word in enumerate(words[:-1]) if word in {"-t", "--target-directory"}), None)
    folder = folder or next((word.split("=", 1)[1] for word in words if word.startswith("--target-directory=")), None)
    names = [word for word in words if not word.startswith("-") and word != folder]
    if folder is not None:
        return [(os.path.join(folder, os.path.basename(name)), name) for name in names]
    if len(names) == 1:
        return [(os.path.basename(names[0]), names[0])]
    return [pair for name in names[:-1] for pair in ((names[-1], name), (os.path.join(names[-1], os.path.basename(name)), name))]


def _touch(proof: _Proof, text: str | None, known: bool) -> None:
    """Because a write to a name the text cannot show may land on any variable, it wipes every proof."""
    if text is None or not known:
        proof.marks.add("wiped")
    elif NAME_RE.fullmatch(text):
        proof.touched.add(text)


HANDLERS: dict[str, Callable[[_Proof, _Command], None]] = {
    **dict.fromkeys(DECLARING_FLAGS, _declare),
    **dict.fromkeys(NAMING_COMMANDS, _touch_names),
    **dict.fromkeys(TARGET_FLAG_COMMANDS, _touch_flag_target),
    "for": _touch_loop_name,
    "select": _touch_loop_name,
    "ln": _link,
}
