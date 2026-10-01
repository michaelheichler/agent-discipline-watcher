from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib import catalog_de, host, parity_fixture, vendor
from lib.scanner import scan_all


REPO_ROOT = vendor.REPO_ROOT
HOOKS_LEAF = Path(__file__).parent.name
SCAN_SCRIPT = (
    "import json;"
    "from lib import parity_fixture;"
    "from lib.scanner import scan_all;"
    "print(json.dumps("
    "scan_all(parity_fixture.FIXTURE_NAME, parity_fixture.FIXTURE_TEXT),"
    " sort_keys=True))"
)
GERMAN_TEXT = (
    "Wir haben gestern das neue Haus von Peter" + chr(39) + "s Familie besucht, "
    "und es war wirklich schön, weil der Garten so groß ist.\n"
)
RENDER_SCRIPT = (
    "import sys;"
    "from lib import reporting;"
    "from lib.scanner import scan_all;"
    "reason = reporting.compact_block(scan_all('notiz.md', sys.argv[1]), {})[0];"
    "print(reason.rsplit(chr(10), 1)[0])"
)


def _serialised(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True)


def _scan_in(tree: Path) -> str:
    finished = subprocess.run(
        [sys.executable, "-c", SCAN_SCRIPT],
        cwd=tree / HOOKS_LEAF, capture_output=True, text=True, check=False,
    )
    assert finished.returncode == 0, finished.stderr[-3000:]
    return finished.stdout.strip()


def _vendored_scan(target: str, tmp_path: Path) -> str:
    tree = tmp_path / target
    vendor.vendor(target, REPO_ROOT, tree)
    return _scan_in(tree)


def test_the_fixture_exercises_every_gated_family() -> None:
    """Guard the fixture because a parity test over a clean file proves only that nothing runs."""
    families = {row["family"] for row in scan_all(parity_fixture.FIXTURE_NAME, parity_fixture.FIXTURE_TEXT)}

    assert {"punctuation", "english"} <= families


def test_the_fixture_frontmatter_stays_silent() -> None:
    """Pin the mask here because a runtime that lost it would still agree with three that also lost it."""
    rows = scan_all(parity_fixture.FIXTURE_NAME, parity_fixture.FIXTURE_TEXT)

    assert not [row for row in rows if row["rule"] == "prose_colon" and row["line"] < 5]


@pytest.mark.parametrize("target", host.SUPPORTED)
def test_a_vendored_runtime_matches_the_source_tree_byte_for_byte(
    target: str, tmp_path: Path,
) -> None:
    """Compare against the source because the split must not change one finding on one host."""
    expected = _serialised(scan_all(parity_fixture.FIXTURE_NAME, parity_fixture.FIXTURE_TEXT))

    assert _vendored_scan(target, tmp_path) == expected


def test_all_four_runtimes_agree_with_each_other(tmp_path: Path) -> None:
    """Compare the runtimes directly because a shared regression would pass every per-host check."""
    scans = {target: _vendored_scan(target, tmp_path) for target in host.SUPPORTED}

    assert len(set(scans.values())) == 1, f"runtimes disagree: {sorted(scans)}"


def _render_in(tree: Path, home: Path) -> str:
    finished = subprocess.run(
        [sys.executable, "-c", RENDER_SCRIPT, GERMAN_TEXT],
        cwd=tree / HOOKS_LEAF, capture_output=True, text=True, check=False, env={**os.environ, "HOME": str(home)},
    )
    assert finished.returncode == 0, finished.stderr[-3000:]
    return finished.stdout


def test_every_runtime_renders_the_same_german_block(tmp_path: Path) -> None:
    """Render in each vendored tree because Claude Code, Codex, and OMP all show the block their own copy builds."""
    blocks = set()
    for target in host.SUPPORTED:
        vendor.vendor(target, REPO_ROOT, tmp_path / target)
        blocks.add(_render_in(tmp_path / target, tmp_path / "home"))

    assert [block.split("\n")[0] for block in blocks] == [catalog_de.BLOCK_LEAD]
