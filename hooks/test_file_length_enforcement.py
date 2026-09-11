import json
import subprocess
from pathlib import Path

import pytest

import pre_tool
import record
from lib import patch_content, session_state, shell_parse, write_shape
from testing import make_repo, run_git


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("ADW_CODEX_HOOK", "1")
    monkeypatch.setattr(session_state, "plugin_data_home", lambda: tmp_path / "data")
    return {
        "baseline": "report",
        "ledger_root": str(tmp_path / "ledger"),
        "state_root": str(tmp_path / "state"),
    }


def _source(count: int) -> str:
    return "".join(f"value_{index} = {index}\n" for index in range(count))


def _feedback(response: dict) -> str:
    return response.get("reason", "") or response.get(
        "hookSpecificOutput", {},
    ).get("additionalContext", "")


def _reported_details(response: dict) -> str:
    report_path = Path(_feedback(response).rsplit("Full report: ", 1)[1])
    findings = json.loads(report_path.read_text(encoding="utf-8"))
    return "\n".join(row["detail"] for row in findings)


@pytest.mark.parametrize("command, text", [
    ("echo 'value = 1'", "value = 1\n"),
    ("echo -n 'value = 1'", "value = 1"),
    ("echo '-n' 'value = 1'", "value = 1"),
    ("echo ''", "\n"),
    ("echo 'value\\nnext'", "value\\nnext\n"),
    ("echo -e 'value\\nnext'", "value\nnext\n"),
    ("echo -E 'value\\nnext'", "value\\nnext\n"),
    ("printf 'value = 1'", "value = 1"),
    ("printf 'value = 1\\n'", "value = 1\n"),
    ("printf ''", ""),
])
def test_literal_write_preserves_the_rendered_newline(command: str, text: str) -> None:
    assert shell_parse.literal_writes(command + " > module.py") == [
        shell_parse.LiteralWrite("module.py", text, False),
    ]


@pytest.mark.parametrize("command", [
    "printf '%s\\n' first second third",
    "printf '%% %s\\n' first second",
    "printf '%s:%s\\n' first second third",
    "printf '%s\\n'",
    "printf 'value\\n' ignored arguments",
    "printf '' ignored",
    "printf -- '%s\\n' '-n' '-e'",
    "printf -- '-%s\\n' value",
    "printf '%s\\n' 'literal\\n' '%%'",
    r"printf '\\%s\t%s\n' first second",
])
def test_literal_printf_matches_native_output(command: str) -> None:
    native = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        check=True, capture_output=True, text=True,
    )

    assert shell_parse.literal_writes(command + " > module.py") == [
        shell_parse.LiteralWrite("module.py", native.stdout, False),
    ]


@pytest.mark.parametrize("format_string", ["%d", "%10s", "%b", r"\x61", "%", r"\c"])
def test_unsupported_printf_formats_have_unknown_content(format_string: str) -> None:
    command = f"printf '{format_string}' 'value' > module.py"

    assert shell_parse.literal_writes(command) == []
    assert shell_parse.write_paths(command) == ["module.py"]


def test_printf_expansion_is_bounded() -> None:
    format_string = "x" * 1000 + "%s"
    arguments = " ".join("value" for _ in range(1000))
    command = f"printf '{format_string}' {arguments} > module.py"

    assert shell_parse.literal_writes(command) == []


@pytest.mark.parametrize("body", ["value = 1\n", "\n", ""])
def test_heredoc_write_preserves_the_rendered_newline(body: str) -> None:
    command = f"cat > module.py <<'EOF'\n{body}EOF\n"

    assert shell_parse.literal_writes(command) == [
        shell_parse.LiteralWrite("module.py", body, False),
    ]


def test_patch_projection_honors_header_location_and_trailing_context_whitespace(
    tmp_path: Path,
) -> None:
    first = "def first():\n    value = 1\n    return value\n\n"
    second = "def second():\n    value = 1\n    return value\n"
    (tmp_path / "module.py").write_text(first + second, encoding="utf-8")
    patch = (
        "*** Begin Patch\n*** Update File: module.py\n@@ def second():\n"
        "     value = 1   \n+    added = 2\n*** End Patch\n"
    )
    expected_second = "def second():\n    value = 1   \n    added = 2\n    return value\n"

    assert patch_content.projected_content(patch, tmp_path) == {
        "module.py": first + expected_second,
    }


@pytest.mark.parametrize("count, rule", [
    (500, "file_length_warning"),
    (750, "file_length_critical"),
    (1000, "file_too_long"),
    (1500, "file_too_long"),
])
def test_update_patch_matches_edit_file_length_enforcement(
    tmp_path: Path, config: dict, count: int, rule: str,
) -> None:
    target = tmp_path / "module.py"
    target.write_text(_source(count - 1), encoding="utf-8")
    last_line = f"value_{count - 2} = {count - 2}\n"
    added_line = f"value_{count - 1} = {count - 1}\n"
    edit_response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {
            "file_path": target.name,
            "old_string": last_line,
            "new_string": last_line + added_line,
        },
    }, config)
    patch_response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.py\n@@\n"
            f" {last_line}+{added_line}*** End Patch\n"
        )},
    }, config)

    assert rule in _feedback(edit_response)
    assert rule in _feedback(patch_response)
    assert f"File has {count} lines" in _reported_details(patch_response)
    assert patch_response.get("decision") == edit_response.get("decision")


