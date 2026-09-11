from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from install_runtime import EXCLUDED_NAMES, INSTALL_MARKER, INSTALL_MARKER_CONTENT

from . import update_release

INSTALL_PATH = Path(".adw/install/agent-discipline-watcher")
HOSTS = ("claude", "codex", "omp")
EXTENSION_PATH = Path("pi/extensions/agent-discipline-watcher")
PLUGIN_NAME = "agent-discipline-watcher"
LEGACY_LINK_TARGETS = {
    ".agents/skills/agent-discipline-watcher": Path(),
    ".omp/agent/extensions/agent-discipline-watcher": EXTENSION_PATH,
}
MANAGED_LINKS = frozenset({
    ".adw/bin/adw", ".adw/bin/adw-judge", ".local/bin/agent-discipline",
    ".local/bin/adw-cli", ".local/bin/adw-judge",
    ".codex/skills/agent-discipline-watcher", ".claude/skills/agent-discipline-watcher",
    ".config/claude-code/skills/agent-discipline-watcher",
    ".omp/agent/extensions/agent-discipline-watcher", ".agents/skills/agent-discipline-watcher",
})


def _account_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="adw update", allow_abbrev=False)
    for host in HOSTS:
        parser.add_argument(f"--{host}", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "update":
        parser.error("the required command is: adw update")
    args = parser.parse_args(arguments[1:])
    args.hosts = tuple(host for host in HOSTS if getattr(args, host))
    if not args.hosts:
        parser.error("select at least one host: --claude, --codex, or --omp")
    return args


def _check_path(path: Path, home: Path, *, allow_link: bool = False) -> None:
    relative = path.relative_to(home)
    current = home
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            if current == path and allow_link:
                return
            raise RuntimeError(f"refusing symlink path: {current}")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise RuntimeError(f"path is not owned and protected: {current}")
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise RuntimeError(f"refusing special file: {current}")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise RuntimeError(f"refusing hardlinked file: {current}")


def _require_installed(home: Path) -> Path:
    installed = home / INSTALL_PATH
    expected = installed / "hooks/lib/update_runtime.py"
    if Path(__file__).absolute() != expected:
        raise RuntimeError("updates must run through the installed adw command")
    _check_path(expected, home)
    marker = installed / INSTALL_MARKER
    _check_path(marker, home)
    if marker.read_text(encoding="utf-8") != INSTALL_MARKER_CONTENT:
        raise RuntimeError("the installed runtime has no valid ownership marker")
    return installed


def _installer_environment(home: Path) -> dict[str, str]:
    paths = [home / ".local/bin", home / ".bun/bin"]
    paths.extend(Path(value) for value in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"))
    return {
        "HOME": str(home),
        "PATH": os.pathsep.join(map(str, paths)),
        "ADW_INSTALL_DIR": str(home / INSTALL_PATH),
        "ADW_PYTHON": sys.executable,
        "CODEX_HOME": str(home / ".codex"),
        "PI_CODING_AGENT_DIR": str(home / ".omp/agent"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


@contextmanager
def _update_lock(home: Path):
    updates = home / ".adw/updates"
    _check_path(updates, home)
    updates.mkdir(mode=0o700, parents=True, exist_ok=True)
    if updates.stat().st_mode & 0o077:
        raise RuntimeError(f"updates directory must be private: {updates}")
    lock = updates / "update.lock"
    _check_path(lock, home)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as stream:
        metadata = os.fstat(stream.fileno())
        current = lock.lstat()
        if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("update lock changed while opening")
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise RuntimeError("update lock is not a private regular file")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another update is already running") from error
        try:
            yield updates
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _claude_root(home: Path) -> Path:
    from .update_claude import claude_config_root

    return claude_config_root(home, {})


def _selected_paths(home: Path, hosts: tuple[str, ...], claude_root: Path | None = None) -> list[Path]:
    paths = [INSTALL_PATH, Path(".adw/bin/adw"), Path(".local/bin/agent-discipline"), Path(".local/bin/adw-cli")]
    if "codex" in hosts:
        paths.extend(map(Path, (".codex/config.toml", ".codex/hooks.json", ".codex/skills/agent-discipline-watcher", ".adw/runtime/codex")))
    if "omp" in hosts:
        paths.extend(map(Path, (".omp/agent/settings.json", ".omp/agent/extensions/agent-discipline-watcher", ".agents/skills/agent-discipline-watcher")))
    if "claude" in hosts:
        profile = (claude_root or _claude_root(home)).relative_to(home)
        paths.extend(map(Path, (
            ".adw/bin/adw-judge", ".local/bin/adw-judge", ".zshrc", ".bashrc",
            ".adw/update-marketplace",
        )))
        paths.extend(profile / name for name in (
            "settings.json", "skills/agent-discipline-watcher", "plugins/installed_plugins.json",
            "plugins/known_marketplaces.json", "plugins/marketplaces/agent-discipline-watcher",
            "plugins/cache/agent-discipline-watcher",
        ))
    return [home / path for path in paths]


def _safe_legacy_source(path: Path, home: Path) -> Path | None:
    relative = path.relative_to(home).as_posix()
    suffix = LEGACY_LINK_TARGETS.get(relative)
    if suffix is None or not path.is_symlink():
        return None
    root: Path | None = None
    valid = False
    try:
        target = path.resolve(strict=True)
        root = target
        for _part in suffix.parts:
            root = root.parent
        raw_target = os.readlink(path)
        valid = (
            root / suffix == target
            and os.path.isabs(raw_target)
            and raw_target == str(root / suffix)
            and root.is_relative_to(home)
        )
        if valid:
            _check_path(root, home)
            manifest_path = root / ".claude-plugin/plugin.json"
            _check_external_file(manifest_path, root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            valid = isinstance(manifest, dict) and manifest.get("name") == PLUGIN_NAME
        if valid:
            _check_external_file(root / "hooks/run.sh", root)
            _check_external_file(root / EXTENSION_PATH / "index.ts", root)
            valid = _omp_registration_matches(home, root)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return None
    return root if valid else None


def _check_external_file(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts[:-1]:
        current /= part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"legacy ADW source has an unsafe directory: {current}")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise RuntimeError(f"legacy ADW source directory is not protected: {current}")
    leaf = path
    metadata = leaf.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"legacy ADW source has an unsafe file: {leaf}")
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022 or metadata.st_nlink != 1:
        raise RuntimeError(f"legacy ADW source file is not protected: {leaf}")


def _omp_registration_matches(home: Path, root: Path) -> bool:
    settings = home / ".omp/agent/settings.json"
    if not settings.exists() or settings.is_symlink() or not settings.is_file():
        return False
    try:
        value = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    entries = value.get("extensions") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        return False
    expected = str(root / EXTENSION_PATH / "index.ts")
    owned = [entry for entry in entries if PLUGIN_NAME in json.dumps(entry)]
    return bool(owned) and expected in owned


def _preflight_paths(paths: list[Path], home: Path) -> Path | None:
    installed = home / INSTALL_PATH
    legacy_roots: set[Path] = set()
    legacy_paths: dict[Path, Path] = {}
    for path in paths:
        managed_link = path.relative_to(home).as_posix() in MANAGED_LINKS
        owned_link = managed_link and path.is_symlink() and path.resolve().is_relative_to(installed)
        if managed_link and path.is_symlink() and not owned_link:
            legacy_root = _safe_legacy_source(path, home)
            if legacy_root is not None:
                legacy_roots.add(legacy_root)
                legacy_paths[path] = legacy_root
                continue
        _check_path(path, home, allow_link=owned_link)
    if len(legacy_roots) > 1:
        raise RuntimeError("ADW legacy links point to different source roots")
    for path in legacy_paths:
        metadata = path.lstat()
        if metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
            raise RuntimeError(f"legacy ADW link is not owned: {path}")
        _check_path(path, home, allow_link=True)
    return next(iter(legacy_roots), None)


def _backup_paths(paths: list[Path], destination: Path) -> dict[Path, Path | None]:
    destination.mkdir(mode=0o700)
    backups: dict[Path, Path | None] = {}
    for index, path in enumerate(paths):
        backup = destination / str(index)
        if path.is_symlink():
            backup.symlink_to(os.readlink(path))
        elif path.is_dir():
            shutil.copytree(path, backup, symlinks=True)
        elif path.exists():
            shutil.copy2(path, backup)
        else:
            backups[path] = None
            continue
        backups[path] = backup
    return backups


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _restore_paths(backups: dict[Path, Path | None], home: Path) -> None:
    for path, backup in backups.items():
        _check_path(path.parent, home)
        _remove(path)
        if backup is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_symlink():
            path.symlink_to(os.readlink(backup))
        elif backup.is_dir():
            shutil.copytree(backup, path, symlinks=True)
        else:
            shutil.copy2(backup, path)


def _run_installer(source: Path, hosts: tuple[str, ...], environment: dict[str, str]) -> None:
    subprocess.run(
        ["/bin/bash", str(source / "install.sh"), *(f"--{host}" for host in hosts)],
        cwd=source, env=environment, check=True, timeout=900,
    )


def _install_claude(home: Path, source: Path, commit: str, environment: dict[str, str]) -> None:
    from .update_claude import install_pinned_plugin

    install_pinned_plugin(home, source, commit, environment)


def _inventory(root: Path) -> dict[str, tuple[str, int]]:
    files: dict[str, tuple[str, int]] = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name not in EXCLUDED_NAMES]
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise RuntimeError("runtime contains a symlinked directory")
        for name in names:
            if name in EXCLUDED_NAMES or (Path(directory) == root and name == INSTALL_MARKER):
                continue
            path = Path(directory) / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise RuntimeError(f"runtime contains a linked or special file: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files[path.relative_to(root).as_posix()] = (digest, metadata.st_mode & 0o111)
    return files


def _source_inventory(source: Path, hosts: tuple[str, ...] = ()) -> dict[str, tuple[str, int]]:
    inventory = _inventory(source)
    required = {"install.sh", "bin/adw", "hooks/update.py", "hooks/lib/update_runtime.py"}
    if not required.issubset(inventory):
        raise RuntimeError("the published release does not include the supported updater")
    if not inventory["bin/adw"][1] & stat.S_IXUSR:
        raise RuntimeError("the published updater command is not executable")
    if "claude" in hosts and not inventory.get("bin/adw-judge", ("", 0))[1] & stat.S_IXUSR:
        raise RuntimeError("the published release needs an executable bin/adw-judge")
    return inventory


def _resolved_template(value: object, installed: Path) -> object:
    if isinstance(value, str):
        return value.replace("__SKILL_DIR__", str(installed))
    if isinstance(value, list):
        return [_resolved_template(item, installed) for item in value]
    if isinstance(value, dict):
        return {key: _resolved_template(item, installed) for key, item in value.items()}
    return value


def _verify_codex(home: Path, source: Path) -> None:
    installed = home / INSTALL_PATH
    template = _resolved_template(json.loads((source / "hooks/codex-hooks.json").read_text(encoding="utf-8")), installed)
    hooks = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    if not isinstance(template, dict) or not isinstance(hooks, dict):
        raise RuntimeError("Codex hook routing is not an object")
    for event, expected in template["hooks"].items():
        actual = [group for group in hooks.get(event, []) if "agent-discipline-watcher" in json.dumps(group) or "ADW_CODEX_HOOK=" in json.dumps(group)]
        if actual != expected:
            raise RuntimeError(f"Codex hook routing does not match the release: {event}")


def _verify_omp(home: Path) -> None:
    extension = home / INSTALL_PATH / EXTENSION_PATH
    link = home / ".omp/agent/extensions/agent-discipline-watcher"
    if not link.is_symlink() or link.resolve() != extension:
        raise RuntimeError("OMP extension does not point to the installed release")
    settings = json.loads((home / ".omp/agent/settings.json").read_text(encoding="utf-8"))
    expected = str(extension / "index.ts")
    entries = settings.get("extensions", [])
    owned = [entry for entry in entries if "agent-discipline-watcher" in json.dumps(entry)]
    if owned != [expected]:
        raise RuntimeError("OMP extension registration does not match the release")


def _verify_install(home: Path, source: Path, hosts: tuple[str, ...], expected: dict) -> None:
    installed = home / INSTALL_PATH
    _check_path(installed, home)
    marker = installed / INSTALL_MARKER
    _check_path(marker, home)
    if marker.read_text(encoding="utf-8") != INSTALL_MARKER_CONTENT or _inventory(installed) != expected:
        raise RuntimeError("installed runtime does not match the verified release")
    command = home / ".adw/bin/adw"
    _check_path(command.parent, home)
    if not command.is_symlink() or command.resolve() != installed / "bin/adw":
        raise RuntimeError("adw command does not point to the installed release")
    if "codex" in hosts:
        _verify_codex(home, source)
    if "omp" in hosts:
        _verify_omp(home)
    if "claude" in hosts:
        judge = home / ".adw/bin/adw-judge"
        target = installed / "bin/adw-judge"
        if not judge.is_symlink() or judge.resolve() != target or not os.access(target, os.X_OK):
            raise RuntimeError("adw-judge does not point to the installed executable")


def _record_release(updates: Path, release: update_release.Release, hosts: tuple[str, ...]) -> None:
    target = updates / "installed.json"
    _check_path(target, updates.parent.parent)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=updates, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump({"tag": release.tag, "commit": release.commit, "hosts": list(hosts)}, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _perform_update(home: Path, updates: Path, hosts: tuple[str, ...], release: update_release.Release) -> None:
    workspace = Path(tempfile.mkdtemp(prefix="update-", dir=updates))
    retain_backup = False
    try:
        source = workspace / "release"
        update_release.stage_release(release, source)
        expected = _source_inventory(source, hosts)
        environment = _installer_environment(home)
        claude_root = _claude_root(home) if "claude" in hosts else None
        if claude_root is not None:
            environment["CLAUDE_CONFIG_DIR"] = str(claude_root)
        paths = _selected_paths(home, hosts, claude_root)
        legacy_root = _preflight_paths(paths, home)
        if legacy_root is not None:
            environment["ADW_LEGACY_INSTALL_DIR"] = str(legacy_root)
        backups = _backup_paths(paths, workspace / "backup")
        try:
            if "claude" in hosts:
                _install_claude(home, source, release.commit, environment)
                environment["ADW_SKIP_PLUGIN"] = "1"
            _run_installer(source, hosts, environment)
            _verify_install(home, source, hosts, expected)
            _record_release(updates, release, hosts)
        except BaseException:
            try:
                _restore_paths(backups, home)
            except Exception as error:
                retain_backup = True
                raise RuntimeError(f"rollback failed. Backups remain in {workspace / 'backup'}: {error}") from error
            raise
    finally:
        if not retain_backup:
            shutil.rmtree(workspace)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        home = _account_home()
        if not args.dry_run:
            _require_installed(home)
        release = update_release.latest_release()
        if args.dry_run:
            print(f"Would install {release.tag} ({release.commit}) for {', '.join(args.hosts)}")
            return 0
        with _update_lock(home) as updates:
            _perform_update(home, updates, args.hosts, release)
        print(f"Installed {release.tag} ({release.commit}) for {', '.join(args.hosts)}")
        return 0
    except Exception as error:
        print(f"adw update failed: {error}", file=sys.stderr)
        return 2
