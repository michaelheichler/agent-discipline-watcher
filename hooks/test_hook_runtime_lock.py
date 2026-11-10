"""Serialize hook imports because updates must not replace a running hook's modules."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ENTRY = Path(__file__).resolve().parent / "update.py"
DRIVER = (
    "import runpy, sys; module = runpy.run_path(sys.argv[1]); "
    "print('attempt', flush=True); "
    "sys.exit(module['run_hook']('hook.py', home=sys.argv[2]))"
)


@pytest.fixture
def hook_copy(tmp_path) -> tuple[Path, Path]:
    source = tmp_path / "copy"
    source.mkdir()
    shutil.copyfile(ENTRY, source / "update.py")
    (source / "hook.py").write_text("print('ran', flush=True)\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    return source, home


def command(source, home) -> list[str]:
    return [sys.executable, "-I", "-S", "-c", DRIVER, str(source / "update.py"), str(home)]


def observe_locked_hook(source, home) -> tuple:
    directory = home / ".adw/updates"
    directory.mkdir(parents=True, mode=0o700)
    descriptor = os.open(directory / "update.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        with subprocess.Popen(command(source, home), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as child:
            return finish_hook(child, stream)


def finish_hook(child, stream) -> tuple:
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "attempt"
        blocked = waits_for_unlock(child)
    finally:
        fcntl.flock(stream, fcntl.LOCK_UN)
    output, error = child.communicate(timeout=5)
    return blocked, child.returncode, output, error


def waits_for_unlock(child) -> bool:
    try:
        child.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        return True
    return False


def test_a_hook_waits_for_the_updater_before_executing(hook_copy) -> None:
    source, home = hook_copy

    blocked, status, output, error = observe_locked_hook(source, home)

    assert blocked is True
    assert status == 0
    assert output == "ran\n"
    assert error == ""


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink", "permissions"])
def test_unsafe_runtime_locks_never_execute_hook_code(hook_copy, kind) -> None:
    source, home = hook_copy
    unsafe_lock(home, kind)

    result = subprocess.run(command(source, home), check=False, capture_output=True,
                            text=True, timeout=5)

    assert result.returncode != 0
    assert result.stdout == "attempt\n"


def unsafe_lock(home, kind) -> None:
    directory = home / ".adw/updates"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "update.lock"
    if kind == "fifo":
        os.mkfifo(path)
        return
    if kind in {"symlink", "hardlink"}:
        outside = home / "outside"
        outside.touch(mode=0o600)
        if kind == "symlink":
            path.symlink_to(outside)
        else:
            path.hardlink_to(outside)
        return
    path.touch(mode=0o644)
