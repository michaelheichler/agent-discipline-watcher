from __future__ import annotations

import pre_python
import pre_tool


def _payload(code: str) -> dict:
    return {"tool_name": "Python", "tool_input": {"code": code}}


def test_pretool_allows_proven_read_only_python() -> None:
    response = pre_tool.run(_payload(
        "from pathlib import Path; p = Path('smoke.txt'); print(p.exists()); print(repr(p.read_text()))",
    ))

    assert response == {}


def test_pretool_blocks_python_file_writes_with_write_edit_action() -> None:
    response = pre_tool.run(_payload("from pathlib import Path; Path('x.txt').write_text('body')"))

    assert response["decision"] == "block"
    assert "Write or Edit" in response["reason"]


def test_pretool_blocks_dynamic_python_write_even_with_a_literal_target() -> None:
    response = pre_tool.run(_payload("from pathlib import Path; Path(target).write_text('body')"))

    assert response["decision"] == "block"
    assert "Write or Edit" in response["reason"]


def test_pretool_blocks_unknown_python_code() -> None:
    response = pre_tool.run(_payload("run_user_supplied_code()"))

    assert response["decision"] == "block"
    assert "read-only" in response["reason"]


def test_pretool_blocks_dynamic_python_execution() -> None:
    response = pre_tool.run(_payload("exec(Path('x.txt').read_text())"))

    assert response["decision"] == "block"
    assert "Write or Edit" in response["reason"]


def test_pretool_blocks_missing_python_code() -> None:
    response = pre_tool.run({"tool_name": "Python", "tool_input": {}})

    assert response["decision"] == "block"
    assert "unreadable hook payload" in response["reason"]


def test_pre_python_fails_closed_for_non_string_code() -> None:
    response = pre_python.run({"tool_name": "Python", "tool_input": {"code": ["print(1)"]}})

    assert response["decision"] == "block"
