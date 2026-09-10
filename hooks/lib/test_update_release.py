from __future__ import annotations

import gzip
import io
import json
import os
import stat
import tarfile
import types
import urllib.request
from pathlib import Path

import pytest

from lib import update_release


COMMIT = "a" * 40
TAG = "v1.2.3"
ROOT = "agent-discipline-watcher-" + COMMIT


class Response:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        self.body = body
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        pass

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _release_json(**overrides: object) -> bytes:
    payload = {
        "tag_name": TAG,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _ref_json(kind: str = "commit", sha: str = COMMIT) -> bytes:
    return json.dumps({"object": {"type": kind, "sha": sha}}).encode()


def _tag_json(kind: str = "commit", sha: str = COMMIT) -> bytes:
    return json.dumps({"object": {"type": kind, "sha": sha}}).encode()


def _archive(
    *,
    files: dict[str, bytes] | None = None,
    modes: dict[str, int] | None = None,
    entries: list[tuple[str, str, bytes | None]] | None = None,
) -> bytes:
    defaults = {
        "install.sh": b"#!/bin/sh\n",
        "hosts/claude/install.sh": b"#!/bin/sh\n",
        "hosts/codex/install.sh": b"#!/bin/sh\n",
        "hosts/omp/install.sh": b"#!/bin/sh\n",
        ".claude-plugin/plugin.json": b'{"name":"agent-discipline-watcher"}\n',
        "README.md": b"# Agent Discipline Watcher\nCurrent release: **1.2.3**\n",
    }
    defaults.update(files or {})
    files = defaults
    modes = modes or {}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        root = tarfile.TarInfo(ROOT + "/")
        root.type = tarfile.DIRTYPE
        bundle.addfile(root)
        for name, content in files.items():
            path = ROOT + "/" + name
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = modes.get(name, 0o644)
            bundle.addfile(info, io.BytesIO(content))
        for name, kind, link in entries or []:
            info = tarfile.TarInfo(ROOT + "/" + name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = str(link or "target")
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = str(link or "target")
            else:
                info.type = tarfile.FIFOTYPE
            bundle.addfile(info)
    return output.getvalue()


def test_latest_release_resolves_a_lightweight_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([Response(_release_json()), Response(_ref_json())])
    seen: list[str] = []

    def fake_get(url: str, _limit: int, _accept: str) -> bytes:
        seen.append(url)
        return next(responses).body

    monkeypatch.setattr(update_release, "_get_bytes", fake_get)

    assert update_release.latest_release() == update_release.Release(TAG, COMMIT)
    assert seen[0].endswith("/releases/latest")
    assert seen[1].endswith("/git/ref/tags/v1.2.3")


def test_latest_release_peels_annotated_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    tag_sha = "b" * 40
    responses = iter([Response(_release_json()), Response(_ref_json("tag", tag_sha)), Response(_tag_json())])
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: next(responses).body)

    assert update_release.latest_release().commit == COMMIT


@pytest.mark.parametrize("payload", [
    {"tag_name": "main", "draft": False, "prerelease": False, "published_at": "x"},
    {"tag_name": "v1.2.3", "draft": True, "prerelease": False, "published_at": "x"},
    {"tag_name": "v1.2.3", "draft": False, "prerelease": True, "published_at": "x"},
    {"tag_name": "v1.2.3", "draft": False, "prerelease": False, "published_at": None},
])
def test_latest_release_rejects_unpublished_or_unstable_metadata(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, object],
) -> None:
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: json.dumps(payload).encode())

    with pytest.raises(ValueError):
        update_release.latest_release()


def test_latest_release_rejects_a_non_commit_after_four_tag_hops(monkeypatch: pytest.MonkeyPatch) -> None:
    tag_sha = "b" * 40
    responses = [Response(_release_json()), Response(_ref_json("tag", tag_sha))]
    responses.extend(Response(_tag_json("tag", tag_sha)) for _ in range(4))
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: responses.pop(0).body)

    with pytest.raises(ValueError, match="tag depth"):
        update_release.latest_release()


