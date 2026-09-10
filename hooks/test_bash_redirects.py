from __future__ import annotations

import pytest

import pre_bash
from lib import shell_parse


@pytest.mark.parametrize("redirect", ["&> x.txt", "&>x.txt", ">& x.txt", ">&x.txt", "&>> x.txt", "&>>x.txt"])
@pytest.mark.parametrize("command", [
    "python3 -I -S -c 'print(1)' {redirect}",
    "python3 -I -S -c 'print(1)'{redirect}",
    "{redirect} python3 -I -S -c 'print(1)'",
    "(python3 -I -S -c 'print(1)'; echo literal) {redirect}",
])
def test_combined_stream_redirects_block_python_output(command, redirect):
    result = pre_bash.run({"tool_input": {"command": command.format(redirect=redirect)}})

    assert result.get("decision") == "block", result
    assert "opaque_source_write" in result["reason"]


@pytest.mark.parametrize("operator, append", [("&>", False), (">&", False), ("&>>", True)])
@pytest.mark.parametrize("space", ["", " "])
def test_combined_stream_redirects_preserve_literal_write_metadata(operator, append, space):
    command = f"echo 'clean text' {operator}{space}'out file.txt'"

    assert shell_parse.literal_writes(command) == [shell_parse.LiteralWrite("out file.txt", "clean text", append)]


@pytest.mark.parametrize("redirect", [
    ">&2", ">& 2", "1>&2", "1>& 2", "2>&1", "2>& 1", ">&'2'", "1>&'2'",
    ">&-", "1>&-", ">&2-", "1>&2-", "&>/dev/null", "&>> /dev/null",
])
def test_descriptor_redirects_do_not_name_files(redirect):
    command = f"python3 -I -S -c 'print(1)' {redirect}"

    assert shell_parse.write_paths(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


@pytest.mark.parametrize("target", ["2", "-", "'2'", "'-'"])
def test_ampersand_first_redirects_keep_numeric_and_dash_filenames(target):
    command = f"python3 -I -S -c 'print(1)' &> {target}"
    result = pre_bash.run({"tool_input": {"command": command}})

    assert result.get("decision") == "block", result
    assert "opaque_source_write" in result["reason"]


@pytest.mark.parametrize("operator", [">&", "&>", "&>>"])
@pytest.mark.parametrize("target", ["'١'", "'&report.txt'"])
def test_combined_redirects_preserve_non_descriptor_filenames(operator, target):
    command = f"python3 -I -S -c 'print(1)' {operator} {target}"
    result = pre_bash.run({"tool_input": {"command": command}})

    assert result.get("decision") == "block", result
    assert "opaque_source_write" in result["reason"]


@pytest.mark.parametrize("suffix", ["& > x.txt", "& >> x.txt", "'>&' x.txt", "'&>' x.txt", r"\>\& x.txt"])
def test_background_and_literal_operators_do_not_redirect_python(suffix):
    command = f"python3 -I -S -c 'print(1)' {suffix}"

    assert pre_bash.run({"tool_input": {"command": command}}) == {}


@pytest.mark.parametrize("operator", ["&>", ">&", "&>>"])
def test_combined_stream_literal_writes_are_scanned(operator):
    command = f"echo 'We leverage a rich tapestry of utilities.' {operator} out.md"
    result = pre_bash.run({"tool_input": {"command": command}})

    assert result.get("decision") == "block", result
    assert "inflated_diction" in result["reason"]
