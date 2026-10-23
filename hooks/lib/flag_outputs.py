"""Because curl, wget, and sort write files through flags, those flags name targets the way a redirect does."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import NamedTuple
from urllib.parse import urlsplit

STDOUT = "-"
END_OF_OPTIONS = "--"
MAY_OPEN_OPTION = frozenset("-$`*?[{\\")
UNSAFE_NAME = frozenset("%#[{")
WRITE_OUT_FLAGS = frozenset({"-w", "--write-out"})
WRITE_OUT_FILE = "%output{"
URL_FLAG = "--url"
NEGATED_PAIR_RE = re.compile("n.")
Resolver = Callable[[str], "str | None"]


class FlagSpec(NamedTuple):
    """Abbreviating, because GNU getopt reads --out as --output, and paired_n, because wget spells -np as one flag."""

    value_shorts: str
    value_longs: frozenset[str]
    files: frozenset[str]
    opaque: frozenset[str]
    folders: frozenset[str]
    naming: frozenset[str]
    quiet: frozenset[str]
    abbreviating: bool = False
    paired_n: bool = False
    templates: bool = False
    names_by_default: bool = False
    config_names: frozenset[str] = frozenset()


class Parsed(NamedTuple):
    options: list[tuple[str, str | None]]
    urls: list[str | None]
    unknown: list[str]


class FlagTargets(NamedTuple):
    paths: list[str]
    unknown: list[str]


class _Source(NamedTuple):
    spec: FlagSpec
    words: list[str]
    resolve: Resolver
    parsed: Parsed


class _Cursor(NamedTuple):
    position: int
    ended: bool


class _Collect(NamedTuple):
    spec: FlagSpec
    folder: str | None
    found: FlagTargets


CURL = FlagSpec(
    value_shorts="AbcCdDeEFHKmoPQrtTuUwxXyYz",
    value_longs=frozenset({
        "--output", "--dump-header", "--cookie-jar", "--trace", "--trace-ascii", "--stderr", "--libcurl",
        "--etag-save", "--etag-compare", "--hsts", "--alt-svc", "--config", "--output-dir", "--write-out",
        "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "--json",
        "--request", "--user", "--user-agent", "--referer", "--form", "--form-string", "--upload-file",
        "--cookie", "--max-time", "--connect-timeout", "--range", "--proxy", "--cert", "--key", "--cacert",
        "--url", "--retry", "--retry-delay", "--retry-max-time", "--oauth2-bearer", "--resolve", "--interface",
        "--limit-rate", "--max-filesize", "--time-cond", "--continue-at", "--quote", "--variable", "--proxy-user",
        "--connect-to", "--max-redirs", "--expect100-timeout", "--keepalive-time", "--aws-sigv4",
    }),
    files=frozenset({
        "-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar", "--trace", "--trace-ascii",
        "--stderr", "--libcurl", "--etag-save", "--hsts", "--alt-svc",
    }),
    opaque=frozenset({"-K", "--config", "-J", "--remote-header-name"}),
    folders=frozenset({"--output-dir"}),
    naming=frozenset({"-O", "--remote-name", "--remote-name-all"}),
    quiet=frozenset(),
    templates=True,
    config_names=frozenset({"HOME", "CURL_HOME", "XDG_CONFIG_HOME"}),
)
WGET = FlagSpec(
    value_shorts="OoaPeiBtTwQUlARDIX",
    value_longs=frozenset({
        "--output-document", "--output-file", "--append-output", "--directory-prefix", "--execute",
        "--input-file", "--base", "--tries", "--timeout", "--wait", "--quota", "--user-agent", "--level",
        "--accept", "--reject", "--domains", "--include-directories", "--exclude-directories", "--config",
        "--save-cookies", "--load-cookies", "--warc-file", "--rejected-log", "--default-page", "--header",
        "--post-data", "--post-file", "--body-data", "--body-file", "--method", "--user", "--password",
        "--http-user", "--http-password", "--referer", "--limit-rate", "--cut-dirs",
    }),
    files=frozenset({
        "-O", "--output-document", "-o", "--output-file", "-a", "--append-output", "--save-cookies",
        "--rejected-log",
    }),
    opaque=frozenset({
        "-r", "--recursive", "-m", "--mirror", "-p", "--page-requisites", "-i", "--input-file",
        "--content-disposition", "--trust-server-names", "-e", "--execute", "--config", "-x",
        "--force-directories", "--default-page", "--warc-file",
    }),
    folders=frozenset({"-P", "--directory-prefix"}),
    naming=frozenset(),
    quiet=frozenset({"--spider", "-O", "--output-document"}),
    abbreviating=True,
    paired_n=True,
    names_by_default=True,
    config_names=frozenset({"HOME", "WGETRC", "SYSTEM_WGETRC"}),
)
SORT = FlagSpec(
    value_shorts="koStT",
    value_longs=frozenset({
        "--output", "--key", "--field-separator", "--buffer-size", "--temporary-directory", "--batch-size",
        "--compress-program", "--files0-from", "--parallel", "--random-source", "--sort",
    }),
    files=frozenset({"-o", "--output"}),
    opaque=frozenset({"--compress-program"}),
    folders=frozenset(),
    naming=frozenset(),
    quiet=frozenset(),
    abbreviating=True,
)
FLAG_WRITERS = {"curl": CURL, "wget": WGET, "sort": SORT}


def flag_targets(verb: str, words: list[str], resolve: Resolver) -> FlagTargets:
    """Unknown on an unproven word that may open an option, because "$X" can carry -o and its file."""
    spec = FLAG_WRITERS[verb]
    parsed = parse(spec, words, resolve)
    flags = [flag for flag, _ in parsed.options]
    collect = _Collect(spec, _folder(spec, parsed), FlagTargets([], list(parsed.unknown)))
    collect.found.unknown.extend(flag for flag in flags if flag in spec.opaque)
    for flag, value in parsed.options:
        _flag_target(collect, flag, value)
    naming = (spec.naming.intersection(flags) or spec.names_by_default) and not spec.quiet.intersection(flags)
    for url in parsed.urls + [value for flag, value in parsed.options if flag == URL_FLAG] if naming else []:
        _named_target(collect, url)
    return collect.found


def parse(spec: FlagSpec, words: list[str], resolve: Resolver) -> Parsed:
    source, cursor = _Source(spec, words, resolve, Parsed([], [], [])), _Cursor(0, False)
    while cursor.position < len(words):
        cursor = _step(source, cursor)
    return source.parsed


def _step(source: _Source, cursor: _Cursor) -> _Cursor:
    raw = source.words[cursor.position]
    word = source.resolve(raw)
    after = cursor._replace(position=cursor.position + 1)
    if cursor.ended or not _option_like(raw, word):
        source.parsed.urls.append(word)
        return after
    if word is None:
        source.parsed.unknown.append(raw)
        return after
    if word == END_OF_OPTIONS:
        return after._replace(ended=True)
    read = _read_long if word.startswith("--") else _read_shorts
    return after._replace(position=read(source, word, after.position))


def _option_like(raw: str, word: str | None) -> bool:
    if word is None:
        bare = raw.lstrip("\"'")
        return not bare or bare[0] in MAY_OPEN_OPTION
    return word.startswith("-") and word != STDOUT


def _read_long(source: _Source, word: str, position: int) -> int:
    name, has_value, value = word.partition("=")
    flag = _canonical(source.spec, name)
    if has_value or flag not in source.spec.value_longs:
        source.parsed.options.append((flag, value))
        return position
    return _take_next(source, flag, position)


def _read_shorts(source: _Source, word: str, position: int) -> int:
    letters = word[1:]
    cut = _value_index(source.spec, letters)
    booleans = NEGATED_PAIR_RE.sub("", letters[:cut]) if source.spec.paired_n else letters[:cut]
    source.parsed.options.extend(("-" + letter, "") for letter in booleans)
    if cut >= len(letters):
        return position
    if cut + 1 < len(letters):
        source.parsed.options.append(("-" + letters[cut], letters[cut + 1:]))
        return position
    return _take_next(source, "-" + letters[cut], position)


def _value_index(spec: FlagSpec, letters: str) -> int:
    index = 0
    while index < len(letters) and letters[index] not in spec.value_shorts:
        index += 2 if spec.paired_n and letters[index] == "n" else 1
    return index


def _take_next(source: _Source, flag: str, position: int) -> int:
    raw = source.words[position] if position < len(source.words) else None
    source.parsed.options.append((flag, None if raw is None else source.resolve(raw)))
    return position + 1


def _canonical(spec: FlagSpec, name: str) -> str:
    """The riskiest match, because an ambiguous prefix either fails or names one of them."""
    known = spec.value_longs | spec.files | spec.opaque | spec.folders | spec.naming | spec.quiet
    if not spec.abbreviating or name in known:
        return name
    matches = sorted(flag for flag in known if flag.startswith(name))
    risky = [flag for flag in matches if flag in spec.files | spec.opaque | spec.folders]
    return (risky or matches or [name])[0]


def _folder(spec: FlagSpec, parsed: Parsed) -> str | None:
    folders = [value for flag, value in parsed.options if flag in spec.folders]
    return folders[-1] if folders else ""


def _flag_target(collect: _Collect, flag: str, value: str | None) -> None:
    unsafe_write_out = flag in WRITE_OUT_FLAGS and collect.spec.templates and WRITE_OUT_FILE in (value or "")
    if unsafe_write_out or (flag in collect.spec.files and _unplaceable(collect, value)):
        collect.found.unknown.append(flag)
    elif flag in collect.spec.files and value != STDOUT:
        collect.found.paths.append(os.path.join(collect.folder, value))


def _unplaceable(collect: _Collect, value: str | None) -> bool:
    """Because curl fills #1 from the URL and a folder flag may move an absolute name, either hides the file."""
    if value is None or collect.folder is None:
        return True
    return (collect.spec.templates and "#" in value) or (bool(collect.folder) and os.path.isabs(value))


def _named_target(collect: _Collect, url: str | None) -> None:
    name = _url_name(collect.spec, url)
    if name is None or collect.folder is None:
        collect.found.unknown.append(url or "URL")
        return
    collect.found.paths.append(os.path.join(collect.folder, name))


def _url_name(spec: FlagSpec, url: str | None) -> str | None:
    """The last path part, because curl -O and wget pick it, and wget picks a server name when the URL has none."""
    if url is None or (spec.templates and UNSAFE_NAME.intersection(url)):
        return None
    name = PurePosixPath(urlsplit(url).path).name
    return None if name in {"", ".", ".."} or UNSAFE_NAME.intersection(name) else name
