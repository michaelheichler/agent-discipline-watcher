"""Protects facts because automatic cleanup must not rewrite hidden code or tool fields."""
import rewrite

BAD_DASH = chr(0x2014)


def test_prose_cleanup_replaces_dashes_and_wordiness() -> None:
    text = f"It is important to note that we utilize this tool {BAD_DASH} in order to move quickly.\n"
    result = rewrite.rewrite_text("README.md", text, {})
    assert BAD_DASH not in result.text
    assert "utilize" not in result.text
    assert "in order to" not in result.text
    assert result.counts["dashes"] == 1
    assert result.counts["prose"] >= 2


def test_cleanup_preserves_inline_code_and_code_strings() -> None:
    prose = rewrite.rewrite_text(
        "README.md", f"Use `left{BAD_DASH}right` but fix left{BAD_DASH}right.\n", {}
    )
    code = rewrite.rewrite_text("example.py", f'value = "left{BAD_DASH}right"\n', {})
    assert f"`left{BAD_DASH}right`" in prose.text
    assert "fix left-right" in prose.text
    assert code.text == f'value = "left{BAD_DASH}right"\n'


def test_cleanup_removes_bad_comments_and_preserves_why() -> None:
    text = "# Now we load the cache\n# Keep this because callers require stable identity\nvalue = 1\n"
    result = rewrite.rewrite_text("example.py", text, {})
    assert "Now we load" not in result.text
    assert "because callers require stable identity" in result.text
    assert result.counts["comments"] == 1


def test_long_sentence_split_preserves_words() -> None:
    words = [f"word{number}" for number in range(45)]
    original = " ".join(words) + ".\n"
    result = rewrite.rewrite_text("README.md", original, {"sentence_word_cap": 20})
    assert "\n" in result.text.strip()
    for word in words:
        assert word in result.text
    assert result.counts["sentences"] >= 1


def test_oversized_list_is_grouped_without_dropping_items() -> None:
    original = "".join(f"- item {number}\n" for number in range(5))
    result = rewrite.rewrite_text("README.md", original, {"list_item_cap": 2})
    assert result.text.count("\n\n") == 2
    for number in range(5):
        assert f"item {number}" in result.text
    assert result.counts["lists"] == 2


def test_write_input_copy_preserves_unknown_fields() -> None:
    original = f"Use this {BAD_DASH} now.\n"
    tool_input = {"file_path": "/tmp/a.md", "content": original, "future": 7}
    result = rewrite.rewrite_tool_input("Write", tool_input, {})
    assert result.tool_input["future"] == 7
    assert result.tool_input["file_path"] == "/tmp/a.md"
    assert BAD_DASH not in result.tool_input["content"]
    assert tool_input["content"] == original


def test_edit_rewrites_only_new_string() -> None:
    tool_input = {
        "file_path": "/tmp/a.md",
        "old_string": f"old {BAD_DASH} text",
        "new_string": f"new {BAD_DASH} text",
        "replace_all": False,
    }
    result = rewrite.rewrite_tool_input("Edit", tool_input, {})
    assert result.tool_input["old_string"] == f"old {BAD_DASH} text"
    assert BAD_DASH not in result.tool_input["new_string"]
    assert result.tool_input["replace_all"] is False


def test_multiedit_rewrites_every_new_string_and_keeps_other_fields() -> None:
    tool_input = {
        "file_path": "/tmp/a.md",
        "edits": [
            {"old_string": "keep1", "new_string": f"one {BAD_DASH} two", "replace_all": True},
            {"old_string": "keep2", "new_string": f"three {BAD_DASH} four", "future": "x"},
        ],
    }
    result = rewrite.rewrite_tool_input("MultiEdit", tool_input, {})
    edits = result.tool_input["edits"]
    assert BAD_DASH not in edits[0]["new_string"]
    assert BAD_DASH not in edits[1]["new_string"]
    assert edits[0]["old_string"] == "keep1"
    assert edits[0]["replace_all"] is True
    assert edits[1]["future"] == "x"
    assert result.counts["dashes"] == 2
    assert result.changed is True
    assert tool_input["edits"][0]["new_string"] == f"one {BAD_DASH} two"


