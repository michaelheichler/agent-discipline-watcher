"""Run through the whole Bash gate, because brace and loop unfolding only matters for what the gate then lets pass."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pre_tool
from lib import protected, tests_policy
from lib.shell_unfold import brace_words
from testing import make_repo

DYNAMIC = "dynamic_write_target"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def denied_repo(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path)
    (repo / ".agent-discipline.json").write_text(json.dumps({"tests": "deny"}), encoding="utf-8")
    return repo


def gate(tmp_path: Path, command: str) -> dict:
    payload = {"session_id": "unfold", "cwd": str(denied_repo(tmp_path)), "tool_name": "Bash",
               "tool_input": {"command": command}}
    return pre_tool.run(payload, {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")})


@pytest.mark.parametrize("command", [
    pytest.param("cp analysis/src/{a.html,b.js} analysis/dest/", id="entry-16-two-files"),
    pytest.param("cp .build/mocks/r1/{config.json,snapshot.json,preview.html,preview.js} .build/mocks/r2/",
                 id="entry-35-four-files"),
    pytest.param("cp .build/fonts/{awtrix.bdf,small.bdf} .build/mocks/fonts/", id="entry-42-fonts"),
    pytest.param("for f in loggia-a.js loggia-b.js; do ln -sf ../src/$f analysis/out/$f; done", id="entry-38-loop"),
])
def test_a_literal_brace_or_loop_over_ordinary_files_passes(tmp_path: Path, command: str) -> None:
    assert gate(tmp_path, command).get("decision") != "block"


@pytest.mark.parametrize("command", [
    pytest.param("cp src/{a.js,a.test.js} out/", id="brace"),
    pytest.param("for f in a.js a.test.js; do cp src/$f out/$f; done", id="loop"),
])
def test_an_unfolded_test_name_blocks_on_that_test_file(tmp_path: Path, command: str) -> None:
    response = gate(tmp_path, command)

    assert (response.get("decision"), tests_policy.RULE in response.get("reason", ""),
            "out/a.test.js" in response.get("reason", "")) == ("block", True, True)


@pytest.mark.parametrize("command", [
    pytest.param("cp src/{a,b}*.js out/", id="brace-beside-glob"),
    pytest.param("cp src/a{1..3}.js out/", id="sequence-brace"),
    pytest.param("cat src/a.js > out/{a,b}.txt", id="brace-in-redirect"),
    pytest.param("cat src/a.js >out/{a,b}.txt", id="brace-in-attached-redirect"),
    pytest.param("for name in a b; do cp .build/x/${name}-*.json .build/y/; done", id="loop-value-beside-glob"),
    pytest.param("for f in a.js b.js; do f=a.test.js; cp src/$f out/$f; done", id="loop-variable-reassigned"),
    pytest.param("for f in a.js b.js; do cp src/$f out/${f%.js}.test.js; done", id="loop-variable-trimmed"),
])
def test_a_brace_or_loop_bash_still_resolves_at_run_time_blocks_as_dynamic(tmp_path: Path, command: str) -> None:
    response = gate(tmp_path, command)

    assert (response.get("decision"), DYNAMIC in response.get("reason", "")) == ("block", True)


@pytest.mark.parametrize(("word", "expected"), [
    pytest.param("src/{a.js,b.js}", ["src/a.js", "src/b.js"], id="one-group"),
    pytest.param("a{b,c}d{e,f}", ["abde", "abdf", "acde", "acdf"], id="two-groups-left-first"),
    pytest.param("x{a,{b,c}}y", ["xay", "xby", "xcy"], id="nested-group"),
    pytest.param("{a}", ["{a}"], id="group-without-comma-stays-literal"),
])
def test_a_literal_brace_word_expands_the_way_bash_expands_it(word: str, expected: list[str]) -> None:
    assert brace_words(word) == expected


@pytest.mark.parametrize("word", [
    pytest.param("f" + "{a,b}" * 12, id="thousands-of-words"),
    pytest.param("{a,b}" + "x" * 5000, id="very-long-word"),
])
def test_a_brace_word_too_large_to_expand_cheaply_stays_whole(word: str) -> None:
    assert brace_words(word) == [word]
