import pytest

from lib.markup import RegionKind, extract_regions, render_regions
from lib.scanner import scan_all


HTML_SOURCE = """<main data-note="attribute; not prose">
  <style>
    :root { --accent: #fff; }
    a[href="https://example.com/a;b"] { color: var(--accent); }
  </style>
  <script>
    const message = "first clause; second clause";
    // Returns the visible label
  </script>
  <code>const example = "first clause; second clause";</code>
  <pre>first clause; second clause</pre>
  <p>Visible first clause; visible second clause.</p>
</main>
"""


VUE_SOURCE = """<template>
  <button :title="label + ';' + suffix" style="color: red;">
    Visible first clause; visible second clause.
  </button>
</template>
<script setup>
const label = "first clause; second clause"
// Returns the visible label
// Keep this because old clients omit the field
</script>
<style scoped>
:root { --accent: #fff; }
.button { color: var(--accent); }
</style>
"""


def _rows(path: str, source: str) -> set[tuple[str, int]]:
    return {(row["rule"], row["line"]) for row in scan_all(path, source, {})}


def test_html_regions_classify_embedded_languages_and_preserve_host_lines() -> None:
    regions = extract_regions("page.html", HTML_SOURCE)

    style = [region for region in regions if region.kind is RegionKind.STYLE]
    script = [region for region in regions if region.kind is RegionKind.SCRIPT]
    ignored = [region for region in regions if region.kind is RegionKind.IGNORED]
    prose_regions = [region for region in regions if region.kind is RegionKind.VISIBLE_PROSE]

    assert [(region.start_line, region.end_line) for region in style] == [(2, 5)]
    assert [(region.start_line, region.end_line) for region in script] == [(6, 9)]
    assert [(region.start_line, region.end_line) for region in ignored] == [(10, 10), (11, 11)]
    assert any(region.start_line <= 12 <= region.end_line for region in prose_regions)
    prose = render_regions(HTML_SOURCE, regions, {RegionKind.VISIBLE_PROSE})
    assert prose.splitlines()[11].strip() == "Visible first clause; visible second clause."
    assert all(not line.strip() for line in prose.splitlines()[:11])


@pytest.mark.parametrize(
    ("path", "source", "expected_line"),
    (("page.html", HTML_SOURCE, 12), ("component.vue", VUE_SOURCE, 3)),
)
def test_mixed_language_scans_only_visible_prose_for_semicolon_splices(
    path: str, source: str, expected_line: int
) -> None:
    rows = _rows(path, source)

    assert ("prose_semicolon", expected_line) in rows
    assert {line for rule, line in rows if rule == "prose_semicolon"} == {expected_line}


def test_embedded_script_comments_are_comments_but_attributes_and_bodies_are_not() -> None:
    rows = _rows("component.vue", VUE_SOURCE)

    assert ("what_comment", 8) in rows
    assert ("weak_why_comment", 9) not in rows
    assert not {line for rule, line in rows if rule == "what_comment"} - {8}


def test_generated_and_directive_comment_behavior_is_preserved_in_embedded_script() -> None:
    source = """<script>
// @ts-expect-error
const row = load()
// Returns the row
</script>
"""

    rows = _rows("component.vue", source)

    assert ("what_comment", 4) in rows
    assert not {rule for rule, _line in rows} & {"prose_comment_block", "narration_comment"}


def test_embedded_script_strings_are_not_scanned_as_comments() -> None:
    source = "<script>\nconst message = \"// " + ("TO" + "DO") + " later\";\n</script>\n"

    rows = _rows("component.vue", source)

    assert not {rule for rule, _line in rows} & {"deferred_work_comment", "commented_code"}


def test_html_what_comment_is_a_hard_block() -> None:
    rows = _rows("component.vue", "<template>\n<!-- Increment the counter. -->\n</template>\n")
    assert ("what_comment", 2) in rows


def test_javascript_block_comment_is_a_hard_block() -> None:
    source = "<script>\n/**\n * Increment the counter.\n */\nconst value = 1\n</script>\n"
    rows = _rows("component.vue", source)
    assert ("what_comment", 3) in rows
    assert ("prose_comment_block", 2) in rows


