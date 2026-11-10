import sys


def runtime_lock_directory(root):
    """Because staging and hooks share storage, validate it before either writes."""
    import os
    import stat

    updates = root / ".adw/updates"
    for path in (root / ".adw", updates):
        if path.is_symlink():
            raise RuntimeError(f"refusing a symlinked runtime lock directory: {path}")
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise RuntimeError(f"runtime lock directory is not protected: {path}")
        if path == updates and metadata.st_mode & 0o077:
            raise RuntimeError(f"updates directory must be private: {path}")
    return updates


def open_runtime_lock(root, mode):
    """Because hook imports must wait, share lock validation without importing lib."""
    import fcntl
    import os
    import stat

    lock = runtime_lock_directory(root) / "update.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    stream = os.fdopen(descriptor, "r+")
    try:
        metadata = os.fstat(stream.fileno())
        current = lock.lstat()
        if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("runtime lock changed while opening")
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise RuntimeError("runtime lock is not a private regular file")
        fcntl.flock(stream.fileno(), mode)
    except Exception:
        stream.close()
        raise
    return stream


def run_hook(script: str, *, home=None) -> int:
    """Because updates replace hook modules, acquire their lock before imports."""
    import fcntl
    import os
    from pathlib import Path
    import pwd
    import runpy

    # Because only tests inject home, production uses passwd rather than $HOME.
    root = Path(home) if home is not None else Path(pwd.getpwuid(os.getuid()).pw_dir)
    with open_runtime_lock(root, fcntl.LOCK_SH):
        hook = Path(__file__).resolve().parent / script
        if hook.parent != Path(__file__).resolve().parent or not hook.is_file():
            raise RuntimeError("invalid hook script")
        sys.path.insert(0, str(hook.parent))
        sys.argv = [str(hook)]
        runpy.run_path(str(hook), run_name="__main__")
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--hook":
        try:
            return run_hook(sys.argv[2])
        except Exception as error:
            print(f"ADW hook could not acquire its runtime: {error}", file=sys.stderr)
            return 2
    if not sys.flags.isolated or not sys.flags.no_site:
        print("adw update requires Python -I -S. Use the installed adw command.", file=sys.stderr)
        return 2
    import importlib
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runtime = importlib.import_module("lib.update_runtime")
    return runtime.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
