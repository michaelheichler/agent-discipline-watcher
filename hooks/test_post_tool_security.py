from pathlib import Path

import record


def _config(tmp_path: Path) -> dict:
    return {"ledger_path": str(tmp_path / "ledger.json"), "baseline": "none"}


def _payload(cwd: Path, path: Path) -> dict:
    return {
        "cwd": str(cwd),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path)},
    }


def test_record_scans_the_approved_open_file(tmp_path: Path) -> None:
    target = tmp_path / "edited.py"
    target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")

    response = record.run(_payload(tmp_path, target), _config(tmp_path))

    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_record_blocks_a_target_outside_cwd(tmp_path: Path) -> None:
    outside = tmp_path.with_name(f"{tmp_path.name}-outside.py")
    outside.write_text("# " + ("TO" + "DO") + " outside\n", encoding="utf-8")
    try:
        response = record.run(_payload(tmp_path, outside), _config(tmp_path))
    finally:
        outside.unlink(missing_ok=True)

    assert response["decision"] == "block"
    assert "unscannable_file" in response["reason"]


def test_record_blocks_a_symlink_that_escapes_cwd(tmp_path: Path) -> None:
    outside = tmp_path.with_name(f"{tmp_path.name}-outside.py")
    outside.write_text("# " + ("TO" + "DO") + " outside\n", encoding="utf-8")
    link = tmp_path / "edited.py"
    try:
        link.symlink_to(outside)
        response = record.run(_payload(tmp_path, link), _config(tmp_path))
    finally:
        link.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)

    assert response["decision"] == "block"
    assert "unscannable_file" in response["reason"]


def test_record_blocks_a_path_swap_without_scanning_the_new_inode(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "edited.py"
    replacement = tmp_path / "replacement.py"
    target.write_text("print(1)\n", encoding="utf-8")
    replacement.write_text("# " + ("TO" + "DO") + " swapped\n", encoding="utf-8")
    real_open = record.os.open
    swapped = False

    def swap_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            target.unlink()
            replacement.replace(target)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(record.os, "open", swap_before_open)
    response = record.run(_payload(tmp_path, target), _config(tmp_path))

    assert response["decision"] == "block"
    assert "unscannable_file" in response["reason"]
    assert "deferred_work_comment" not in response["reason"]


def test_record_blocks_control_characters_in_a_target(tmp_path: Path) -> None:
    target = tmp_path / "edited.py"
    response = record.run(_payload(tmp_path, Path(f"{target}\x00")), _config(tmp_path))

    assert response["decision"] == "block"
    assert "unscannable_file" in response["reason"]
