from __future__ import annotations

from pathlib import Path

import pytest

import build_runtime
from lib import host, vendor


REPO_ROOT = vendor.REPO_ROOT


def test_building_every_host_writes_one_tree_each(tmp_path: Path) -> None:
    """Build the whole roster because a release must ship every runtime from one command."""
    counts = build_runtime.build(host.SUPPORTED, REPO_ROOT, tmp_path)

    assert set(counts) == set(host.SUPPORTED)
    assert all(count > 0 for count in counts.values())
    assert all((tmp_path / name / "hooks" / "lib" / "scanner.py").is_file() for name in host.SUPPORTED)


def test_a_single_host_build_leaves_the_others_absent(tmp_path: Path) -> None:
    """Build one because a plugin release for Claude must not produce a Codex tree at all."""
    build_runtime.build((host.CLAUDE,), REPO_ROOT, tmp_path)

    assert (tmp_path / host.CLAUDE).is_dir()
    assert not (tmp_path / host.CODEX).exists()


def test_the_build_refuses_a_tree_carrying_a_foreign_adapter(tmp_path: Path, monkeypatch) -> None:
    """Fail the build because a leaked adapter must never reach a release rather than be noticed later."""
    monkeypatch.setattr(vendor, "foreign_files", lambda *_args: (Path("hooks/lib/codex_luna.py"),))

    with pytest.raises(ValueError, match="foreign files"):
        build_runtime.build((host.CLAUDE,), REPO_ROOT, tmp_path)


def test_the_cli_reports_a_count_for_each_built_host(tmp_path: Path, capsys) -> None:
    """Print the counts because a build that silently wrote nothing looks the same as a good one."""
    status = build_runtime.main(["--host", host.CODEX, "--destination", str(tmp_path)])

    assert status == 0
    assert host.CODEX in capsys.readouterr().out


def test_the_cli_reports_a_failure_without_a_traceback(tmp_path: Path, monkeypatch, capsys) -> None:
    """Name the fault because a build failure in CI must read as one line, not a stack."""
    monkeypatch.setattr(vendor, "foreign_files", lambda *_args: (Path("hooks/lib/claude_native.py"),))

    status = build_runtime.main(["--host", host.CODEX, "--destination", str(tmp_path)])

    assert status == 2
    assert "foreign files" in capsys.readouterr().err
