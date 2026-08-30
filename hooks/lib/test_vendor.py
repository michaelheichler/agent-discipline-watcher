from __future__ import annotations

from pathlib import Path

import pytest

from lib import host, vendor


REPO_ROOT = vendor.REPO_ROOT


@pytest.mark.parametrize(
    ("filename", "owner"),
    (
        ("claude_native.py", host.CLAUDE),
        ("merge-codex-config.py", host.CODEX),
        ("test_task4_codex.py", host.CODEX),
        ("test_claude_luna.py", host.CLAUDE),
        ("prompt_submit.py", None),
        ("luna_provider.py", None),
        ("scanner.py", None),
    ),
)
def test_ownership_reads_separated_tokens_not_substrings(filename: str, owner: str | None) -> None:
    """Pin prompt_submit.py because the letters o, m, p sit inside the word prompt."""
    assert vendor.owning_host(filename) == owner


def test_a_file_naming_two_hosts_is_refused_rather_than_assigned() -> None:
    """Refuse rather than pick because either choice would ship the file to a host that cannot run it."""
    with pytest.raises(ValueError, match="more than one host"):
        vendor.owning_host("claude_codex_bridge.py")


@pytest.mark.parametrize("target", host.SUPPORTED)
def test_a_vendored_runtime_carries_no_other_host(target: str, tmp_path: Path) -> None:
    """Prove the isolation because the checkpoint requires deleting three runtimes and running the fourth."""
    destination = tmp_path / target
    vendor.vendor(target, REPO_ROOT, destination)

    assert vendor.foreign_files(target, destination) == ()


def test_the_claude_runtime_keeps_its_own_adapters(tmp_path: Path) -> None:
    """Name the adapters because a runtime stripped of its own host code would gate nothing."""
    written = set(vendor.vendor(host.CLAUDE, REPO_ROOT, tmp_path / "claude"))

    assert Path("hooks/lib/claude_native.py") in written
    assert Path("hooks/lib/codex_luna.py") not in written


def test_the_codex_runtime_keeps_its_own_adapter(tmp_path: Path) -> None:
    """Mirror the Claude case because the split must cut both ways to be a split at all."""
    written = set(vendor.vendor(host.CODEX, REPO_ROOT, tmp_path / "codex"))

    assert Path("hooks/lib/codex_luna.py") in written
    assert Path("hooks/lib/claude_native.py") not in written


def test_every_runtime_carries_the_launcher_and_the_interpreter_floor(tmp_path: Path) -> None:
    """Ship the root assets because nine Claude tests failed when only the hooks tree travelled."""
    for target in host.SUPPORTED:
        written = set(vendor.vendor(target, REPO_ROOT, tmp_path / target))

        assert Path("bin/adw-judge") in written, f"{target} lost the judge launcher"
        assert Path(".python-version") in written, f"{target} lost the interpreter floor"


def test_only_omp_carries_the_extension_tree(tmp_path: Path) -> None:
    """Read the extras from the manifest because pi carries no host token in its name."""
    for target in host.SUPPORTED:
        written = set(vendor.vendor(target, REPO_ROOT, tmp_path / target))
        carried = any(path.parts[0] == "pi" for path in written)

        assert carried == (target == host.OMP), f"{target} disagrees about the pi tree"


def test_vendoring_replaces_a_stale_tree_rather_than_merging(tmp_path: Path) -> None:
    """Clear first because a leftover adapter from an earlier build would survive into the new runtime."""
    destination = tmp_path / "runtime"
    vendor.vendor(host.CLAUDE, REPO_ROOT, destination)
    assert (destination / "hooks" / "lib" / "claude_native.py").exists()

    vendor.vendor(host.CODEX, REPO_ROOT, destination)

    assert not (destination / "hooks" / "lib" / "claude_native.py").exists()


def test_an_unknown_host_is_refused_rather_than_vendored(tmp_path: Path) -> None:
    """Refuse a guess because an undeclared roster would copy every adapter into one tree."""
    with pytest.raises(ValueError, match="not a supported host"):
        vendor.vendor("some-future-host", REPO_ROOT, tmp_path / "out")


def test_no_cache_directory_reaches_a_vendored_runtime(tmp_path: Path) -> None:
    """Skip caches because a stale pyc from the source tree would ship into every runtime."""
    written = vendor.vendor(host.OMP, REPO_ROOT, tmp_path / "omp")

    assert not [path for path in written if "__pycache__" in path.parts]


def test_no_runtime_carries_the_task_or_evaluation_trees(tmp_path: Path) -> None:
    """Leave planning out because a runtime ships to a user who never reads our backlog."""
    written = vendor.vendor(host.CLAUDE, REPO_ROOT, tmp_path / "claude")
    roots = {path.parts[0] for path in written}

    assert not roots & {"tasks", "evals", "docs"}
