from __future__ import annotations

import gzip
import io
import json
import os
import re
import ssl
import stat
import tarfile
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote, urljoin, urlsplit


REPOSITORY = "michaelheichler/agent-discipline-watcher"
API_HOST = "api.github.com"
CODELOAD_HOST = "codeload.github.com"
API_ROOT = f"https://{API_HOST}/repos/{REPOSITORY}"
LATEST_URL = f"{API_ROOT}/releases/latest"
ARCHIVE_ROOT = f"https://{CODELOAD_HOST}/{REPOSITORY}/tar.gz"
PLUGIN_NAME = "agent-discipline-watcher"

HTTP_TIMEOUT = 20.0
MAX_REDIRECTS = 4
MAX_API_BYTES = 1 << 20
MAX_ARCHIVE_BYTES = 64 << 20
MAX_TAR_BYTES = 288 << 20
MAX_EXTRACTED_BYTES = 256 << 20
MAX_MEMBER_BYTES = 64 << 20
MAX_MEMBERS = 10_000
READ_CHUNK_BYTES = 1 << 20
MAX_TAG_DEPTH = 4

TAG_RE = re.compile(r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
README_RELEASE_RE = re.compile(r"Current release:\s*\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*")
REQUIRED_FILES = (
    "install.sh",
    "hosts/claude/install.sh",
    "hosts/codex/install.sh",
    "hosts/omp/install.sh",
    ".claude-plugin/plugin.json",
    "README.md",
)


@dataclass(frozen=True, slots=True)
class Release:
    tag: str
    commit: str


@dataclass(frozen=True, slots=True)
class _Member:
    info: tarfile.TarInfo
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Archive:
    root: str
    members: tuple[_Member, ...]


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, "_adw_redirect_count", 0)
        if count >= MAX_REDIRECTS:
            raise ValueError("release download exceeded the redirect limit")
        target = urljoin(req.full_url, newurl)
        _validate_url(target)
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is not None:
            setattr(redirected, "_adw_redirect_count", count + 1)
        return redirected


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in {API_HOST, CODELOAD_HOST}:
        raise ValueError("release URL is outside the HTTPS allowlist")
    if parsed.port not in (None, 443):
        raise ValueError("release URL uses an unexpected port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("release URL carries credentials")


def _tls_context() -> ssl.SSLContext:
    paths = ssl.get_default_verify_paths()
    return ssl.create_default_context(cafile=paths.openssl_cafile, capath=paths.openssl_capath)


def _read_response(response, limit: int) -> bytes:
    headers = getattr(response, "headers", {})
    advertised = headers.get("Content-Length") if hasattr(headers, "get") else None
    if advertised is not None:
        if not advertised.isascii() or not advertised.isdigit():
            raise ValueError("release response Content-Length is invalid")
        if int(advertised) > limit:
            raise ValueError("release response exceeds the size limit")
    body = bytearray()
    while len(body) <= limit:
        chunk = response.read(min(READ_CHUNK_BYTES, limit + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > limit:
            raise ValueError("release response exceeds the size limit")
    if advertised is not None and len(body) != int(advertised):
        raise ValueError("release response is truncated")
    return bytes(body)


def _get_bytes(url: str, limit: int, accept: str) -> bytes:
    _validate_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": "agent-discipline-watcher-release/1"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=_tls_context()),
        _RedirectHandler(),
    )
    with opener.open(request, timeout=HTTP_TIMEOUT) as response:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status is not None and not 200 <= status < 300:
            raise ValueError(f"release request returned HTTP {status}")
        return _read_response(response, limit)


def _json(url: str) -> dict[str, object]:
    try:
        value = json.loads(_get_bytes(url, MAX_API_BYTES, "application/vnd.github+json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("release API returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("release API returned a JSON object with the wrong shape")
    return value


def _tag(value: object) -> str:
    if not isinstance(value, str) or TAG_RE.fullmatch(value) is None:
        raise ValueError("release tag is not a stable vN.N.N tag")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} is not a 40-character hexadecimal SHA")
    return value.lower()


def _object(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError("git object metadata is missing")
    kind = value.get("type")
    if not isinstance(kind, str) or kind not in {"commit", "tag"}:
        raise ValueError("git object type is invalid")
    return kind, _sha(value.get("sha"), "git object SHA")


def _commit_for_tag(tag: str) -> str:
    ref = _json(f"{API_ROOT}/git/ref/tags/{quote(tag, safe='')}")
    kind, sha = _object(ref.get("object"))
    for depth in range(MAX_TAG_DEPTH + 1):
        if kind == "commit":
            return sha
        if depth == MAX_TAG_DEPTH:
            raise ValueError("annotated tag depth exceeds the limit")
        tag_document = _json(f"{API_ROOT}/git/tags/{quote(sha, safe='')}")
        kind, sha = _object(tag_document.get("object"))
    raise ValueError("git tag did not resolve to a commit")


def latest_release() -> Release:
    metadata = _json(LATEST_URL)
    tag = _tag(metadata.get("tag_name"))
    if metadata.get("draft") is not False or metadata.get("prerelease") is not False:
        raise ValueError("latest GitHub release is not a stable published release")
    published_at = metadata.get("published_at")
    if not isinstance(published_at, str) or not published_at.strip():
        raise ValueError("latest GitHub release is not published")
    return Release(tag, _commit_for_tag(tag))


def _member_parts(name: object) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("archive member path is invalid")
    if name.startswith("/") or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive:
        raise ValueError("archive member path is absolute")
    parts = name.split("/")
    while parts and parts[-1] == "":
        parts.pop()
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("archive member path contains traversal")
    return tuple(parts)


def _member_kind(info: tarfile.TarInfo) -> bool:
    if info.size < 0 or info.size > MAX_MEMBER_BYTES:
        raise ValueError("release archive member exceeds the size limit")
    if info.issym() or info.islnk() or not (info.isdir() or info.isreg()):
        raise ValueError("release archive contains an unsupported member type")
    return info.isdir()


def _check_parent_types(seen: set[tuple[str, ...]], kinds: dict[tuple[str, ...], bool]) -> None:
    for parts in seen:
        for index in range(1, len(parts)):
            parent = parts[:index]
            if parent in kinds and not kinds[parent]:
                raise ValueError("release archive has a file as a directory")


def _plan_members(infos: list[tarfile.TarInfo]) -> _Archive:
    root: str | None = None
    seen: set[tuple[str, ...]] = set()
    kinds: dict[tuple[str, ...], bool] = {}
    planned: list[_Member] = []
    total = 0
    for info in infos:
        parts = _member_parts(info.name)
        if root is None:
            root = parts[0]
        elif parts[0] != root:
            raise ValueError("release archive has multiple roots")
        if parts in seen:
            raise ValueError("release archive contains duplicate paths")
        seen.add(parts)
        is_directory = _member_kind(info)
        kinds[parts] = is_directory
        if not is_directory:
            total += info.size
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("release archive exceeds the extracted size limit")
        planned.append(_Member(info, parts))
    if root is None:
        raise ValueError("release archive is empty")
    _check_parent_types(seen, kinds)
    return _Archive(root, tuple(planned))


def _decompressed_tar(data: bytes) -> bytes:
    body = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            while True:
                chunk = stream.read(min(READ_CHUNK_BYTES, MAX_TAR_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_TAR_BYTES:
                    raise ValueError("release archive exceeds the decompressed size limit")
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("release archive is not a valid gzip archive") from error
    return bytes(body)


def _archive_plan(data: bytes) -> _Archive:
    try:
        bundle = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ValueError("release archive is not a valid tar archive") from error
    with bundle:
        infos: list[tarfile.TarInfo] = []
        seen: set[tuple[str, ...]] = set()
        root: str | None = None
        total = 0
        try:
            for index in range(MAX_MEMBERS + 1):
                info = bundle.next()
                if info is None:
                    break
                if index >= MAX_MEMBERS:
                    raise ValueError("release archive has too many members")
                parts = _member_parts(info.name)
                if root is None:
                    root = parts[0]
                elif parts[0] != root:
                    raise ValueError("release archive has multiple roots")
                if parts in seen:
                    raise ValueError("release archive contains duplicate paths")
                seen.add(parts)
                if not _member_kind(info):
                    total += info.size
                    if total > MAX_EXTRACTED_BYTES:
                        raise ValueError("release archive exceeds the extracted size limit")
                infos.append(info)
        except (tarfile.TarError, OSError, EOFError) as error:
            raise ValueError("release archive members could not be read") from error
        return _plan_members(infos)


def _required_contents(bundle: tarfile.TarFile, archive: _Archive) -> dict[str, bytes]:
    by_path = {"/".join(member.parts[1:]): member for member in archive.members if len(member.parts) > 1}
    contents: dict[str, bytes] = {}
    for name in REQUIRED_FILES:
        member = by_path.get(name)
        if member is None or not member.info.isreg():
            raise ValueError(f"release archive is missing required file {name}")
        stream = bundle.extractfile(member.info)
        if stream is None:
            raise ValueError(f"release archive could not read required file {name}")
        with stream:
            body = stream.read(MAX_MEMBER_BYTES + 1)
        if len(body) != member.info.size:
            raise ValueError(f"release archive required file {name} is truncated")
        contents[name] = body
    return contents


def _validate_release_files(contents: dict[str, bytes], tag: str) -> None:
    try:
        manifest = json.loads(contents[".claude-plugin/plugin.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("release plugin manifest is invalid") from error
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN_NAME:
        raise ValueError("release plugin name is invalid")
    try:
        readme = contents["README.md"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("release README is not UTF-8") from error
    expected = tag[1:]
    match = README_RELEASE_RE.search(readme)
    if match is None or match.group(1) != expected:
        raise ValueError("release README version does not match the tag")


def _destination_state(destination: Path) -> bool:
    if destination.is_symlink():
        raise ValueError("release destination must not be a symlink")
    if destination.exists():
        metadata = destination.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("release destination must be a directory")
        if metadata.st_uid != getattr(os, "getuid", lambda: metadata.st_uid)():
            raise ValueError("release destination is not owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("release destination must be private")
        if any(destination.iterdir()):
            raise ValueError("release destination must be empty")
        return True
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("release destination parent is invalid")
    return False


def _safe_file_mode(info: tarfile.TarInfo) -> int:
    return 0o755 if info.mode & 0o111 else 0o644


def _remove_created(paths: list[Path]) -> None:
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            pass


def _ensure_directory(path: Path, destination: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    current = path
    while current != destination and not current.exists():
        missing.append(current)
        current = current.parent
    if current != destination and (current.is_symlink() or not current.is_dir()):
        raise ValueError("release archive output parent is invalid")
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        created.append(directory)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("release archive output parent is invalid")
    if path != destination:
        os.chmod(path, 0o755)


def _extract_directory(target: Path, destination: Path, created: list[Path]) -> None:
    _ensure_directory(target, destination, created)


def _extract_file(
    bundle: tarfile.TarFile,
    member: _Member,
    target: Path,
    destination: Path,
    created: list[Path],
) -> None:
    _ensure_directory(target.parent, destination, created)
    stream = bundle.extractfile(member.info)
    if stream is None:
        raise ValueError("release archive member cannot be read")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    copied = 0
    with stream:
        descriptor = os.open(target, flags, 0o600)
        try:
            created.append(target)
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                while True:
                    chunk = stream.read(min(READ_CHUNK_BYTES, member.info.size - copied + 1))
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > member.info.size:
                        raise ValueError("release archive member exceeds its declared size")
                    output.write(chunk)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    if copied != member.info.size:
        raise ValueError("release archive member is truncated")
    os.chmod(target, _safe_file_mode(member.info))


def _extract(bundle: tarfile.TarFile, archive: _Archive, destination: Path) -> None:
    created: list[Path] = []
    try:
        for member in archive.members:
            relative = member.parts[1:]
            if not relative:
                continue
            target = destination.joinpath(*relative)
            if member.info.isdir():
                _extract_directory(target, destination, created)
            else:
                _extract_file(bundle, member, target, destination, created)
    except BaseException:
        _remove_created(created)
        raise


def stage_release(release: Release, destination: Path) -> None:
    if not isinstance(release, Release):
        raise ValueError("release has the wrong type")
    tag = _tag(release.tag)
    commit = _sha(release.commit, "release commit")
    destination = Path(destination)
    existed = _destination_state(destination)
    archive_bytes = _get_bytes(
        f"{ARCHIVE_ROOT}/{commit}", MAX_ARCHIVE_BYTES, "application/gzip",
    )
    if not isinstance(archive_bytes, bytes) or len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("release archive exceeds the size limit")
    archive_bytes = _decompressed_tar(archive_bytes)
    archive = _archive_plan(archive_bytes)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as bundle:
            contents = _required_contents(bundle, archive)
            _validate_release_files(contents, tag)
            if not existed:
                destination.mkdir(mode=0o700)
            _destination_state(destination)
            _extract(bundle, archive, destination)
    except BaseException:
        if not existed and destination.exists():
            _remove_created(list(destination.iterdir()))
            try:
                destination.rmdir()
            except OSError:
                pass
        raise
