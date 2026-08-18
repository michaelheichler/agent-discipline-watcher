from __future__ import annotations

from pathlib import Path

import pre_write
from lib.scanner import scan_all


def _rules(source: str) -> set[str]:
    return {row["rule"] for row in scan_all("sample.py", source, {})}


def _write(source: str, config: dict | None = None) -> dict:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "sample.py", "content": source},
    }
    return pre_write.run(payload, config or {"baseline": "none"})


def test_two_lines_of_ordinary_code_are_allowed() -> None:
    assert _write("x = 1\ny = 2\n") == {}


def test_one_strict_why_comment_is_allowed() -> None:
    source = "# Keep one copy because callers rely on object identity.\nx = 1\n"
    assert _write(source) == {}


def test_one_what_comment_is_a_hard_block() -> None:
    response = _write("# Increment the counter.\nx = 1\n")
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]


def test_weak_why_wording_is_a_hard_block() -> None:
    response = _write("# Skip unless the lock is held.\nx = 1\n")
    assert response["decision"] == "block"
    assert "weak_why_comment" in response["reason"]


def test_vague_because_wording_is_a_hard_block() -> None:
    response = _write("# Increment the counter because reasons.\nx = 1\n")
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]


def test_generic_causal_tails_are_hard_blocks() -> None:
    for comment in (
        "# Increment the counter because it is needed.",
        "# Increment the counter because this is necessary.",
        "# Increment the counter otherwise it breaks.",
    ):
        response = _write(comment + "\nx = 1\n")
        assert response["decision"] == "block"


def test_inline_trailing_todo_is_a_hard_block() -> None:
    response = _write("x = 1  # " + ("TO" + "DO") + ": fix this later\n")
    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_no_space_todo_marker_is_a_hard_block() -> None:
    response = _write("#" + ("TO" + "DO") + ": fix this later\nx = 1\n")
    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_no_space_lowercase_hash_markers_are_not_css_comments() -> None:
    for marker in ("to" + "do", "fix" + "me", "x" + "xx", "ha" + "ck"):
        css = "#" + marker + " { color: #fff; }\n"
        assert [row["rule"] for row in scan_all("style.css", css, {})] == []


def test_preprocessor_and_css_hash_tokens_are_not_comments() -> None:
    source = (
        "#include <stdio.h>\n#define MAX 10\n#ifdef DEBUG\n"
        "#endif\nint main(void) { return 0; }\n"
    )
    assert [row["rule"] for row in scan_all("main.c", source, {})] == []
    css = "#id { color: #fff; }\n.box { background: #a1b2c3; }\n"
    assert [row["rule"] for row in scan_all("style.css", css, {})] == []


def test_trailing_code_cannot_launder_a_vague_because_into_a_strong_why() -> None:
    source = "/* Skip because it. */avoid_expensive_computation()\n"
    response = _write(source)
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"] or "weak_why_comment" in response["reason"]


def test_malformed_python_cannot_hide_a_multiline_docstring() -> None:
    source = 'def value():\n    """First line.\n    Second line.\n    """\n    return 1\ninvalid syntax\n'
    response = _write(source)
    assert response["decision"] == "block"
    assert "docstring_narration" in response["reason"]


def test_malformed_multiline_signature_cannot_hide_a_docstring() -> None:
    source = (
        "def value(\n"
        "    item,\n"
        "):\n"
        "    \"\"\"First line.\n"
        "    Second line.\n"
        "    \"\"\"\n"
        "    return item\n"
        "invalid syntax\n"
    )
    response = _write(source)
    assert response["decision"] == "block"
    assert "docstring_narration" in response["reason"]


def test_tagged_leading_narration_is_a_hard_block() -> None:
    source = "# Args:\n# Increment the counter.\nx = 1\n"
    response = _write(source)
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]


def test_two_prose_comment_lines_are_a_hard_block_even_with_why() -> None:
    source = (
        "# Keep one copy because callers rely on object identity.\n"
        "# The cache stores that copy.\n"
        "x = 1\n"
    )
    response = _write(source)
    assert response["decision"] == "block"
    assert "prose_comment_block" in response["reason"]


def test_one_strict_why_docstring_is_allowed() -> None:
    source = (
        "def cached_value():\n"
        "    \"\"\"Keep one copy because callers rely on object identity.\"\"\"\n"
        "    return 1\n"
    )
    assert _write(source) == {}


def test_one_what_docstring_is_a_hard_block() -> None:
    source = (
        "def cached_value():\n"
        "    \"\"\"Return the cached value.\"\"\"\n"
        "    return 1\n"
    )
    response = _write(source)
    assert response["decision"] == "block"
    assert "what_docstring" in response["reason"]


def test_every_multiline_docstring_is_a_hard_block() -> None:
    source = (
        "def cached_value():\n"
        "    \"\"\"Keep one copy because callers rely on object identity.\n"
        "    The cache stores that copy.\n"
        "    \"\"\"\n"
        "    return 1\n"
    )
    response = _write(source)
    assert response["decision"] == "block"
    assert "docstring_narration" in response["reason"]


def test_comment_blocks_ignore_release_switches() -> None:
    source = "# Increment the counter.\nx = 1\n"
    response = _write(
        source,
        {
            "baseline": "none",
            "clean_code": False,
            "gates": {"clean_code": "off"},
            "kill_switches": {"clean_code": True},
            "rule_gates": {"what_comment": "off"},
            "exempt_paths": ["sample.py"],
        },
    )
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]


def test_semantic_release_cannot_release_a_what_comment() -> None:
    calls: list[object] = []

    def release(request: object) -> dict[str, str]:
        calls.append(request)
        return {
            "verdict": "release",
            "evidence": "# Increment the counter.",
            "reason": "release",
        }

    response = _write(
        "# Increment the counter.\nx = 1\n",
        {"baseline": "none", "adjudicator": release},
    )
    assert response["decision"] == "block"
    assert calls == []


def test_post_write_source_path_is_not_required_for_pending_contract(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")
    assert _rules(target.read_text(encoding="utf-8")) == set()