def test_get_bytes_uses_fixed_https_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    context = object()

    class Opener:  # pylint: disable=too-few-public-methods
        def open(self, request: urllib.request.Request, timeout: float) -> Response:
            captured["request"] = request
            captured["timeout"] = timeout
            return Response(b"ok")

    def fake_build_opener(*handlers: object) -> Opener:
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(update_release, "_tls_context", lambda: context)
    monkeypatch.setattr(update_release.urllib.request, "build_opener", fake_build_opener)

    assert update_release._get_bytes("https://api.github.com/test", 10, "application/json") == b"ok"
    request = captured["request"]
    handlers = captured["handlers"]
    assert isinstance(request, urllib.request.Request)
    assert request.get_header("Accept") == "application/json"
    assert captured["timeout"] == update_release.HTTP_TIMEOUT
    assert any(isinstance(handler, urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers)
    assert any(isinstance(handler, urllib.request.HTTPSHandler) and handler._context is context for handler in handlers)
    assert any(isinstance(handler, update_release._RedirectHandler) for handler in handlers)


def test_get_bytes_rejects_non_allowlisted_urls() -> None:
    with pytest.raises(ValueError, match="HTTPS allowlist"):
        update_release._get_bytes("https://example.com/release", 10, "application/octet-stream")
    with pytest.raises(ValueError, match="HTTPS allowlist"):
        update_release._get_bytes("http://api.github.com/release", 10, "application/octet-stream")


def test_tls_context_uses_compiled_default_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    paths = types.SimpleNamespace(openssl_cafile="/compiled/ca.pem", openssl_capath="/compiled/certs")

    def fake_create_default_context(**kwargs: object) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setenv("SSL_CERT_FILE", "/caller/ca.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/caller/certs")
    monkeypatch.setattr(update_release.ssl, "get_default_verify_paths", lambda: paths)
    monkeypatch.setattr(update_release.ssl, "create_default_context", fake_create_default_context)

    update_release._tls_context()

    assert seen == {"cafile": "/compiled/ca.pem", "capath": "/compiled/certs"}


def test_redirect_handler_rejects_a_host_escape() -> None:
    handler = update_release._RedirectHandler()
    request = urllib.request.Request("https://api.github.com/releases/latest")

    with pytest.raises(ValueError, match="HTTPS allowlist"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/release")


def test_archive_member_bounds_are_checked_before_advancing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update_release, "MAX_MEMBER_BYTES", 3)
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(files={"install.sh": b"1234"}))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="member exceeds"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert list(destination.iterdir()) == []


def test_archive_member_count_is_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update_release, "MAX_MEMBERS", 1)
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive())
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="too many members"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert list(destination.iterdir()) == []


def test_extracted_size_is_bounded_before_extraction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update_release, "MAX_EXTRACTED_BYTES", 10)
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive())
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="extracted size"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert list(destination.iterdir()) == []


def test_stage_release_strips_one_archive_root_and_keeps_exec_bits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    archive = _archive(modes={"install.sh": 0o755})
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: archive)
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    update_release.stage_release(update_release.Release(TAG, COMMIT), destination)

    assert (destination / "install.sh").read_bytes() == b"#!/bin/sh\n"
    assert stat.S_IMODE((destination / "install.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert not (destination / ROOT).exists()


def test_stage_release_rejects_a_nonempty_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive())
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)
    (destination / "keep").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


@pytest.mark.parametrize("entries", [
    [("link", "symlink", "install.sh")],
    [("hard", "hardlink", "install.sh")],
    [("fifo", "fifo", None)],
])
def test_stage_release_rejects_non_regular_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, entries: list[tuple[str, str, bytes | None]],
) -> None:
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(entries=entries))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="member type"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


@pytest.mark.parametrize("name", ["../outside", "/absolute", ROOT + "/../outside"])
def test_stage_release_rejects_traversal_and_absolute_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str,
) -> None:
    files = {name: b"bad"}
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(files=files))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="path"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


def test_stage_release_rejects_duplicate_members(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for _ in range(2):
            info = tarfile.TarInfo(ROOT + "/install.sh")
            info.size = 1
            bundle.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: output.getvalue())
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="duplicate"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


