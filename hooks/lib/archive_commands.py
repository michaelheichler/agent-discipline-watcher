"""Reads tar, unzip, patch and git apply arguments into an ArchiveRead, because only a source and a landing folder known before the run let the gate list the members."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from lib.archive_members import PATCH, TAR, ZIP, ArchiveRead

STDIN = "-"
# Because these rename members, keep absolute names, or run a program.
TAR_HAZARDS = ("--transform", "--xform", "--absolute-names", "--to-command", "--use-compress-program")
TAR_HAZARD_LETTERS = frozenset("PsI")
TAR_VALUE_LETTERS = frozenset("fCbTXgKNVH")
TAR_LONG_VALUES = {"--file": "f", "--directory": "C", "--strip-components": "strip"}
UNZIP_VALUE_FLAGS = frozenset({"-P", "-I", "-O", "-d"})
PATCH_OUTPUT_FLAGS = frozenset({"-o", "--output"})
PATCH_INPUT_FLAGS = frozenset({"-i", "--input"})
PATCH_DIRECTORY_FLAGS = frozenset({"-d", "--directory"})
PATCH_REJECT_FLAGS = frozenset({"-r", "--reject-file"})
PATCH_NAMED_FLAGS = (PATCH_OUTPUT_FLAGS, PATCH_INPUT_FLAGS, PATCH_DIRECTORY_FLAGS, PATCH_REJECT_FLAGS)
# Because a backup prefix or suffix can name any folder.
PATCH_BACKUP_FLAGS = frozenset({"-B", "--prefix", "-Y", "--basename-prefix", "-z", "--suffix"})
PATCH_VALUE_FLAGS = frozenset({"-p", "--strip", "-D", "--ifdef", "-F", "--fuzz", "-V", "--version-control", "-g", "--get"})
PATCH_SIDE_FILES = ("", ".rej", ".orig")
UNSAFE_CHARS = frozenset("$`*?[~{")
GIT_APPLY_VALUE_FLAGS = frozenset({"--directory", "--include", "--exclude", "-p", "-C"})


class PatchPlan(NamedTuple):
    """Either the named outputs or the patch to read, because -o and an original file name the target themselves."""

    paths: tuple[str, ...]
    read: ArchiveRead | None


def stdin_source(args: list[str]) -> str | None:
    """The file behind a plain < redirect, because a piped archive has no file the gate could list."""
    for position, token in enumerate(args):
        if token == "<" and position + 1 < len(args):
            return _plain(args[position + 1])
        if token.startswith("<") and not token.startswith(("<<", "<(")) and len(token) > 1:
            return _plain(token[1:])
    return None


def _plain(word: str) -> str | None:
    bare = word.strip("'\"")
    return bare if bare and not UNSAFE_CHARS.intersection(bare) else None


def tar_read(words: list[str], stdin: str | None) -> ArchiveRead | None:
    fields: dict[str, str] = {}
    rest = _tar_old_style(words, fields)
    if rest is None or not _tar_options(rest, fields):
        return None
    source = fields.get("f", STDIN)
    source = stdin if source == STDIN else _plain(source)
    directory = _plain(fields["C"]) if "C" in fields else ""
    strip = fields.get("strip", "0")
    if source is None or directory is None or not strip.isdigit():
        return None
    return ArchiveRead(TAR, source, directory, int(strip))


def _tar_old_style(words: list[str], fields: dict[str, str]) -> list[str] | None:
    """Because old-style letters take their values from the next words in order, only a lone f value is read."""
    if not words or words[0].startswith("-"):
        return words
    letters, rest = words[0], words[1:]
    others = TAR_VALUE_LETTERS - {"f"}
    if TAR_HAZARD_LETTERS.intersection(letters) or others.intersection(letters) or ("f" in letters and not rest):
        return None
    if "f" in letters:
        fields["f"], rest = rest[0], rest[1:]
    return rest


def _tar_options(words: list[str], fields: dict[str, str]) -> bool:
    position = 0
    while position < len(words):
        word = words[position]
        position += 1
        taken = _tar_long(word, words[position:], fields) if word.startswith("--") else _tar_short(word, words[position:], fields)
        if taken is None:
            return False
        position += taken
    return True


def _tar_long(word: str, following: list[str], fields: dict[str, str]) -> int | None:
    name, separator, value = word.partition("=")
    if name.startswith(TAR_HAZARDS):
        return None
    if name not in TAR_LONG_VALUES:
        return 0
    if not separator and not following:
        return None
    fields[TAR_LONG_VALUES[name]] = value if separator else following[0]
    return 0 if separator else 1


def _tar_short(word: str, following: list[str], fields: dict[str, str]) -> int | None:
    """Because every member stays judged, a positional member name needs no reading."""
    if not word.startswith("-") or word == STDIN:
        return 0
    cluster = word[1:]
    if TAR_HAZARD_LETTERS.intersection(cluster):
        return None
    position = next((index for index, letter in enumerate(cluster) if letter in TAR_VALUE_LETTERS), None)
    if position is None:
        return 0
    inline = cluster[position + 1:]
    if not inline and not following:
        return None
    fields[cluster[position]] = inline or following[0]
    return 0 if inline else 1


@dataclass(slots=True)
class _UnzipScan:
    fields: dict[str, str] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    excluding: bool = False
    junk: bool = False

    def take(self, words: list[str], position: int) -> int:
        word = words[position]
        if word in UNZIP_VALUE_FLAGS:
            self.fields[word] = words[position + 1] if position + 1 < len(words) else ""
            return position + 2
        if word.startswith("-"):
            self.excluding = self.excluding or word == "-x"
            self.junk = self.junk or "j" in word[1:]
        else:
            self._operand(word)
        return position + 1

    def _operand(self, word: str) -> None:
        if "archive" not in self.fields:
            self.fields["archive"] = word
        elif not self.excluding:
            self.patterns.append(word)


def unzip_read(words: list[str]) -> ArchiveRead | None:
    scan = _UnzipScan()
    position = 0
    while position < len(words):
        position = scan.take(words, position)
    source = _plain(scan.fields.get("archive", ""))
    directory = _plain(scan.fields["-d"]) if "-d" in scan.fields else ""
    if source is None or directory is None:
        return None
    return ArchiveRead(ZIP, source, directory, 0, tuple(scan.patterns), scan.junk)


def git_apply_read(rest: list[str], stdin: str | None) -> ArchiveRead | None:
    """One patch file only, because the headers of each patch must be read before the run."""
    if GIT_APPLY_VALUE_FLAGS.intersection(rest):
        return None
    directories = [word.partition("=")[2] for word in rest if word.startswith("--directory=")]
    patches = [word for word in rest if not word.startswith("-") or word == STDIN]
    source = stdin if patches in ([], [STDIN]) else (_plain(patches[0]) if len(patches) == 1 else None)
    directory = _plain(directories[-1]) if directories else ""
    if source is None or directory is None:
        return None
    return ArchiveRead(PATCH, source, directory)


def patch_plan(words: list[str], stdin: str | None) -> PatchPlan | None:
    fields, positional = _patch_fields(words)
    if fields is None or len(positional) > 2:
        return None
    directory = _plain(fields["-d"]) if "-d" in fields else ""
    if directory is None:
        return None
    named = fields.get("-o") or (positional[0] if positional else "")
    if named:
        return _named_patch(named, fields.get("-r"), directory)
    source = fields.get("-i") or (positional[1] if len(positional) > 1 else stdin)
    plain = _plain(source) if source else None
    return None if plain is None else PatchPlan((), ArchiveRead(PATCH, plain, directory))


def _named_patch(named: str, reject: str | None, directory: str) -> PatchPlan | None:
    plain = _plain(named)
    extra = _plain(reject) if reject else ""
    if plain is None or extra is None:
        return None
    joined = f"{directory}/{plain}" if directory else plain
    return PatchPlan(tuple([joined + suffix for suffix in PATCH_SIDE_FILES] + ([extra] if extra else [])), None)


def _patch_fields(words: list[str]) -> tuple[dict[str, str] | None, list[str]]:
    fields: dict[str, str] = {}
    positional: list[str] = []
    position = 0
    while position < len(words):
        word = words[position]
        position += 1
        taken = _patch_option(word, words[position:], fields) if word.startswith("-") else 0
        if taken is None:
            return None, positional
        positional.extend([] if word.startswith("-") else [word])
        position += taken
    return fields, positional


def _patch_option(word: str, following: list[str], fields: dict[str, str]) -> int | None:
    name, separator, value = word.partition("=")
    if name in PATCH_BACKUP_FLAGS or name[:2] in {"-B", "-Y", "-z"}:
        return None
    flags = next((group for group in PATCH_NAMED_FLAGS if _names_flag(name, group)), None)
    if flags is None:
        return 1 if name in PATCH_VALUE_FLAGS and not separator and len(name) == 2 else 0
    inline = value if separator else ("" if name.startswith("--") else name[2:])
    fields[min(flags, key=len)] = inline or (following[0] if following else "")
    return 0 if inline else 1


def _names_flag(name: str, flags: frozenset[str]) -> bool:
    short = min(flags, key=len)
    return name in flags or (not name.startswith("--") and name.startswith(short) and len(name) > 2)
