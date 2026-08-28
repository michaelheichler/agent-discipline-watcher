"""Descriptor-owned storage for the Luna judge boundary."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
from typing import Iterator


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_LEAF_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class LunaProviderFailure(RuntimeError):
    """A safe, user-facing Luna provider failure."""

    def __init__(self, message: str, *, category: str = "provider") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class RuntimePaths:
    codex_home: Path
    cwd: Path


class SecureJudgeStorage:
    """Hold trusted directory descriptors for one complete judge call."""

    def __init__(
        self,
        *,
        runtime_root: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        if runtime_root is None and cache_root is None:
            self.runtime_path = Path.home() / ".adw" / "runtime"
            self.cache_path = Path.home() / ".adw" / "cache" / "judges"
            self._trusted_path = Path.home()
            self._runtime_parts = (".adw", "runtime")
            self._cache_parts = (".adw", "cache", "judges")
        elif runtime_root is not None and cache_root is not None:
            self.runtime_path = Path(os.path.abspath(runtime_root))
            self.cache_path = Path(os.path.abspath(cache_root))
            common = Path(os.path.commonpath((self.runtime_path, self.cache_path)))
            if common in (self.runtime_path, self.cache_path):
                common = common.parent
            self._trusted_path = common
            self._runtime_parts = self.runtime_path.relative_to(common).parts
            self._cache_parts = self.cache_path.relative_to(common).parts
        else:
            raise ValueError("runtime_root and cache_root must be supplied together")
        self._trusted_fd: int | None = None
        self._runtime_fd: int | None = None
        self._cache_fd: int | None = None

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
        try:
            home_fd = _mkdir_open_chain(call_fd, ("home",))
            try:
                cwd_fd = _mkdir_open_chain(call_fd, ("cwd",))
                try:
                    _atomic_write(home_fd, "config.toml", config_text)
                    _link_verified_auth(auth_source, home_fd)
                finally:
                    os.close(cwd_fd)
            finally:
                os.close(home_fd)
            call_path = self.runtime_path / call_name
            yield RuntimePaths(codex_home=call_path / "home", cwd=call_path / "cwd")
        finally:
            os.close(call_fd)
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


def _validate_leaf_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise LunaProviderFailure("unsafe Luna storage leaf name")


def _require_directory_fd(descriptor: int, label: str) -> None:
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        raise LunaProviderFailure(f"unsafe Luna storage directory: {label}")


def _mkdir_open_chain(parent_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(parent_fd)
    try:
        for part in parts:
            _validate_leaf_name(part)
            try:
                os.mkdir(part, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as exc:
                raise LunaProviderFailure(f"unsafe symlink or non-directory Luna storage directory: {part}") from exc
            try:
                _require_directory_fd(child, part)
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _create_random_directory(parent_fd: int) -> tuple[str, int]:
    for _attempt in range(32):
        name = f"luna-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        try:
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            _require_directory_fd(descriptor, name)
            return name, descriptor
        except BaseException:
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
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
    temporary = ""
    descriptor = -1
    for _attempt in range(32):
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _LEAF_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            break
        except FileExistsError:
            continue
    if descriptor < 0:
        raise LunaProviderFailure("could not allocate a Luna storage temporary file")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_regular_or_absent(parent_fd, name)
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary = ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _link_verified_auth(source: Path, destination_fd: int) -> None:
    source_parent = source.parent
    try:
        source_fd = os.open(source_parent, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LunaProviderFailure("unsafe Codex authentication source directory") from exc
    try:
        try:
            captured = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(captured.st_mode):
            raise LunaProviderFailure("Codex authentication source must be a regular file")
        os.link(
            source.name,
            "auth.json",
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
            follow_symlinks=False,
        )
        linked = os.stat("auth.json", dir_fd=destination_fd, follow_symlinks=False)
        if not stat.S_ISREG(linked.st_mode) or (linked.st_dev, linked.st_ino) != (captured.st_dev, captured.st_ino):
            try:
                os.unlink("auth.json", dir_fd=destination_fd)
            except OSError:
                pass
            raise LunaProviderFailure("Codex authentication source changed while linking")
    finally:
        os.close(source_fd)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    except OSError:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass
        return
    try:
        for entry in os.scandir(descriptor):
            try:
                metadata = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(metadata.st_mode):
                _remove_tree_at(descriptor, entry.name)
            else:
                try:
                    os.unlink(entry.name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
    finally:
        os.close(descriptor)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass
