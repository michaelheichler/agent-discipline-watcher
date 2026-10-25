"""Because the test gate can judge an extraction or a patch only by the names it lands, those names are listed before the run."""
from __future__ import annotations

import fnmatch
import os
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import NamedTuple

MAX_MEMBERS = 20_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PATCH_BYTES = 4 * 1024 * 1024
TAR, ZIP, PATCH = "tar", "zip", "patch"
PATCH_HEADERS = ("--- ", "+++ ")
# Because these lines move, copy, or replace a file no header names.
PATCH_HAZARDS = ("rename from ", "rename to ", "copy from ", "copy to ", "GIT binary patch", "Binary files ")
DEV_NULL = "/dev/null"


class ArchiveRead(NamedTuple):
    """Unresolved later when the source cannot be read, because only the members say which files land."""

    kind: str
    source: str
    directory: str = ""
    strip: int = 0
    patterns: tuple[str, ...] = ()
    junk_paths: bool = False


def landed_paths(read: ArchiveRead, folder: Path) -> list[str] | None:
    """None when any member is unsafe or unreadable, because one hidden test name is enough to open the gate."""
    names = _names(read, folder / read.source)
    if names is None:
        return None
    landed: list[str] = []
    for name in names:
        placed = _placed(read, name)
        if placed is None:
            return None
        landed.extend(os.path.normpath(os.path.join(read.directory, path)) for path in placed)
    return landed


def _names(read: ArchiveRead, source: Path) -> list[str] | None:
    try:
        size = source.stat().st_size
    except OSError:
        return None
    if read.kind == PATCH:
        return _patch_names(source) if size <= MAX_PATCH_BYTES else None
    if size > MAX_ARCHIVE_BYTES:
        return None
    names = _tar_names(source) if read.kind == TAR else _zip_names(source)
    if names is None or not read.patterns:
        return names
    return [name for name in names if any(fnmatch.fnmatchcase(name, pattern) for pattern in read.patterns)]


def _placed(read: ArchiveRead, name: str) -> list[str] | None:
    """Because patch without -p picks the strip level itself, every strip spelling counts."""
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or ".." in parts:
        return None
    if read.kind == PATCH:
        return ["/".join(parts[index:]) for index in range(len(parts))]
    if read.junk_paths:
        return [parts[-1]]
    kept = parts[read.strip:]
    return ["/".join(kept)] if kept else []


def _tar_names(source: Path) -> list[str] | None:
    """None on a link or device member, because it can point an extraction at a file outside its own name."""
    try:
        with tarfile.open(source, "r:*") as archive:
            return _plain_members(archive)
    except (OSError, tarfile.TarError, EOFError, ValueError):
        return None


def _plain_members(archive: tarfile.TarFile) -> list[str] | None:
    names: list[str] = []
    for member in archive:
        if len(names) >= MAX_MEMBERS or not (member.isfile() or member.isdir()):
            return None
        names.append(member.name)
    return names


def _zip_names(source: Path) -> list[str] | None:
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
    except (OSError, zipfile.BadZipFile, ValueError):
        return None
    if len(members) > MAX_MEMBERS or any(stat.S_ISLNK(member.external_attr >> 16) for member in members):
        return None
    return [member.filename for member in members]


def _patch_names(source: Path) -> list[str] | None:
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if any(line.startswith(PATCH_HAZARDS) for line in lines):
        return None
    names = [_header_path(line) for line in lines if line.startswith(PATCH_HEADERS)]
    found = [name for name in names if name and name != DEV_NULL]
    return found if found and len(found) <= MAX_MEMBERS else None


def _header_path(line: str) -> str:
    """The path before any tab, because diff puts a timestamp after it."""
    return line[4:].split("\t", 1)[0].strip()
