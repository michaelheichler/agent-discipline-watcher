from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from lib import principle_kb


ROOT = "deviq-hugo-" + principle_kb.DEVIQ_COMMIT


def _deviq_archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo(ROOT + "/" + name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
    return output.getvalue()


DEVIQ_FILES = {
    "content/code-smells/dead-code.md": (
        b"---\ntitle: Dead Code\n\ndate: 2020-01-01\n---\n"
        b"Dead code is code that never runs. It stays in the codebase and confuses readers.\n"
    ),
    "content/code-smells/images/dead-code.png": b"\x89PNG",
    "content/code-smells/_index.md": b"---\ntitle: Code smells\n---\nIndex body.\n",
    "content/other-section/off-list.md": b"---\ntitle: Off list\n---\nNot an allowed section.\n",
}

PRINCIPLES_README = """# Programming principles

## Contents

- [DRY](#dry)

## DRY, Don't Repeat Yourself

Duplication in logic calls for abstraction. Duplication in process calls for automation.

## Curly's Law

A variable or method should mean one thing, and only one thing. It should not
mean one thing in one context and something else somewhere else.

See also YAGNI.
"""


def _fetch_from(deviq_bytes: bytes, principles_bytes: bytes) -> principle_kb.Fetch:
    def _fetch(url: str, limit: int) -> bytes:
        if principle_kb.CODELOAD_HOST in url:
            return deviq_bytes
        return principles_bytes

    return _fetch


def _failing_fetch(url: str, limit: int) -> bytes:
    raise OSError("no network")


def test_validate_url_rejects_a_host_outside_the_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        principle_kb._validate_url("https://evil.example.com/x")


def test_validate_url_rejects_a_non_https_scheme():
    with pytest.raises(ValueError, match="allowlist"):
        principle_kb._validate_url("http://" + principle_kb.RAW_HOST + "/x")


def test_validate_url_rejects_embedded_credentials():
    with pytest.raises(ValueError, match="credentials"):
        principle_kb._validate_url(f"https://user:pw@{principle_kb.RAW_HOST}/x")


def test_validate_url_rejects_an_unexpected_port():
    with pytest.raises(ValueError, match="port"):
        principle_kb._validate_url(f"https://{principle_kb.RAW_HOST}:8443/x")


def test_validate_url_accepts_both_allowlisted_hosts():
    assert principle_kb._validate_url(f"https://{principle_kb.CODELOAD_HOST}/x") is None
    assert principle_kb._validate_url(f"https://{principle_kb.RAW_HOST}/x") is None


def test_plain_text_strips_markup_and_never_lets_a_url_survive():
    body = (
        "See the [DevIQ site](https://deviq.com/x) for more.\n\n"
        "A **bold** and _italic_ word, plus `inline code`, describe the idea in plain prose.\n"
    )
    text = principle_kb._plain_text(body)
    assert "http" not in text
    assert "[" not in text and "]" not in text
    assert "bold" in text and "italic" in text and "inline code" in text


def test_plain_text_caps_at_eighty_words():
    body = " ".join(f"word{i}" for i in range(200))
    text = principle_kb._plain_text(body)
    assert len(text.split()) == principle_kb.MAX_WORDS


def test_plain_text_drops_bullet_label_and_see_also_paragraphs():
    body = "Why\n\n- one\n- two\n\nSee also Other Thing.\n\nThe real explanation sentence stays.\n"
    text = principle_kb._plain_text(body)
    assert text == "The real explanation sentence stays."


def test_slugify_matches_known_github_anchors():
    assert principle_kb._slugify("Curly's Law") == "curlys-law"
    assert (
        principle_kb._slugify("Do The Simplest Thing That Could Possibly Work")
        == "do-the-simplest-thing-that-could-possibly-work"
    )


def test_fetch_deviq_keeps_only_allowed_markdown_and_excludes_index_and_images():
    archive = _deviq_archive(DEVIQ_FILES)
    rows = principle_kb._fetch_deviq(_fetch_from(archive, b""))
    assert [(row.source, row.entry_id, row.title) for row in rows] == [
        ("deviq", "code-smells/dead-code", "Dead Code"),
    ]
    assert "http" not in rows[0].text


def test_front_matter_with_windows_line_endings_stays_out_of_the_text(tmp_path: Path):
    page = b"---\r\ntitle: Static Cling\r\r\ndate: 2023-04-22\r\r\n---\r\nStatic cling ties a class to a static call.\r\n"
    root = tmp_path / "cache"
    archive = _deviq_archive({"content/antipatterns/static-cling.md": page})
    principle_kb.build(root=root, fetch=_fetch_from(archive, PRINCIPLES_README.encode()))
    assert principle_kb.lookup("antipatterns/static-cling", root=root) == "Static cling ties a class to a static call."


def test_fetch_principles_skips_contents_and_slugs_each_heading():
    rows = principle_kb._fetch_principles(_fetch_from(b"", PRINCIPLES_README.encode()))
    entry_ids = [row.entry_id for row in rows]
    assert entry_ids == ["dry-dont-repeat-yourself", "curlys-law"]
    curly = next(row for row in rows if row.entry_id == "curlys-law")
    assert "see also" not in curly.text.lower()


def test_build_writes_only_the_database_under_the_cache_root(tmp_path: Path):
    root = tmp_path / "cache"
    result = principle_kb.build(root=root, fetch=_fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode()))
    assert result.skipped is False
    assert result.deviq_count == 1
    assert result.principles_count == 2
    written = list(root.rglob("*"))
    assert written == [root / principle_kb.DB_NAME]


