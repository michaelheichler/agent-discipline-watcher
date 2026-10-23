"""Because a heredoc or here-string is data unless a shell reads it, and a comment or redirect is no argument, the commit gate lexes only the text bash would run."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import NamedTuple

from .shell_syntax import SHELL_C_INTERPRETERS, _basename, _payload_command_index

SUBSTITUTION_RE = re.compile(r"\\.|\$\(|`", re.DOTALL)
BACKTICK_BODY_RE = re.compile(r"(?:\\.|[^`\\])*", re.DOTALL)
SCAN_RE = re.compile(r"""
    (?P<continuation>\\\n)
  | (?P<escape>\\.)
  | (?P<single>'[^']*'?)
  | (?P<double>"(?:\\.|[^"\\])*"?)
  | (?P<backtick>`(?:\\.|[^`\\])*`?)
  | (?P<subst>\$\()
  | (?P<procsub>[<>]\()
  | (?P<herestring><<<[ \t]*(?P<word>'[^']*'|"(?:\\.|[^"\\])*"|[^\s;&|()<>'"]+))
  | (?P<heredoc><<(?P<strip>-?)[ \t]*(?:'(?P<quoted>[^'\n]*)'|"(?P<dquoted>[^"\n]*)"|\\?(?P<bare>[^\s;&|()<>'"]+)))
  | (?P<dup>\d*[<>]&(?:\d+|-)?)
  | (?P<redirect>\d*(?:>>|>\||<>|>|<)[ \t]*(?:'[^']*'|"(?:\\.|[^"\\])*"|[^\s;&|()<>'"]+))
  | (?P<comment>(?<![^\s;&|()])\#[^\n]*)
  | (?P<separator>[;&|()\n])
  | (?P<other>(?:[^\\'"`#;&|()<>\s$]|\$(?!\())+|\s+|.)
