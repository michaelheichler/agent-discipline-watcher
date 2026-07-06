from scanner import scan_all
from config import effective_config


def test_scan_all_normalizes_enabled_families():
    text = "We util" + "ize this\n# " + ("TO" + "DO") + " later\nbad\u2014dash"
    findings = scan_all("sample.md", text, {})
    keys = {(item["family"], item["rule"], item["line"]) for item in findings}
    assert ("english", "utilize", 1) in keys
    assert ("punctuation", "banned_dash", 3) in keys
    code_findings = scan_all("sample.py", "# " + ("TO" + "DO") + " later\n", {})
    code_keys = {(item["family"], item["rule"], item["line"]) for item in code_findings}
    assert ("clean_code", "deferred_work_comment", 1) in code_keys
    for item in findings:
        assert {"family", "rule", "line", "detail", "force", "snippet", "action"} <= item.keys()
        assert item["force"] is True


def test_scan_all_respects_switches():
    findings = scan_all("sample.txt", "util" + "ize\nbad\u2014dash", {"english": False})
    assert {item["family"] for item in findings} == {"punctuation"}


def test_punctuation_rules_cover_diagnosed_marks():
    text = "\n".join([
        "left" + "--" + "right",
        "a thing" + chr(59) + " another thing",
        "your" + chr(39) + "s",
        "1990" + chr(39) + "s",
        "twenty - three",
        "its" + chr(39),
    ])
    findings = scan_all("sample.md", text, {"english": False, "clean_code": False})
    rules = {item["rule"] for item in findings}
    assert {"dash_break", "semicolon_splice", "pronoun_apostrophe", "decade_apostrophe", "spaced_hyphen"} <= rules
    assert all(item["force"] is True for item in findings)


def test_punctuation_advisories_and_markup_stripping():
    findings = scan_all(
        "sample.md",
        "\n".join([
            "I came home, I went to bed.",
            "She said \"hello\", then left.",
            "Use `left--right` as a bad example.",
            "<code>bad" + chr(0x2014) + "dash</code>",
            "Use &mdash; only as an entity example.",
        ]),
        {"english": False, "clean_code": False},
    )
    by_rule = {item["rule"]: item for item in findings}
    assert by_rule["comma_splice"]["force"] is False
    assert by_rule["quote_punctuation"]["force"] is False
    assert "dash_break" not in by_rule
    assert "banned_dash" not in by_rule


def test_english_rules_cover_filler_and_inflation():
    text = "\n".join([
        "At the end of the day, we leverage a wide variety of tools in order to delve into it.",
        "In today's fast-paced world, the cache matters.",
        "There is a setting that controls retries.",
    ])
    rules = {item["rule"] for item in scan_all("sample.md", text, {"punctuation": False, "clean_code": False})}
    assert {"filler", "inflated_diction", "vague_quantity", "wordiness", "ai_tell", "filler_opener", "expletive_there"} <= rules


def test_english_strips_inline_code_quotes_and_hidden_html():
    text = "\n".join([
        "The quoted word `util" + "ize` is an example.",
        "The quoted word \"util" + "ize\" is an example.",
        "<style>.x { color: red; }</style>",
        "<code>util" + "ize</code>",
    ])
    assert scan_all("sample.md", text, {"punctuation": False, "clean_code": False}) == []


def test_clean_code_rules_cover_common_comment_faults():
    text = "\n".join([
        "# Bug A: bad path",
        "# hacky workaround",
        "# def unused():",
        "# " + ("TO" + "DO") + " later",
        "# " + ("FIX" + "ME") + " later",
        "# " + ("X" + "XX") + " later",
        "# " + ("HA" + "CK") + " later",
        "def test_empty(): pass",
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert {"bug_label_comment", "apology_comment", "commented_code", "deferred_work_comment", "hollow_test"} <= rules


def test_clean_code_restores_old_structural_floor():
    long_func = "def test_big():\n" + "\n".join("    x%s = %s" % (i, i) for i in range(81))
    text = "\n".join([
        '"""module summary',
        'second line"""',
        "# changed list to dict",
        "def test_empty():",
        "    pass",
        long_func,
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert {"docstring_narration", "version_control_comment", "hollow_test", "function_too_long"} <= rules


def test_clean_code_file_length_thresholds():
    warn = scan_all("sample.py", "\n".join("x = 1" for _ in range(500)), {"punctuation": False, "english": False})
    hard = scan_all("sample.py", "\n".join("x = 1" for _ in range(1000)), {"punctuation": False, "english": False})
    warn_rows = [item for item in warn if item["rule"] == "file_getting_long"]
    hard_rows = [item for item in hard if item["rule"] == "file_too_long"]
    assert warn_rows and warn_rows[0]["force"] is False
    assert hard_rows and hard_rows[0]["force"] is True


def test_clean_code_hollow_test_block_in_js():
    text = 'test("x", () => {\n  run();\n});\n'
    rules = {item["rule"] for item in scan_all("sample.js", text, {"punctuation": False, "english": False})}
    assert "hollow_test" in rules


def test_clean_code_blocks_prose_comment_blocks_in_code_files():
    findings = scan_all(
        "sample.py",
        "# first line\n# second line\nprint(1)\n",
        {"punctuation": False, "english": False},
    )
    blocks = [item for item in findings if item["rule"] == "prose_comment_block"]
    assert len(blocks) == 1
    assert blocks[0]["family"] == "clean_code"
    assert blocks[0]["force"] is True
    assert "wiki page" in blocks[0]["action"]
    assert "Create one or update" in blocks[0]["action"]


def test_clean_code_allows_standard_license_header_blocks():
    text = "\n".join([
        "# SPDX-FileCopyrightText: 2026 Example",
        "# SPDX-License-Identifier: MIT",
        "",
        "print(1)",
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "prose_comment_block" not in rules


def test_clean_code_comment_block_rule_spares_single_comment_docs_and_config():
    cfg = {"punctuation": False, "english": False}
    assert "prose_comment_block" not in {item["rule"] for item in scan_all("sample.py", "# reset before enable\nreset()\n", cfg)}
    assert "prose_comment_block" not in {item["rule"] for item in scan_all("tool.py", "#!/usr/bin/env python3\n# coding: utf-8\nprint(1)\n", cfg)}
    text = "# first line\n# second line\n# " + ("TO" + "DO") + " later\n"
    for path in ("README.md", "notes.txt", "settings.toml", "config.yaml", "data.json"):
        assert not [item for item in scan_all(path, text, cfg) if item["family"] == "clean_code"]


def test_project_config_is_found_from_child_directory(tmp_path):
    project = tmp_path / "project"
    child = project / "src"
    child.mkdir(parents=True)
    (project / ".agent-discipline.json").write_text('{"checks":{"english":false}}', encoding="utf-8")
    assert effective_config(cwd=child)["english"] is False


if __name__ == "__main__":
    test_scan_all_normalizes_enabled_families()
    test_scan_all_respects_switches()
    test_punctuation_rules_cover_diagnosed_marks()
    test_punctuation_advisories_and_markup_stripping()
    test_english_rules_cover_filler_and_inflation()
    test_english_strips_inline_code_quotes_and_hidden_html()
    test_clean_code_rules_cover_common_comment_faults()
    test_clean_code_restores_old_structural_floor()
    test_clean_code_file_length_thresholds()
    test_clean_code_hollow_test_block_in_js()
    test_clean_code_blocks_prose_comment_blocks_in_code_files()
    test_clean_code_allows_standard_license_header_blocks()
    test_clean_code_comment_block_rule_spares_single_comment_docs_and_config()
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_project_config_is_found_from_child_directory(Path(directory))