def test_second_build_with_the_same_commits_is_byte_identical(tmp_path: Path):
    root = tmp_path / "cache"
    fetch = _fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode())
    principle_kb.build(root=root, fetch=fetch)
    first = (root / principle_kb.DB_NAME).read_bytes()
    result = principle_kb.build(root=root, fetch=_failing_fetch)
    assert result.skipped is True
    assert (root / principle_kb.DB_NAME).read_bytes() == first


def test_build_with_no_network_and_no_existing_db_skips_with_zero_counts(tmp_path: Path):
    root = tmp_path / "cache"
    result = principle_kb.build(root=root, fetch=_failing_fetch)
    assert result.skipped is True
    assert result.deviq_count == 0
    assert result.principles_count == 0
    assert not (root / principle_kb.DB_NAME).exists()


def test_build_with_no_network_and_an_existing_db_leaves_it_untouched(tmp_path: Path, monkeypatch):
    root = tmp_path / "cache"
    fetch = _fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode())
    principle_kb.build(root=root, fetch=fetch)
    before = (root / principle_kb.DB_NAME).read_bytes()
    monkeypatch.setattr(principle_kb, "DEVIQ_COMMIT", "f" * 40)
    result = principle_kb.build(root=root, fetch=_failing_fetch)
    assert result.skipped is True
    assert result.deviq_count == 1
    assert (root / principle_kb.DB_NAME).read_bytes() == before


def test_build_offline_skips_without_calling_the_fetch(tmp_path: Path, monkeypatch):
    root = tmp_path / "cache"
    monkeypatch.setenv(principle_kb.OFFLINE_ENV, "1")
    result = principle_kb.build(root=root, fetch=_failing_fetch)
    assert result.skipped is True
    assert result.reason == "ADW_OFFLINE=1"
    assert not (root / principle_kb.DB_NAME).exists()


def test_install_build_entry_writes_the_home_cache_with_an_injected_fetch(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(principle_kb.OFFLINE_ENV, raising=False)
    fetch = _fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode())
    code = principle_kb.main(["build"], fetch=fetch)
    assert code == 0
    assert (tmp_path / ".adw" / "cache" / principle_kb.DB_NAME).is_file()
    assert "principle KB built: deviq 1 rows, programming-principles 2 rows" in capsys.readouterr().out


def test_lookup_returns_none_when_the_database_file_is_missing(tmp_path: Path):
    assert principle_kb.lookup("code-smells/dead-code", root=tmp_path / "cache") is None


def test_lookup_returns_none_when_the_entry_id_is_missing(tmp_path: Path):
    root = tmp_path / "cache"
    fetch = _fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode())
    principle_kb.build(root=root, fetch=fetch)
    assert principle_kb.lookup("code-smells/nonexistent", root=root) is None


def test_lookup_returns_the_stored_text_for_a_found_row(tmp_path: Path):
    root = tmp_path / "cache"
    fetch = _fetch_from(_deviq_archive(DEVIQ_FILES), PRINCIPLES_README.encode())
    principle_kb.build(root=root, fetch=fetch)
    text = principle_kb.lookup("code-smells/dead-code", root=root)
    assert text is not None and "Dead code" in text


def test_lookup_never_raises_on_a_corrupt_database(tmp_path: Path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / principle_kb.DB_NAME).write_bytes(b"not a sqlite file")
    assert principle_kb.lookup("code-smells/dead-code", root=root) is None


def test_no_tracked_file_is_named_principles_sqlite():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert not any(Path(path).name == principle_kb.DB_NAME for path in tracked)


def test_main_only_accepts_the_build_argument(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert principle_kb.main(["build"], fetch=_failing_fetch) == 0
    assert "principle KB unchanged" in capsys.readouterr().out
    assert principle_kb.main(["scrub"]) == 2