def test_notebookedit_rewrites_new_source() -> None:
    tool_input = {
        "notebook_path": "/tmp/nb.ipynb",
        "new_source": f"# Now we build the cache {BAD_DASH} fast\nvalue = 1\n",
        "cell_id": "abc",
    }
    result = rewrite.rewrite_tool_input("NotebookEdit", tool_input, {})
    assert "Now we build" not in result.tool_input["new_source"]
    assert result.tool_input["cell_id"] == "abc"
    assert result.changed is True


ROUND_TRIP_WORDS = [f"word{number}" for number in range(45)]
ROUND_TRIP_BODY = (
    f"It is important to note that we utilize this tool {BAD_DASH} in order to move quickly.\n"
    + " ".join(ROUND_TRIP_WORDS) + ".\n"
    + "".join(f"- item {number}\n" for number in range(5))
    + "```\ncode with -- inside stays\n```\n"
    + "Use `left--right` inline and see https://example.com/a--b.\n"
    + "| col a--b | col c |\n"
)


def _round_trip_result() -> rewrite.ToolRewrite:
    tool_input = {"file_path": "/tmp/a.md", "content": ROUND_TRIP_BODY}
    config = {"sentence_word_cap": 20, "list_item_cap": 2}
    return rewrite.rewrite_tool_input("Write", tool_input, config)


def test_round_trip_rewrite_updates_content_and_leaves_masked_regions() -> None:
    updated = _round_trip_result().tool_input["content"]
    assert BAD_DASH not in updated
    assert "; " not in updated
    assert "utilize" not in updated
    for word in ROUND_TRIP_WORDS:
        assert word in updated
    for number in range(5):
        assert f"item {number}" in updated
    assert "code with -- inside stays" in updated
    assert "`left--right`" in updated
    assert "https://example.com/a--b" in updated
    assert "col a--b" in updated


def test_round_trip_rewrite_matches_summary_counts() -> None:
    result = _round_trip_result()
    assert result.counts["dashes"] >= 1
    assert result.counts["prose"] >= 1
    assert result.counts["sentences"] >= 1
    assert result.counts["lists"] == 2

    summary = rewrite.summary(result.counts)
    assert f"{result.counts['dashes']} banned dashes replaced" in summary
    assert f"{result.counts['prose']} prose cuts" in summary
    assert f"{result.counts['sentences']} sentences split" in summary


def test_round_trip_rewrite_does_not_mutate_original_input() -> None:
    tool_input = {"file_path": "/tmp/a.md", "content": ROUND_TRIP_BODY}
    rewrite.rewrite_tool_input("Write", tool_input, {"sentence_word_cap": 20, "list_item_cap": 2})
    assert tool_input["content"] == ROUND_TRIP_BODY


CODE_BODY = (
    "# Now we load the cache\n"
    "# relied on by external callers\n"
    f"value = \"left{BAD_DASH}right\"\n"
)


def test_round_trip_code_rewrite_deletes_narration_and_retains_weak_why() -> None:
    tool_input = {"file_path": "/tmp/a.py", "content": CODE_BODY}
    result = rewrite.rewrite_tool_input("Write", tool_input, {})
    updated = result.tool_input["content"]

    assert "Now we load" not in updated
    assert "relied on by external callers" in updated
    assert f'value = "left{BAD_DASH}right"' in updated
    assert result.counts["comments"] == 1
    assert result.counts["weak_why"] == 1
    assert tool_input["content"] == CODE_BODY

    summary = rewrite.summary(result.counts)
    assert f"{result.counts['comments']} comments removed" in summary
    assert "1 WHY comments need a concrete constraint or consequence" in summary