def test_update_patch_scans_the_moved_destination_for_file_length(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.md").write_text(_source(999), encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.md\n"
            "*** Move to: module.py\n@@\n"
            " value_998 = 998\n+value_999 = 999\n*** End Patch\n"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "module.py:1" in _feedback(response)
    assert "file_too_long" in _feedback(response)


@pytest.mark.parametrize("context", [" value = 1\n", ""])
def test_update_patch_enforces_length_with_repeated_or_empty_context(
    tmp_path: Path, config: dict, context: str,
) -> None:
    (tmp_path / "module.py").write_text("value = 1\n" * 999, encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.py\n@@\n"
            f"{context}+added_value = 1\n*** End Patch\n"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "file_too_long" in _feedback(response)


def test_patch_reports_only_the_final_file_length_tier(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(300), encoding="utf-8")
    additions = "".join(f"+value_{index} = {index}\n" for index in range(300, 800))
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.py\n@@\n"
            f" value_299 = 299\n{additions}*** End Patch\n"
        )},
    }, config)

    assert "file_length_critical" in _feedback(response)
    assert "file_length_warning" not in _feedback(response)


def test_append_to_an_existing_oversized_file_still_blocks(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(1200), encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "echo 'added_value = 1' >> module.py"},
    }, config)

    assert response.get("decision") == "block"
    assert "file_too_long" in _feedback(response)
    assert "at least" in _reported_details(response)


def test_appends_in_one_command_use_the_combined_file_length(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(998), encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": (
            "echo 'first_added = 1' >> module.py && "
            "echo 'second_added = 2' >> module.py"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "file_too_long" in _feedback(response)


def test_printf_arguments_cannot_grow_a_file_to_the_hard_limit(
    tmp_path: Path, config: dict,
) -> None:
    target = tmp_path / "module.py"
    original = _source(997)
    target.write_text(original, encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": (
            "printf '%s\\n' 'first = 1' 'second = 2' 'third = 3' >> module.py"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "File has 1000 lines" in _reported_details(response)
    assert target.read_text(encoding="utf-8") == original


def test_append_after_an_overwrite_uses_the_new_file_length(
    tmp_path: Path, config: dict,
) -> None:
    command = (
        f"cat > module.py <<'EOF'\n{_source(999)}EOF\n"
        "echo 'added_value = 1' >> ./module.py"
    )
    owned, _ = write_shape.shaped_write_findings(command, config, tmp_path)

    assert any(row["rule"] == "file_too_long" for row in owned)
    assert not (tmp_path / "module.py").exists()


def test_overwrite_of_an_oversized_file_resets_the_append_length(
    tmp_path: Path, config: dict,
) -> None:
    target = tmp_path / "module.py"
    original = _source(1200)
    target.write_text(original, encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": (
            "echo 'value = 1' > module.py && "
            "echo 'added_value = 2' >> module.py"
        )},
    }, config)

    assert response == {}
    assert target.read_text(encoding="utf-8") == original


def test_sequential_appends_track_the_previous_trailing_newline(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(998).rstrip("\n"), encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": (
            "printf '\\n' >> module.py && "
            "echo 'first_added = 1' >> module.py && "
            "echo 'second_added = 2' >> module.py"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "File has 1000 lines" in _reported_details(response)


def test_empty_append_does_not_lower_the_capped_file_length(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(1000).rstrip("\n"), encoding="utf-8")
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "printf '' >> module.py"},
    }, config)

    assert response.get("decision") == "block"
    assert "file_too_long" in _feedback(response)


def test_patch_that_reduces_a_file_below_the_warning_threshold_is_allowed(
    tmp_path: Path, config: dict,
) -> None:
    (tmp_path / "module.py").write_text(_source(1000), encoding="utf-8")
    deleted_lines = "".join(f"-value_{index} = {index}\n" for index in range(499, 1000))
    response = pre_tool.run({
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.py\n@@\n"
            f" value_498 = 498\n{deleted_lines}*** End Patch\n"
        )},
    }, config)

    assert response == {}


def test_post_tool_patch_cannot_baseline_away_a_committed_oversized_file(
    tmp_path: Path, config: dict,
) -> None:
    repo = make_repo(tmp_path)
    target = repo / "module.py"
    target.write_text(_source(1200), encoding="utf-8")
    run_git(repo, "add", target.name)
    run_git(repo, "commit", "-qm", "Add source fixture")
    target.write_text(_source(1200) + "added_value = 1\n", encoding="utf-8")
    response = record.run({
        "cwd": str(repo),
        "tool_name": "apply_patch",
        "tool_input": {"input": (
            "*** Begin Patch\n*** Update File: module.py\n@@\n"
            " value_1199 = 1199\n+added_value = 1\n*** End Patch\n"
        )},
    }, config)

    assert response.get("decision") == "block"
    assert "file_too_long" in _feedback(response)
    assert f"{target}:1" in _feedback(response)
