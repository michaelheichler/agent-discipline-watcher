import pytest

from markup import RegionKind, extract_regions, render_regions
from scanner import scan_all


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


def test_protected_rules_still_scan_ignored_regions() -> None:
    marker = "craftsman" + "-ignore: PY002"
    source = f"<style>/* {marker} */</style>\n"

    assert ("suppression_escape_hatch", 1) in _rows("page.html", source)


@pytest.mark.parametrize("tag", ("script", "style", "code", "pre"))
def test_unclosed_embedded_blocks_do_not_leak_into_visible_prose(tag: str) -> None:
    source = f"<{tag}>\nfirst clause; second clause\n"

    assert not {rule for rule, _line in _rows("component.vue", source)} & {"prose_semicolon"}
