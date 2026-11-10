from pathlib import Path

import pytest

from lib import finding_output, imported_baseline, path_policy, scan_input


UNKNOWN_HOME = "~adw_nonexistent_user_874932/x"


def test_lexical_absolute_keeps_a_symlink_for_no_follow_reads(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)

    assert path_policy.lexical_absolute(link / "missing.md") == link / "missing.md"


def test_canonical_paths_resolve_symlinked_parents_of_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)

    assert path_policy.real_path(link / "missing.md") == target / "missing.md"


def test_anchored_identity_resolves_links_after_lexical_anchoring(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)

    assert path_policy.anchored_identity("alias/missing.md", tmp_path) == target / "missing.md"


@pytest.mark.parametrize(
    ("resolve", "expected_parent"),
    [
        pytest.param(path_policy.lexical_absolute, "", id="lexical-collapses-dots-without-links"),
        pytest.param(path_policy.real_path, "other", id="canonical-follows-link-before-parent"),
    ],
)
def test_parent_segments_distinguish_lexical_reads_from_canonical_identity(
    tmp_path: Path, resolve, expected_parent: str,
) -> None:
    target = tmp_path / "other" / "nested"
    target.mkdir(parents=True)
    (tmp_path / "link").symlink_to(target, target_is_directory=True)

    assert resolve(tmp_path / "link" / ".." / "file") == tmp_path / expected_parent / "file"


@pytest.mark.parametrize(
    "resolve",
    [
        pytest.param(path_policy.real_path, id="process-cwd-identity"),
        pytest.param(lambda path: path_policy.anchored_identity(path, Path("/elsewhere")), id="project-identity"),
    ],
)
def test_canonical_identities_expand_the_sandbox_home(tmp_path: Path, monkeypatch, resolve) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve("~/message") == tmp_path / "message"


def test_lexical_anchoring_preserves_parent_segments() -> None:
    assert path_policy.anchored("a/../b", Path("/project")) == Path("/project/a/../b")


def test_unknown_user_homes_remain_literal_and_anchored(tmp_path) -> None:
    assert path_policy.anchored(UNKNOWN_HOME, tmp_path) == tmp_path / UNKNOWN_HOME


@pytest.mark.parametrize("kind", [pytest.param("file", id="literal-file"), pytest.param("link", id="dangling-link")])
def test_literal_unknown_home_targets_cannot_appear_missing(tmp_path, kind) -> None:
    target = tmp_path / UNKNOWN_HOME
    target.parent.mkdir()
    create_target(target, kind)

    assert scan_input.nothing_landed(UNKNOWN_HOME, tmp_path) is False


def create_target(target: Path, kind: str) -> None:
    if kind == "link":
        target.symlink_to(target.parent / "missing")
    else:
        target.write_text("Keep the note.", encoding="utf-8")


def test_unknown_home_review_identities_agree(tmp_path) -> None:
    lexical = path_policy.anchored(UNKNOWN_HOME, tmp_path)
    expected = str((tmp_path / UNKNOWN_HOME).resolve())

    assert str(path_policy.anchored_identity(UNKNOWN_HOME, tmp_path)) == expected
    assert finding_output.canonical_path(str(lexical)) == expected
    assert imported_baseline.path_key(lexical) == expected
