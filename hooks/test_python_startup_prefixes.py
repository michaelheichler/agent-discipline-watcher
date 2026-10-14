from __future__ import annotations

import pytest

import pre_tool


def bash(command: str, cwd: str) -> dict:
    return pre_tool.run({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}})


@pytest.mark.parametrize("prefix", [
    "env FOO=1", "FOO=1", "env -i LC_ALL=C", "env -u TERM", "time", "time -p", "timeout 5", "timeout -k 2 5s",
    "timeout --foreground 1m", "nice", "nice -n 5", "nice -n5", "nice -5", "timeout 5 env LC_ALL=C nice", "command",
])
def test_harmless_startup_prefixes_keep_a_python_read_allowed(tmp_path, prefix: str) -> None:
    assert bash(f"{prefix} python3 -c 'print(1)'", str(tmp_path)) == {}


@pytest.mark.parametrize("prefix", [
    "env HOME=modules", "PATH=modules", "env LD_PRELOAD=modules/x.so", "DYLD_INSERT_LIBRARIES=x.dylib",
    "env PYTHONSTARTUP=x.py", "env FOO=$DEST", "env -a other", "time -o out.txt", "timeout $DEST",
    "timeout 5 env PYTHONPATH=modules", "nice -n 5 env -C modules", "'env' FOO=1",
])
def test_startup_prefixes_that_change_the_interpreter_or_its_imports_block(tmp_path, prefix: str) -> None:
    result = bash(f"{prefix} python3 -c 'print(1)'", str(tmp_path))

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("prefix", [
    "env LD_PRELOAD=x.so", "DYLD_INSERT_LIBRARIES=x.dylib", "PYTHONPATH=modules", "env PATH=modules", "HOME=modules",
    "env FOO=$DEST",
])
def test_isolation_flags_do_not_trust_a_prefix_that_swaps_the_interpreter(tmp_path, prefix: str) -> None:
    result = bash(f"{prefix} python3 -I -S -c 'print(1)'", str(tmp_path))

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("prefix", ["", "env FOO=1", "LC_ALL=C", "env -C modules", "sudo"])
def test_isolation_flags_keep_harmless_prefixes_trusted(tmp_path, prefix: str) -> None:
    assert bash(f"{prefix} python3 -I -S -c 'print(1)'", str(tmp_path)) == {}


@pytest.mark.parametrize("prefix", ["env FOO=1", "time", "timeout 5", "nice -n 5"])
def test_a_harmless_prefix_does_not_clear_a_python_write(tmp_path, prefix: str) -> None:
    result = bash(f"""{prefix} python3 -c 'open("x.txt", "w").write("y")'""", str(tmp_path))

    assert result.get("decision") == "block"
    assert "Call \"open('x.txt', 'w')\"" in result["reason"]
