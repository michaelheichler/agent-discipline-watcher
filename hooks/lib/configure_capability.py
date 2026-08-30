"""Write authorisation for the configuration bridge, kept apart because a token check is not policy."""
from __future__ import annotations

import fcntl
import hmac
import os
import pwd
import shlex
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    from .configure_policy import MAX_CWD_CHARS, ConfigureError
except ImportError:
    from configure_policy import MAX_CWD_CHARS, ConfigureError

CAPABILITY_ENV = "ADW_CONFIG_CAPABILITY"
CAPABILITY_FILE_ENV = "ADW_CONFIG_CAPABILITY_FILE"
MAX_CAPABILITY_BYTES = 4096
TRUSTED_EXECUTABLES = frozenset({"omp", "pi"})
LAUNCHER_SUFFIXES = (".bun/bin/omp", ".bun/bin/pi")


def _refuse() -> ConfigureError:
    return ConfigureError("capability_required", "write requires the OMP capability")


def read_parent_process(parent_pid: str, output_format: str) -> str | None:
    """Call the fixed system binary because a PATH lookup would let a shim impersonate ps."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", parent_pid, "-o", output_format],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _expected_launchers() -> set[Path]:
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return set()
    return {(account_home / suffix).resolve() for suffix in LAUNCHER_SUFFIXES}


def _resolves_to_launcher(argument: str, expected: set[Path]) -> bool:
    candidate = Path(argument)
    if not candidate.is_absolute():
        return False
    try:
        return candidate.resolve() in expected
    except (OSError, RuntimeError):
        return False


def _bun_runs_omp(command_line: str) -> bool:
    try:
        arguments = shlex.split(command_line)
    except ValueError:
        return False
    expected = _expected_launchers()
    return any(_resolves_to_launcher(argument, expected) for argument in arguments[1:])


def omp_parent_is_trusted() -> bool:
    """Check the parent because a leaked token alone would let any process rewrite policy."""
    parent_pid = str(os.getppid())
    executable_text = read_parent_process(parent_pid, "comm=")
    if executable_text is None:
        return False
    executable = Path(executable_text).name.lower()
    if executable in TRUSTED_EXECUTABLES:
        return True
    if executable != "bun":
        return False
    return _bun_runs_omp(read_parent_process(parent_pid, "command=") or "")


def _token_and_path() -> tuple[str, str]:
    token = os.environ.get(CAPABILITY_ENV, "")
    path_text = os.environ.get(CAPABILITY_FILE_ENV, "")
    if not isinstance(token, str) or not token.strip() or len(token) > MAX_CAPABILITY_BYTES:
        raise _refuse()
    if not isinstance(path_text, str) or not path_text or len(path_text) > MAX_CWD_CHARS:
        raise _refuse()
    return token, path_text


def _check_parent_directory(capability_path: Path, owner: int) -> None:
    parent_stat = capability_path.parent.stat()
    if parent_stat.st_uid != owner or parent_stat.st_mode & 0o022:
        raise _refuse()


def _check_leaf(stream, capability_path: Path, owner: int) -> None:
    metadata = os.fstat(stream.fileno())
    path_metadata = os.stat(capability_path, follow_symlinks=False)
    if path_metadata.st_dev != metadata.st_dev or path_metadata.st_ino != metadata.st_ino:
        raise _refuse()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != owner:
        raise _refuse()
    if metadata.st_mode & 0o077 or metadata.st_nlink != 1:
        raise _refuse()


@contextmanager
def _capability_lock(capability_path: Path) -> Iterator[None]:
    descriptor = os.open(
        Path(f"{capability_path}.lock"),
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "r+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _verify_and_unlink(capability_path: Path, token: str, owner: int) -> None:
    capability_fd = os.open(capability_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(capability_fd, "rb") as stream:
        _check_leaf(stream, capability_path, owner)
        body = stream.read(MAX_CAPABILITY_BYTES + 1)
    if len(body) > MAX_CAPABILITY_BYTES or not hmac.compare_digest(body, token.encode("utf-8")):
        raise _refuse()
    os.unlink(capability_path)


def consume_capability() -> None:
    """Spend the token once because a replayed token would reopen the write path forever."""
    token, path_text = _token_and_path()
    if not omp_parent_is_trusted():
        raise _refuse()
    capability_path = Path(path_text)
    if not capability_path.is_absolute():
        raise _refuse()
    owner = os.getuid()
    try:
        _check_parent_directory(capability_path, owner)
        with _capability_lock(capability_path):
            _verify_and_unlink(capability_path, token, owner)
    except (OSError, UnicodeEncodeError) as exc:
        raise _refuse() from exc
