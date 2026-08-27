"""Fetches the embedding artifacts into the watcher home, because a release that assumes a server is already running is not standalone."""
from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    from .model_artifacts import Artifact, ArchiveRuntime, ModelPlatform, PythonRuntime
except ImportError:
    from model_artifacts import Artifact, ArchiveRuntime, ModelPlatform, PythonRuntime

PARTIAL_SUFFIX = ".partial"
LOCK_SUFFIX = ".lock"
DOWNLOAD_ATTEMPTS = 3
CHUNK_BYTES = 1 << 20
REQUEST_TIMEOUT = 60
PARTIAL_STATUS = 206
RUNTIME_DIRNAME = "runtime"
VENV_DIRNAME = "venv"
PIP_TIMEOUT = 1800


def _digest(path: Path) -> str:
    reader = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            reader.update(chunk)
    return reader.hexdigest()


def verified(path: Path, artifact: Artifact) -> bool:
    return path.is_file() and path.stat().st_size == artifact.size and _digest(path) == artifact.sha256


@contextmanager
def exclusive(lock_path: Path) -> Iterator[None]:
    """Blocks rather than racing, because two sessions starting the same gigabyte download would both finish and both lose."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _opened(url: str, offset: int):
    request = urllib.request.Request(url)
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)


def _copy(response, sink) -> None:
    for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
        sink.write(chunk)


def _stream(url: str, partial: Path, offset: int) -> None:
    with _opened(url, offset) as response:
        mode = "ab" if response.status == PARTIAL_STATUS else "wb"
        with partial.open(mode) as sink:
            _copy(response, sink)


def _resume_offset(partial: Path, artifact: Artifact) -> int:
    if not partial.is_file():
        return 0
    size = partial.stat().st_size
    return size if size < artifact.size else 0


def _attempt(artifact: Artifact, destination: Path) -> None:
    partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
    _stream(artifact.url, partial, _resume_offset(partial, artifact))
    if not verified(partial, artifact):
        partial.unlink(missing_ok=True)
        raise ValueError(
            f"{artifact.name}: downloaded {partial.stat().st_size if partial.exists() else 0} bytes "
            f"that do not match the pinned sha256 {artifact.sha256}"
        )
    os.replace(partial, destination)


def _attempted(artifact: Artifact, destination: Path, attempt: int) -> Exception | None:
    try:
        _attempt(artifact, destination)
        return None
    except (ValueError, OSError, urllib.error.URLError) as error:
        sys.stderr.write(f"agent-discipline-watcher: {artifact.name} attempt {attempt} failed: {error}\n")
        return error


def download(artifact: Artifact, destination: Path) -> None:
    """Retries because a truncated body is ordinary on a long transfer, and raises the last error because a wrong digest must never be executed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    failure: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        failure = _attempted(artifact, destination, attempt)
        if failure is None:
            return
    raise failure


def ensure_artifact(artifact: Artifact, directory: Path) -> Path:
    destination = directory / artifact.name
    if verified(destination, artifact):
        return destination
    with exclusive(directory / (artifact.name + LOCK_SUFFIX)):
        if not verified(destination, artifact):
            download(artifact, destination)
    return destination


def weights_root(entry: ModelPlatform, root: Path) -> Path:
    return root / entry.key / "weights"


def runtime_root(entry: ModelPlatform, root: Path) -> Path:
    return root / entry.key / RUNTIME_DIRNAME


def ensure_weights(entry: ModelPlatform, root: Path) -> Path:
    directory = weights_root(entry, root)
    for artifact in entry.weights:
        ensure_artifact(artifact, directory)
    return directory


def _extract(archive: Path, directory: Path) -> None:
    """Extracts member by member under the data filter because a release tarball is third-party content and extractall would trust its paths."""
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            bundle.extract(member, directory, filter="data")


def _ensure_archive_runtime(runtime: ArchiveRuntime, directory: Path) -> Path:
    server = directory / runtime.server
    if server.is_file():
        return server
    with exclusive(directory.parent / (runtime.archive.name + LOCK_SUFFIX)):
        if not server.is_file():
            _extract(ensure_artifact(runtime.archive, directory), directory)
    if not server.is_file():
        raise ValueError(f"{runtime.archive.name}: archive carries no {runtime.server}")
    server.chmod(0o755)
    return server


def _pip(venv: Path, arguments: tuple[str, ...]) -> None:
    result = subprocess.run(
        (str(venv / "bin" / "python"), "-m", "pip", *arguments),
        capture_output=True, text=True, timeout=PIP_TIMEOUT, check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"pip {' '.join(arguments)} failed with {result.returncode}: {result.stderr.strip()}")


def _ensure_python_runtime(runtime: PythonRuntime, directory: Path) -> Path:
    interpreter = directory / VENV_DIRNAME / "bin" / "python"
    if interpreter.is_file():
        return interpreter
    with exclusive(directory.parent / (VENV_DIRNAME + LOCK_SUFFIX)):
        if not interpreter.is_file():
            subprocess.run(
                (sys.executable, "-m", "venv", str(directory / VENV_DIRNAME)),
                capture_output=True, text=True, timeout=PIP_TIMEOUT, check=True,
            )
            _pip(directory / VENV_DIRNAME, ("install", "--quiet", *runtime.requirements))
    return interpreter


def ensure_runtime(entry: ModelPlatform, root: Path) -> Path:
    directory = runtime_root(entry, root)
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(entry.runtime, ArchiveRuntime):
        return _ensure_archive_runtime(entry.runtime, directory)
    return _ensure_python_runtime(entry.runtime, directory)