""", re.VERBOSE | re.DOTALL)
REDIRECT_PARTS_RE = re.compile(r"(\d*)(>>|>\||<>|<&|>&|>|<)[ \t]*(.*)", re.DOTALL)
MARKED_RE = re.compile(r"\x00(\d+)(<<|>>|>\||<>|<&|>&|>|<)(.*)", re.DOTALL)
ANSI_C_START_RE = re.compile(r"\$'|\\.|'[^']*'?|\"(?:\\.|[^\"\\])*\"?", re.DOTALL)
ANSI_C_ESCAPE_RE = re.compile(
    r"\\(?:([abeEfnrtv\\'\"?])|([0-7]{1,3})|x([0-9A-Fa-f]{1,2})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})|c(.)|(.))", re.DOTALL,
)
ANSI_C_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
    "\\": "\\", "'": "'", '"': '"', "?": "?",
}
PASSED_THROUGH = frozenset({"escape", "single", "double", "other"})
REPLACED = frozenset({"backtick", "subst", "procsub"})
MARKED = frozenset({"redirect", "dup"})
SCRIPT_READERS = frozenset({"source", "."})
SUBSTITUTED = "$SUBSTITUTED"
PROCESS_FILE = "/dev/fd/63"
REDIRECT_MARK = "\x00"
INLINE_INPUT = "<<"


class _Heredoc(NamedTuple):
    delimiter: str
    strip_tabs: bool
    read_by_shell: bool
    slot: str = ""


class Redirect(NamedTuple):
    fd: int
    operator: str
    target: str


def shell_text(command: str) -> str:
    """Cut at a NUL, because bash reads its command as a C string and never sees past one."""
    return _scan(_normalize_ansi_c_quotes(command.split("\0", 1)[0]))


def split_redirects(words: list[str]) -> tuple[list[str], list[Redirect]]:
    """Split out, because a redirect names what a command reads or writes but is never one of its arguments."""
    marked = [(word, MARKED_RE.fullmatch(word)) for word in words]
    plain = [word for word, match in marked if match is None]
    return plain, [Redirect(int(match.group(1)), match.group(2), match.group(3)) for _word, match in marked if match]


def decode_ansi_c_value(value: str) -> str:
    if not value.startswith("$'"):
        return value
    end, decoded = _ansi_c_quote(value, 2)
    return decoded if end == len(value) - 1 else value


def _scan(text: str) -> str:
    return _Scanner(text).text()


def _marker(fd: str, operator: str, target: str) -> str:
    default = "0" if operator.startswith("<") else "1"
    return f" {shlex.quote(f'{REDIRECT_MARK}{fd or default}{operator}{target}')} "


@dataclass(slots=True)
class _Scanner:
    """Because a substitution runs before its command, its body lands as a command line ahead of that command."""

    command: str
    parts: list[str] = field(default_factory=list)
    pending: list[_Heredoc] = field(default_factory=list)
    start: int = 0
    command_part: int = 0

    def text(self) -> str:
        position = 0
        while position < len(self.command):
            match = SCAN_RE.match(self.command, position)
            position = self._take(match) if match else len(self.command)
        self._bodies(len(self.command))
        return "".join(self.parts)

    def _take(self, match: re.Match) -> int:
        kind = match.lastgroup
        if kind == "separator":
            return self._separator(match)
        if kind in REPLACED:
            return self._replace(match)
        if kind in MARKED:
            fd, operator, target = REDIRECT_PARTS_RE.fullmatch(match.group()).groups()
            self.parts.append(_marker(fd, operator, _unquoted(target)))
        if kind == "heredoc":
            self._heredoc(match)
        if kind == "herestring":
            self._herestring(match)
        if kind == "double":
            self._lead_with(_substitutions(match.group()))
        if kind in PASSED_THROUGH:
            self.parts.append(match.group())
        return match.end()

    def _heredoc(self, match: re.Match) -> None:
        slot = f"\x01{len(self.pending)}:{match.start()}\x01"
        self.pending.append(_Heredoc(_delimiter(match), bool(match.group("strip")), self._shell_reads(match.start()), slot))
        self.parts.append(slot)

    def _herestring(self, match: re.Match) -> None:
        word = _unquoted(match.group("word"))
        self.parts.append(f"\n{_scan(word)}\n" if self._shell_reads(match.start()) else _marker("", INLINE_INPUT, word))

    def _replace(self, match: re.Match) -> int:
        """Because a substitution runs first and leaves only its output, its body moves ahead and a dynamic word stays."""
        if match.lastgroup == "backtick":
            body, end = match.group()[1:].removesuffix("`"), match.end()
        else:
            close = _closing_paren(self.command, match.end())
            body, end = self.command[match.end():close], close + 1
        if match.lastgroup == "procsub":
            self.parts.insert(self.command_part, f"( {_scan(body)}\n) | ")
            self.command_part += 1
            self._process_file()
        else:
            self._lead_with([body])
            self.parts.append(SUBSTITUTED)
        return end

    def _process_file(self) -> None:
        """Marked as stdin after a bare <, because bash < <(cmd) reads the process output as its input."""
        index = len(self.parts) - 1
        while index >= self.command_part and not self.parts[index].strip():
            index -= 1
        if index >= self.command_part and self.parts[index] == "<":
            self.parts[index] = _marker("", "<", PROCESS_FILE)
            return
        self.parts.append(PROCESS_FILE)

    def _separator(self, match: re.Match) -> int:
        self.parts.append(match.group())
        self.start, self.command_part = match.end(), len(self.parts)
        return self._bodies(match.end()) if match.group() == "\n" else match.end()

    def _lead_with(self, bodies: list[str]) -> None:
        for body in bodies:
            self.parts.insert(self.command_part, f"{_scan(body)}\n")
            self.command_part += 1

    def _shell_reads(self, position: int) -> bool:
        return _reads_script(self.command[self.start:position])

    def _bodies(self, position: int) -> int:
        for heredoc in self.pending:
            body, position, closed = _heredoc_body(self.command, position, heredoc)
            if heredoc.read_by_shell or not closed:
                self.parts.append(_scan(body))
            self.parts[self.parts.index(heredoc.slot)] = "" if heredoc.read_by_shell else _marker("", INLINE_INPUT, body)
        self.pending = []
        return position


def _substitutions(text: str) -> list[str]:
    """Because bash runs only an unescaped $( or backtick inside double quotes, an escaped marker is skipped."""
    bodies: list[str] = []
    cursor = 0
    while (match := SUBSTITUTION_RE.search(text, cursor)) is not None:
        cursor = match.end()
        if match.group().startswith("\\"):
            continue
        end = BACKTICK_BODY_RE.match(text, cursor).end() if match.group() == "`" else _closing_paren(text, cursor)
        bodies.append(text[cursor:end])
        cursor = end + 1
    return bodies


def _closing_paren(text: str, cursor: int) -> int:
    depth = 1
    for index in range(cursor, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 0:
            return index
    return len(text)


def _delimiter(match: re.Match) -> str:
    return next(value for value in (match.group("quoted"), match.group("dquoted"), match.group("bare")) if value is not None)


def _unquoted(word: str) -> str:
    try:
        return " ".join(shlex.split(word))
    except ValueError:
        return word


def _reads_script(prefix: str) -> bool:
    try:
        words = shlex.split(prefix)
    except ValueError:
        return True
    index = _payload_command_index(words)
    return index >= len(words) or words[index] in SCRIPT_READERS or _basename(words[index]) in SHELL_C_INTERPRETERS


def _heredoc_body(command: str, start: int, heredoc: _Heredoc) -> tuple[str, int, bool]:
    cursor = start
    while cursor < len(command):
        newline = command.find("\n", cursor)
        stop = len(command) if newline < 0 else newline
        line = command[cursor:stop]
        if (line.lstrip("\t") if heredoc.strip_tabs else line) == heredoc.delimiter:
            return command[start:cursor], min(stop + 1, len(command)), True
        cursor = stop + 1
    return command[start:], len(command), False


def _normalize_ansi_c_quotes(command: str) -> str:
    """Only outside quotes, because bash reads $' inside single or double quotes as plain text."""
    parts: list[str] = []
    cursor = position = 0
    while (match := ANSI_C_START_RE.search(command, position)) is not None:
        position = match.end()
        if match.group() != "$'":
            continue
        end, value = _ansi_c_quote(command, match.end())
        if end < 0:
            return command
        parts.extend([command[cursor:match.start()], shlex.quote(value)])
        cursor = position = end + 1
    parts.append(command[cursor:])
    return "".join(parts)


def _ansi_c_quote(command: str, cursor: int) -> tuple[int, str]:
    """Cut at a decoded NUL, because bash ends the word there."""
    chars: list[str] = []
    while cursor < len(command) and command[cursor] != "'":
        match = ANSI_C_ESCAPE_RE.match(command, cursor) if command[cursor] == "\\" else None
        if command[cursor] == "\\" and match is None:
            return -1, ""
        chars.append(_escape_value(match) if match else command[cursor])
        cursor = match.end() if match else cursor + 1
    return (cursor, "".join(chars).split("\0", 1)[0]) if cursor < len(command) else (-1, "")


def _escape_value(match: re.Match) -> str:
    """Kept as written when bash has no meaning for it, so an unknown escape stays unresolved rather than guessed."""
    simple, octal, hexa, short, wide, control, other = match.groups()
    if simple:
        return ANSI_C_ESCAPES[simple]
    if octal or hexa:
        return chr(int(octal, 8) & 0xFF) if octal else chr(int(hexa, 16))
    if short or wide:
        code = int(short or wide, 16)
        return chr(code) if code <= 0x10FFFF else match.group()
    if control:
        return chr(ord(control) & 0x1F)
    return f"\\{other}"
