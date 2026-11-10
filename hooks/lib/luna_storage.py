"""Descriptors rather than paths, because a path re-resolved after its check can point somewhere else."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path

try:
    from . import config_roots as config_paths
except ImportError:
    import config_roots as config_paths

try:
    from . import state_recovery
except ImportError:
    import state_recovery
import secrets
import stat
from typing import Iterator


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_LEAF_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class LunaProviderFailure(RuntimeError):
    """Carry a category because a caller must tell a missing login from a broken worker."""

    def __init__(self, message: str, *, category: str = "provider") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class RuntimePaths:
    """Pin descriptors beside paths because a path alone cannot prove the directory never moved."""

    codex_home: Path
    cwd: Path
    call_fd: int | None = None
    codex_home_fd: int | None = None
    cwd_fd: int | None = None
    call_identity: tuple[int, int] | None = None
    codex_home_identity: tuple[int, int] | None = None
    cwd_identity: tuple[int, int] | None = None


class SecureJudgeStorage:
    """One open scope per judge call, because a descriptor reopened later cannot prove the same directory."""

    def __init__(
        self,
        *,
        runtime_root: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        if (runtime_root is None) != (cache_root is None):
            raise ValueError("runtime_root and cache_root must be supplied together")
        if runtime_root is None:
            self.runtime_path = config_paths.data_root() / "runtime"
            self.cache_path = config_paths.data_root() / "cache" / "judges"
            self._trusted_path = config_paths.home_root()
            self._runtime_parts = (".adw", "runtime")
            self._cache_parts = (".adw", "cache", "judges")
        else:
            self._custom_roots(runtime_root, cache_root)
        self._trusted_fd: int | None = None
        self._runtime_fd: int | None = None
        self._cache_fd: int | None = None

    def _custom_roots(self, runtime_root: Path, cache_root: Path) -> None:
        self.runtime_path = Path(os.path.abspath(runtime_root))
        self.cache_path = Path(os.path.abspath(cache_root))
        common = Path(os.path.commonpath((self.runtime_path, self.cache_path)))
        if common in (self.runtime_path, self.cache_path):
            common = common.parent
        self._trusted_path = common
        self._runtime_parts = self.runtime_path.relative_to(common).parts
        self._cache_parts = self.cache_path.relative_to(common).parts

    def __enter__(self) -> SecureJudgeStorage:
        try:
            trusted = os.open(self._trusted_path, _DIRECTORY_FLAGS)
            _require_directory_fd(trusted, str(self._trusted_path))
            self._trusted_fd = trusted
            self._runtime_fd = _mkdir_open_chain(trusted, self._runtime_parts)
            self._cache_fd = _mkdir_open_chain(trusted, self._cache_parts)
            return self
        except LunaProviderFailure:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise LunaProviderFailure(
                f"unsafe Luna storage directory: {exc.filename or self._trusted_path}"
            ) from exc

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def close(self) -> None:
        for attribute in ("_cache_fd", "_runtime_fd", "_trusted_fd"):
            descriptor = getattr(self, attribute)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, attribute, None)

    @contextmanager
    def runtime(self, *, config_text: str, auth_source: Path) -> Iterator[RuntimePaths]:
        runtime_fd = self._require_fd(self._runtime_fd)
        call_name, call_fd = _create_random_directory(runtime_fd)
        home_fd = -1
        cwd_fd = -1
        try:
            home_fd = _mkdir_open_chain(call_fd, ("home",))
            cwd_fd = _mkdir_open_chain(call_fd, ("cwd",))
            _atomic_write(home_fd, "config.toml", config_text)
            _link_verified_auth(auth_source, home_fd)
            call_path = self.runtime_path / call_name
            os.fchmod(call_fd, 0o500)
            yield RuntimePaths(
                codex_home=call_path / "home", cwd=call_path / "cwd",
                call_fd=call_fd, codex_home_fd=home_fd, cwd_fd=cwd_fd,
                call_identity=_directory_identity(call_fd),
                codex_home_identity=_directory_identity(home_fd),
                cwd_identity=_directory_identity(cwd_fd),
            )
        finally:
            _cleanup_runtime((cwd_fd, home_fd, call_fd))
            _remove_tree_at(runtime_fd, call_name)

    def read_cache(self, name: str) -> tuple[str, os.stat_result] | None:
        cache_fd = self._require_fd(self._cache_fd)
        _validate_leaf_name(name)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_NOFOLLOW, dir_fd=cache_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LunaProviderFailure(f"unsafe Luna cache leaf {name}: expected a regular file") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise LunaProviderFailure(f"unsafe Luna cache leaf {name}: expected a regular file")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                return handle.read(), metadata
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def write_cache(self, name: str, text: str) -> None:
        _atomic_write(self._require_fd(self._cache_fd), name, text)

    def unlink_cache(self, name: str) -> None:
        cache_fd = self._require_fd(self._cache_fd)
        _validate_regular_or_absent(cache_fd, name)
        try:
            os.unlink(name, dir_fd=cache_fd)
        except FileNotFoundError:
            pass

    @staticmethod
    def _require_fd(descriptor: int | None) -> int:
        if descriptor is None:
            raise RuntimeError("secure Luna storage is not open")
        return descriptor


def _cleanup_runtime(descriptors: tuple[int, int, int]) -> None:
    try:
        os.fchmod(descriptors[-1], 0o700)
    except OSError:
        pass
    for descriptor in descriptors:
        if descriptor >= 0:
            _remove_directory_contents(descriptor)
            os.close(descriptor)


def _validate_leaf_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise LunaProviderFailure("unsafe Luna storage leaf name")


def _require_directory_fd(descriptor: int, label: str) -> None:
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        raise LunaProviderFailure(f"unsafe Luna storage directory: {label}")


def _directory_identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise LunaProviderFailure("unsafe Luna runtime descriptor: expected a directory")
    return metadata.st_dev, metadata.st_ino


def _mkdir_open_child(parent_fd: int, name: str) -> int:
    _validate_leaf_name(name)
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        child = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise LunaProviderFailure(f"unsafe symlink or non-directory Luna storage directory: {name}") from exc
    try:
        _require_directory_fd(child, name)
    except BaseException:
        os.close(child)
        raise
    return child


def _mkdir_open_chain(parent_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(parent_fd)
    try:
        for part in parts:
            child = _mkdir_open_child(descriptor, part)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_created_directory(parent_fd: int, name: str) -> int:
    descriptor = -1
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        _require_directory_fd(descriptor, name)
        return descriptor
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        _rmdir_quietly(parent_fd, name)
        raise


def _rmdir_quietly(parent_fd: int, name: str) -> None:
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        pass


def _create_random_directory(parent_fd: int) -> tuple[str, int]:
    for _attempt in range(32):
        name = f"luna-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        return name, _open_created_directory(parent_fd, name)
    raise LunaProviderFailure("could not allocate an isolated Luna runtime")


def _validate_regular_or_absent(parent_fd: int, name: str) -> None:
    _validate_leaf_name(name)
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise LunaProviderFailure(f"unsafe Luna storage leaf {name}: expected a regular file")


def _atomic_write(parent_fd: int, name: str, text: str) -> None:
    _validate_regular_or_absent(parent_fd, name)
    try:
        with state_recovery.atomic_open(
            Path(name), parent_fd=parent_fd, sync=True,
            before_replace=lambda: _validate_regular_or_absent(parent_fd, name),
        ) as stream:
            stream.write(text)
    except state_recovery.TemporaryExhausted as error:
        raise LunaProviderFailure("could not allocate a Luna storage temporary file") from error


def _unlink_quietly(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except OSError:
        pass


def _link_auth_at(source_fd: int, name: str, destination_fd: int) -> None:
    try:
        captured = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(captured.st_mode):
        raise LunaProviderFailure("Codex authentication source must be a regular file")
    os.link(name, "auth.json", src_dir_fd=source_fd, dst_dir_fd=destination_fd, follow_symlinks=False)
    linked = os.stat("auth.json", dir_fd=destination_fd, follow_symlinks=False)
    if not stat.S_ISREG(linked.st_mode) or (linked.st_dev, linked.st_ino) != (captured.st_dev, captured.st_ino):
        _unlink_quietly(destination_fd, "auth.json")
        raise LunaProviderFailure("Codex authentication source changed while linking")


def _link_verified_auth(source: Path, destination_fd: int) -> None:
    try:
        source_fd = os.open(source.parent, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LunaProviderFailure("unsafe Codex authentication source directory") from exc
    try:
        _link_auth_at(source_fd, source.name, destination_fd)
    finally:
        os.close(source_fd)


def _unlink_missing_ok(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass


def _remove_entries(descriptor: int, entries) -> None:
    for entry in entries:
        try:
            metadata = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(metadata.st_mode):
            _remove_tree_at(descriptor, entry.name)
        else:
            _unlink_missing_ok(descriptor, entry.name)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    except OSError:
        _unlink_quietly(parent_fd, name)
        return
    try:
        with os.scandir(descriptor) as entries:
            _remove_entries(descriptor, entries)
    finally:
        os.close(descriptor)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass


def _remove_directory_contents(descriptor: int) -> None:
    """Reached through the owned descriptor, because a path walk here would follow a symlink planted mid-call."""
    try:
        entries = tuple(os.scandir(descriptor))
    except OSError:
        return
    _remove_entries(descriptor, entries)