def test_javascript_template_string_comment_markers_are_not_comments() -> None:
    source = "const example = `/*\n * Increment the counter.\n */`\nconst value = 1\n"
    rows = _rows("example.js", source)
    assert not {rule for rule, _line in rows} & {"what_comment", "prose_comment_block"}


def test_spdx_block_header_is_not_a_prose_comment() -> None:
    source = "/*\n * SPDX-License-Identifier: MIT\n * Copyright 2026 Example\n */\nint value = 1;\n"
    rows = _rows("example.c", source)
    assert not {rule for rule, _line in rows} & {"what_comment", "prose_comment_block"}


def test_protected_rules_still_scan_ignored_regions() -> None:
    marker = "craftsman" + "-ignore: PY002"
    source = f"<style>/* {marker} */</style>\n"

    assert ("suppression_escape_hatch", 1) in _rows("page.html", source)


@pytest.mark.parametrize("tag", ("script", "style", "code", "pre"))
def test_unclosed_embedded_blocks_do_not_leak_into_visible_prose(tag: str) -> None:
    source = f"<{tag}>\nfirst clause; second clause\n"

    assert not {rule for rule, _line in _rows("component.vue", source)} & {"prose_semicolon"}


def test_prose_semicolon_spares_hex_and_alnum_html_entities() -> None:
    hex_entity = "Use the char &#x2014; in prose here today, plainly.\n"
    alnum_entity = "Use the char &frac12; in prose here today, plainly.\n"

    assert "prose_semicolon" not in {rule for rule, _line in _rows("notes.md", hex_entity)}
    assert "prose_semicolon" not in {rule for rule, _line in _rows("notes.md", alnum_entity)}


def test_english_hides_code_tag_with_space_before_closing_bracket() -> None:
    source = (
        "Prose sentence here.\n"
        "<code>value = compute() in order to cache it</code >\n"
        "More prose after.\n"
    )

    assert "wordiness" not in {rule for rule, _line in _rows("doc.md", source)}


FRONTMATTER_DOC = (
    "---\n"
    "name: agent-discipline-watcher\n"
    "description: Use when an agent writes files and needs a check.\n"
    "---\n"
    "\n"
    "The rule is this: a colon inside a sentence still blocks.\n"
)


def _colon_lines(path: str, source: str) -> set[int]:
    return {row["line"] for row in scan_all(path, source, {"english": False, "clean_code": False}) if row["rule"] == "prose_colon"}


@pytest.mark.parametrize("path", ("skill.md", "guide.markdown", "page.mdx"))
def test_markdown_frontmatter_masks_its_keys_but_keeps_body_colons(path: str) -> None:
    assert _colon_lines(path, FRONTMATTER_DOC) == {6}


def test_markdown_frontmatter_closes_on_the_yaml_document_end_marker() -> None:
    source = "---\nname: agent-discipline-watcher\n...\nPlain body prose.\n"

    assert _colon_lines("skill.md", source) == set()


def test_unclosed_leading_delimiter_is_not_markdown_frontmatter() -> None:
    source = "---\nname: agent-discipline-watcher\n\nPlain body prose.\n"

    assert _colon_lines("skill.md", source) == {2}


def test_markdown_frontmatter_must_open_on_the_first_line() -> None:
    source = "Title line.\n---\nname: agent-discipline-watcher\n---\n"

    assert _colon_lines("skill.md", source) == {3}


def test_frontmatter_masking_leaves_the_asciidoc_block_rule_alone() -> None:
    source = "----\nin order to\n----\n"

    assert "wordiness" not in {rule for rule, _line in _rows("guide.adoc", source)}


def test_oversized_list_counts_items_with_indented_continuation_text() -> None:
    items = "".join(f"- item {number}\n  continuation text for item {number}\n" for number in range(9))

    assert "oversized_list" in {rule for rule, _line in _rows("doc.md", items)}
