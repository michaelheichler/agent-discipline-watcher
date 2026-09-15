import struct
import zlib
from pathlib import Path

import pytest

import pre_commit
import pre_tool
import record
from lib import end_turn, scan_input, scanner
from lib.write_shape import shaped_write_findings
from testing import make_repo, run_git


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">2I5B", 1, 1000, 8, 2, 0, 0, 0)
    pixels = b"\0\n\n\n" * 1000
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels, level=0)) + chunk(b"IEND", b"")
    )


@pytest.fixture
def config(tmp_path: Path) -> dict:
    return {
        "baseline": "report",
        "ledger_root": str(tmp_path / "ledger"),
        "state_root": str(tmp_path / "state"),
    }


def _commit(repo: Path, config: dict, message: str = "Add baseline") -> dict:
    return pre_commit.run({
        "cwd": str(repo),
        "tool_name": "Bash",
        "tool_input": {"command": ["git", "commit", "-m", message]},
    }, config, ledger_root=config["ledger_root"], state_root=config["state_root"])


@pytest.mark.parametrize("limit", [100, 1_000_000])
def test_staged_png_is_not_counted_as_source(
    tmp_path: Path, config: dict, limit: int,
) -> None:
    repo = make_repo(tmp_path)
    asset = repo / "baseline.png"
    asset.write_bytes(_png())
    run_git(repo, "add", asset.name)
    asset.write_text("value = 1\n" * 1200, encoding="utf-8")
    config["max_scan_bytes"] = limit

    assert _png().count(b"\n") > 2945
    assert _commit(repo, config) == {}


def test_binary_asset_does_not_hide_other_files_or_commit_prose(
    tmp_path: Path, config: dict,
) -> None:
    repo = make_repo(tmp_path)
    (repo / "baseline.png").write_bytes(_png())
    (repo / "module.py").write_text("value = 1\n" * 1000, encoding="utf-8")
    (repo / "notes.md").write_text("We ship it; it works.\n", encoding="utf-8")
    run_git(repo, "add", ".")

    response = _commit(repo, config, "We ship it; it works")

    assert response["decision"] == "block"
    assert "module.py:1 clean_code/file_too_long" in response["reason"]
    assert "notes.md:1 punctuation/prose_semicolon" in response["reason"]
    assert "commit_message.md:1 punctuation/prose_semicolon" in response["reason"]
    assert "baseline.png" not in response["reason"]


@pytest.mark.parametrize("limit", [1, 100, 1_000_000])
def test_post_tool_and_stop_skip_binary_assets(
    tmp_path: Path, config: dict, limit: int,
) -> None:
    target = tmp_path / "baseline.png"
    target.write_bytes(_png())
    config["max_scan_bytes"] = limit
    payload = {
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": target.name},
    }

    assert record.run(payload, config) == {}
    findings, existing = end_turn._blocking_rows([target.name], tmp_path, config)
    assert findings == []
    assert existing == [str(target)]


def test_direct_scan_and_length_fallback_skip_binary_assets() -> None:
    text = _png().decode("utf-8", errors="replace")

    assert scanner.scan_all("baseline.png", text) == []
    assert scanner.file_length_findings("baseline.png", text) == []


@pytest.mark.parametrize("name", ["module.py", "module.newlang", "baseline.png", "notes.md"])
def test_text_is_not_exempted_by_an_asset_name(
    tmp_path: Path, config: dict, name: str,
) -> None:
    repo = make_repo(tmp_path)
    target = repo / name
    text = "# " + "TO" + "DO fix this; it works\n" + "value = 1\n" * 1000
    target.write_text(text, encoding="utf-8")
    run_git(repo, "add", name)

    assert _commit(repo, config)["decision"] == "block"
    assert record.run({
        "cwd": str(repo), "tool_name": "Write",
        "tool_input": {"file_path": name},
    }, config)["decision"] == "block"
    assert pre_tool.run({
        "cwd": str(repo), "tool_name": "Write",
        "tool_input": {"file_path": name, "content": text},
    }, config)["decision"] == "block"


@pytest.mark.parametrize("name", ["module.py", "notes.md", "page.svg", "module.newlang"])
def test_binary_bytes_do_not_exempt_text_paths(
    tmp_path: Path, config: dict, name: str,
) -> None:
    target = tmp_path / name
    target.write_bytes(b"\0value = 1\n")

    assert scan_input.fallback_findings(target)[0]["rule"] == "unscannable_file"
    response = record.run({
        "cwd": str(tmp_path), "tool_name": "Write",
        "tool_input": {"file_path": name},
    }, config)
    assert response["decision"] == "block"


def test_missing_asset_does_not_become_a_success(tmp_path: Path, config: dict) -> None:
    assert scan_input.fallback_findings(tmp_path / "missing.png")[0]["rule"] == "unscannable_file"
    response = record.run({
        "cwd": str(tmp_path), "tool_name": "Write",
        "tool_input": {"file_path": "missing.png"},
    }, config)
    assert response["decision"] == "block"


@pytest.mark.parametrize("name, content", [
    ("photo.JPG", b"\xff\xd8\xff\xe0\0\x10JFIF\0"),
    ("baseline.gif", b"GIF89a"),
    ("document.pdf", b"%PDF-1.7\n"),
    ("archive.zip", b"PK\x03\x04"),
    ("font.woff2", b"wOF2"),
    ("sound.wav", b"RIFF\0\0\0\0WAVE"),
    ("video.mp4", b"\0\0\0\x18ftypmp42"),
    ("data.bin", b"\0\xff\x01"),
])
def test_binary_formats_skip_all_file_scan_paths(
    tmp_path: Path, config: dict, name: str, content: bytes,
) -> None:
    repo = make_repo(tmp_path)
    target = repo / name
    target.write_bytes(content + b"\n" * 3000)
    run_git(repo, "add", name)

    assert _commit(repo, config) == {}
    assert scan_input.read_scannable(target, config) is None
    assert scan_input.fallback_findings(target) == []
    assert scan_input.file_line_count(target) is None
    assert record.run({
        "cwd": str(repo), "tool_name": "Write",
        "tool_input": {"file_path": name},
    }, config) == {}


def test_append_does_not_count_binary_newlines(tmp_path: Path, config: dict) -> None:
    (tmp_path / "baseline.gif").write_bytes(b"GIF89a" + b"\n" * 3000)

    owned, inherited = shaped_write_findings(
        "printf 'trailer' >> baseline.gif", config, tmp_path,
    )

    assert owned == []
    assert inherited == []


@pytest.mark.parametrize("content", [
    "Text with a replacement character \ufffd still needs checking.\n",
    "x" * 8191 + "\u00e9",
    "\ufeffText with a byte order mark.\n",
])
def test_unicode_text_is_not_misclassified_as_binary(content: str) -> None:
    assert not scan_input.is_binary_content("baseline.png", content)
    assert not scan_input.is_binary_content("baseline.png", content.encode("utf-8"))


def test_staged_text_cannot_hide_behind_a_worktree_image(
    tmp_path: Path, config: dict,
) -> None:
    repo = make_repo(tmp_path)
    target = repo / "baseline.png"
    target.write_text("value = 1\n" * 1000, encoding="utf-8")
    run_git(repo, "add", target.name)
    target.write_bytes(_png())

    assert _commit(repo, config)["decision"] == "block"