def test_stage_release_rejects_multiple_archive_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for root in (ROOT, "other-root"):
            info = tarfile.TarInfo(root + "/install.sh")
            info.size = 1
            bundle.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: output.getvalue())
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="root"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


def test_stage_release_rejects_wrong_plugin_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    files = {".claude-plugin/plugin.json": b'{"name":"other"}\n'}
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(files=files))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="plugin name"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


def test_stage_release_rejects_a_readme_version_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    files = {"README.md": b"Current release: **9.9.9**\n"}
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(files=files))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="README"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)


def test_stage_release_rejects_an_oversized_archive_before_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: b"x" * (update_release.MAX_ARCHIVE_BYTES + 1))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="archive"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert list(destination.iterdir()) == []


def test_stage_release_does_not_execute_extracted_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    files = {"install.sh": f"#!/bin/sh\ntouch {marker}\n".encode()}
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: _archive(files=files))
    destination = tmp_path / "stage"
    destination.mkdir(mode=0o700)

    update_release.stage_release(update_release.Release(TAG, COMMIT), destination)

    assert not marker.exists()


def _metadata_archive(kind: bytes) -> bytes:
    value = b"comment=" + b"x" * 16384 + b"\n"
    length = len(value) + 2
    while length != len(str(length)) + len(value) + 1:
        length = len(str(length)) + len(value) + 1
    body = str(length).encode() + b" " + value
    if kind in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
        body = ROOT.encode() + b"/" + b"x" * 16384 + b"\x00"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as bundle:
        metadata = tarfile.TarInfo(ROOT + "/metadata")
        metadata.type = kind
        metadata.size = len(body)
        bundle.addfile(metadata, io.BytesIO(body))
        bundle.addfile(tarfile.TarInfo(ROOT + "/file"), io.BytesIO())
    return gzip.compress(output.getvalue())


@pytest.mark.parametrize("kind", [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK])
def test_compressed_extended_headers_are_bounded_before_tar_parsing(monkeypatch, tmp_path, kind):
    archive = _metadata_archive(kind)
    assert len(archive) < 4096
    monkeypatch.setattr(update_release, "MAX_TAR_BYTES", 4096, raising=False)
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: archive)

    def forbidden_parse(*args, **kwargs):
        pytest.fail("compressed metadata reached the tar parser before the expansion limit")

    monkeypatch.setattr(update_release.tarfile, "open", forbidden_parse)
    destination = tmp_path / "stage"
    with pytest.raises(ValueError, match="decompressed size"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert not destination.exists()


def test_concatenated_gzip_members_share_the_tar_expansion_budget(monkeypatch, tmp_path):
    archive = _archive() + gzip.compress(b"x" * 32768)
    monkeypatch.setattr(update_release, "MAX_TAR_BYTES", 16384, raising=False)
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: archive)
    destination = tmp_path / "stage"
    with pytest.raises(ValueError, match="decompressed size"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert not destination.exists()


@pytest.mark.parametrize("failure", ["fdopen", "tracking"])
def test_extract_file_closes_handles_when_output_setup_fails(monkeypatch, tmp_path, failure):
    class FailingList(list):
        def append(self, value):
            raise RuntimeError("output setup failed")

    target = tmp_path / "output"
    descriptor = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
    source = io.BytesIO(b"content")
    bundle = types.SimpleNamespace(extractfile=lambda info: source)
    info = tarfile.TarInfo(ROOT + "/output")
    info.size = 7
    member = update_release._Member(info, (ROOT, "output"))
    monkeypatch.setattr(update_release.os, "open", lambda *args: descriptor)

    def failed_fdopen(*args):
        raise RuntimeError("output setup failed")

    if failure == "fdopen":
        monkeypatch.setattr(update_release.os, "fdopen", failed_fdopen)
    try:
        with pytest.raises(RuntimeError, match="output setup"):
            update_release._extract_file(bundle, member, target, tmp_path, FailingList() if failure == "tracking" else [])
        with pytest.raises(OSError):
            os.fstat(descriptor)
        assert source.closed
    finally:
        source.close()
        try:
            os.close(descriptor)
        except OSError:
            pass
