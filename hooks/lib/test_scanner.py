import json
from pathlib import Path

import escalate
import scanner
from config import effective_config
from scanner import scan_all


def test_length_caps_read_the_adw_env_names(monkeypatch):
    monkeypatch.setenv("ADW_FUNC_BLOCK_LINES", "2")
    body = "def wide():\n" + "".join(f"    x{n} = {n}\n" for n in range(6))
    rules = [row["rule"] for row in scanner.scan_all("a.py", body, {})]
    assert "function_too_long" in rules


def test_length_caps_still_accept_the_merged_package_env_names(monkeypatch):
    monkeypatch.delenv("ADW_FUNC_BLOCK_LINES", raising=False)
    monkeypatch.setenv("CLEANCODER_FUNC_BLOCK_LINES", "2")
    body = "def wide():\n" + "".join(f"    x{n} = {n}\n" for n in range(6))
    rules = [row["rule"] for row in scanner.scan_all("a.py", body, {})]
    assert "function_too_long" in rules


def test_adw_env_name_wins_over_the_legacy_alias(monkeypatch):
    monkeypatch.setenv("ADW_FUNC_BLOCK_LINES", "500")
    monkeypatch.setenv("CLEANCODER_FUNC_BLOCK_LINES", "2")
    body = "def wide():\n" + "".join(f"    x{n} = {n}\n" for n in range(6))
    rules = [row["rule"] for row in scanner.scan_all("a.py", body, {})]
    assert "function_too_long" not in rules


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
    assert {"dash_break", "prose_semicolon", "pronoun_apostrophe", "decade_apostrophe", "spaced_hyphen"} <= rules
    assert all(item["force"] is True for item in findings)


def test_uncertain_punctuation_is_ignored_and_markup_is_stripped():
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
    assert findings == []


def test_punctuation_url_scheme_slashes_are_not_a_comment_marker():
    sep = ";"
    shell = "\n".join([
        'if curl -sk "https://${REG}/v2/" 2>/dev/null' + sep + " then",
        '|| die "reach https://${REG} (insecure? try FLAG=true' + sep + ' down? escape)."',
    ])
    findings = scan_all("deploy.sh", shell, {"english": False, "clean_code": False})
    assert not [item for item in findings if item["rule"] == "prose_semicolon"]

    comment_splice = "// first clause here" + sep + " second clause follows on"
    real = scan_all("app.js", comment_splice, {"english": False, "clean_code": False})
    assert [item for item in real if item["rule"] == "prose_semicolon"]


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


def test_readability_regex_rules_cover_closers_openers_stacked_hedges_and_idioms():
    text = "\n".join([
        "Hope this helps.",
        "Great question, the answer is six.",
        "This might perhaps fail.",
        "We can circle back tomorrow.",
    ])
    rules = {row["rule"] for row in scan_all("sample.md", text)}
    assert {"ai_closer", "greeting_opener", "hedge_stack", "corporate_idiom"} <= rules


def test_readability_regex_rules_spare_plain_prose_and_single_hedges():
    text = "\n".join([
        "The answer might change.",
        "Perhaps the answer will change.",
        "The team will meet tomorrow.",
        "That was a great question from the survey.",
    ])
    rules = {row["rule"] for row in scan_all("sample.md", text)}
    assert not rules & {"ai_closer", "greeting_opener", "hedge_stack", "corporate_idiom"}


def test_readability_regex_rules_scan_code_comments_under_clean_code():
    text = "\n".join([
        "x = 1",
        "# Hope this helps.",
        "x = 2",
        "# Great question, this value is two.",
        "x = 3",
        "# This might perhaps change because the input is unstable.",
        "x = 4",
        "# Circle back because the remote service is offline.",
    ])
    rows = scan_all("sample.py", text, {"punctuation": False, "english": False})
    readability = [row for row in rows if row["rule"] in {
        "ai_closer", "greeting_opener", "hedge_stack", "corporate_idiom",
    }]
    assert {row["rule"] for row in readability} == {
        "ai_closer", "greeting_opener", "hedge_stack", "corporate_idiom",
    }
    assert {row["family"] for row in readability} == {"clean_code"}


def test_readability_rules_default_to_observe():
    gates = effective_config({})["rule_gates"]
    for rule in (
        "ai_closer", "greeting_opener", "hedge_stack", "corporate_idiom",
        "long_sentence", "oversized_list",
    ):
        assert gates[rule] == "observe"


def test_long_sentence_uses_a_generous_default_cap():
    forty_words = "This " + " ".join("word" for _ in range(39)) + "."
    forty_one_words = "This " + " ".join("word" for _ in range(40)) + "."
    assert "long_sentence" not in {row["rule"] for row in scan_all("sample.md", forty_words)}
    assert "long_sentence" in {row["rule"] for row in scan_all("sample.md", forty_one_words)}


def test_long_sentence_splits_on_punctuation_before_uppercase():
    first = "First " + " ".join("word" for _ in range(20)) + "."
    second = "Second " + " ".join("word" for _ in range(20)) + "."
    rules = {row["rule"] for row in scan_all("sample.md", first + " " + second)}
    assert "long_sentence" not in rules


def test_oversized_list_uses_eight_item_default_cap():
    eight_items = "\n".join(f"- item {number}" for number in range(8))
    nine_items = "\n".join(f"- item {number}" for number in range(9))
    assert "oversized_list" not in {row["rule"] for row in scan_all("sample.md", eight_items)}
    assert "oversized_list" in {row["rule"] for row in scan_all("sample.md", nine_items)}


def test_prose_structure_thresholds_accept_config():
    sentence = "One two three four."
    configured = {row["rule"] for row in scan_all("sample.md", sentence, {"sentence_word_cap": 3})}
    assert "long_sentence" in configured


def test_int_setting_uses_environment_without_config(monkeypatch):
    monkeypatch.setenv("ADW_LIST_ITEM_CAP", "1")
    assert scanner._int_setting({}, "list_item_cap", "ADW_LIST_ITEM_CAP", 8) == 1


def test_explicit_config_wins_over_environment(monkeypatch):
    monkeypatch.setenv("ADW_SENTENCE_WORD_CAP", "1")
    text = "One two three four."
    rules = {row["rule"] for row in scan_all("sample.md", text, {"sentence_word_cap": 10})}
    assert "long_sentence" not in rules


def test_prose_structure_skips_both_fence_styles():
    long_line = "Sentence " + " ".join("word" for _ in range(45)) + "."
    long_list = "\n".join(f"- item {number}" for number in range(10))
    for marker in ("```", "~~~"):
        text = f"{marker}\n{long_line}\n{long_list}\n{marker}\n"
        rules = {row["rule"] for row in scan_all("sample.md", text)}
        assert not rules & {"long_sentence", "oversized_list"}, marker


def test_prose_structure_skips_markdown_tables():
    long_cell = " ".join("word" for _ in range(45))
    text = f"| Heading |\n| --- |\n| {long_cell} |\n"
    rules = {row["rule"] for row in scan_all("sample.md", text)}
    assert "long_sentence" not in rules
    assert list(scanner._markdown_prose_lines("Heading | Detail\n--- | ---"))[-1] == (2, "")


def test_prose_structure_scans_long_sentences_containing_pipes():
    long_prefix = "This " + " ".join("word" for _ in range(40))
    for suffix in ("input | output.", "Value = Left | Right."):
        rules = {row["rule"] for row in scan_all("sample.md", long_prefix + " " + suffix)}
        assert "long_sentence" in rules


def test_prose_structure_counts_list_items_containing_pipes():
    items = [f"- item {number}" for number in range(9)]
    items[4] += " | alternative"
    rules = {row["rule"] for row in scan_all("sample.md", "\n".join(items))}
    assert "oversized_list" in rules


def test_prose_structure_skips_blockquotes():
    text = "> Quoted " + " ".join("word" for _ in range(45)) + "."
    rules = {row["rule"] for row in scan_all("sample.md", text)}
    assert "long_sentence" not in rules


def test_prose_structure_skips_link_reference_lines():
    long_target = "".join(f"part{number}/" for number in range(45))
    text = f"[source]: https://example.com/{long_target}\n"
    rules = {row["rule"] for row in scan_all("sample.md", text)}
    assert "long_sentence" not in rules


def test_clean_code_rules_cover_common_comment_faults():
    text = "\n".join([
        "# Bug" + " A: bad path",
        "# ha" + "cky worka" + "round",
        "# def unused():",
        "# " + ("TO" + "DO") + " later",
        "# " + ("FIX" + "ME") + " later",
        "# " + ("X" + "XX") + " later",
        "# " + ("HA" + "CK") + " later",
        "def test_empty(): pass",
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert {"bug_label_comment", "apology_comment", "commented_code", "deferred_work_comment", "hollow_test"} <= rules


def test_clean_code_blocks_explicit_narration_starters():
    text = "\n".join([
        "# " + "now validate the input",
        "// " + "this function returns the socket",
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "narration_comment" in rules


def test_craftsman_suppression_marker_is_always_blocked():
    marker = "craftsman" + "-ignore: PY002"
    for path in ("sample.py", "README.md", "settings.toml"):
        findings = scan_all(
            path,
            "# " + marker + "\n",
            {"punctuation": False, "english": False, "clean_code": False},
        )
        rows = [item for item in findings if item["rule"] == "suppression_escape_hatch"]
        assert len(rows) == 1
        assert rows[0]["force"] is True
    exempt = scan_all(
        "/repo/generated/sample.py",
        "# " + marker + "\n",
        {"exempt_paths": ["generated/*"]},
    )
    assert [item for item in exempt if item["rule"] == "suppression_escape_hatch"]


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
    hard_rows = [item for item in hard if item["rule"] == "file_too_long"]
    assert warn == []
    assert hard_rows and hard_rows[0]["force"] is True


def test_clean_code_hollow_test_block_in_js():
    text = 'test("x", () => {\n  run();\n});\n'
    rules = {item["rule"] for item in scan_all("sample.js", text, {"punctuation": False, "english": False})}
    assert "hollow_test" in rules


def test_clean_code_hollow_test_spares_js_blocks_with_nested_braces_before_assert():
    text = "\n".join([
        'describe("suite", () => {',
        "  beforeEach(() => {",
        "    reset();",
        "  });",
        '  it("asserts after a nested block", () => {',
        "    stub((path) => {",
        "      if (path) {",
        "        return fail();",
        "      }",
        "      return ok();",
        "    });",
        "    expect(run()).toBe(true);",
        "  });",
        "});",
        "",
    ])
    rules = {item["rule"] for item in scan_all("sample.js", text, {"punctuation": False, "english": False})}
    assert "hollow_test" not in rules


def test_clean_code_hollow_test_spares_pass_substrings_in_python_test_names():
    text = "\n".join([
        "def test_lane_does_not_bypass_signing() -> None:",
        "    assert lane() == 'signed'",
        "",
        "",
        "def test_render_passes_root_raw() -> None:",
        "    assert render() == 'raw'",
        "",
    ])
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "hollow_test" not in rules


def test_clean_code_docstring_rule_spares_multiline_string_assignments():
    text = "def helper():\n    payload = 'a\\nb'\n    return payload\n"
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "docstring_narration" not in rules


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


def test_default_config_scans_tweakcc_prompt_snapshots():
    text = "upstream\u2014prompt"
    prompt = "/Users/example/.tweakcc/system-prompts/upstream.md"
    control = "/Users/example/.tweakcc/config.json"
    assert {item["rule"] for item in scan_all(prompt, text, {})} == {"banned_dash"}
    assert {item["rule"] for item in scan_all(control, text, {})} == {"banned_dash"}


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
    test_uncertain_punctuation_is_ignored_and_markup_is_stripped()
    test_english_rules_cover_filler_and_inflation()
    test_english_strips_inline_code_quotes_and_hidden_html()
    test_clean_code_rules_cover_common_comment_faults()
    test_clean_code_blocks_explicit_narration_starters()
    test_clean_code_restores_old_structural_floor()
    test_clean_code_file_length_thresholds()
    test_clean_code_hollow_test_block_in_js()
    test_clean_code_hollow_test_spares_js_blocks_with_nested_braces_before_assert()
    test_clean_code_hollow_test_spares_pass_substrings_in_python_test_names()
    test_clean_code_docstring_rule_spares_multiline_string_assignments()
    test_clean_code_blocks_prose_comment_blocks_in_code_files()
    test_clean_code_allows_standard_license_header_blocks()
    test_clean_code_comment_block_rule_spares_single_comment_docs_and_config()
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_project_config_is_found_from_child_directory(Path(directory))


def test_exempt_paths_config_skips_configurable_families():
    text = (
        "# Keep this HYG-99 fixture because exempt paths must skip prose blocks\n"
        "# Preserve a second line because the fixture needs a comment run\n"
        "x = 1\n"
    )
    cfg = {"exempt_paths": ["scripts/legacy_contract_test.py"]}
    assert scanner.scan_all("/repo/scripts/legacy_contract_test.py", text, cfg) == []
    assert scanner.scan_all("/repo/scripts/other_file.py", text, cfg) != []


def test_dockerfile_parser_directive_not_a_prose_comment_block():
    text = "# syntax=10.0.0.105/dockerhub-proxy/docker/dockerfile:1.7\n# escape=`\nFROM alpine\n"
    rules = [f["rule"] for f in scanner.scan_all("FrontEnd/Dockerfile", text)]
    assert "prose_comment_block" not in rules
    prose = "# first narrating line of prose\n# second narrating line of prose\nFROM alpine\n"
    rules = [f["rule"] for f in scanner.scan_all("FrontEnd/Dockerfile", prose)]
    assert "prose_comment_block" in rules


def test_config_shell_argument_separator_is_not_a_dash_break():
    cfg = {"english": False, "clean_code": False}
    shellish = "run: grep foo " + "--" + " dir"
    assert scan_all("ci.yaml", shellish, cfg) == []
    prose = "first clause " + "--" + " second clause"
    rules = {item["rule"] for item in scan_all("notes.md", prose, cfg)}
    assert "dash_break" in rules


def test_read_scannable_skips_oversized_and_binary_files(tmp_path):
    cfg = {"max_scan_bytes": 10}
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 4, encoding="utf-8")
    assert scanner.read_scannable(big, cfg) is None
    blob = tmp_path / "blob.py"
    blob.write_bytes(b"x = 1\n" + b"\0" + b"y = 2\n")
    assert scanner.read_scannable(blob, {"max_scan_bytes": 1000}) is None
    small = tmp_path / "small.py"
    small.write_text("x = 1\n", encoding="utf-8")
    assert scanner.read_scannable(small, cfg) == "x = 1\n"


def test_scannable_text_caps_length_and_nul_bytes():
    assert scanner.scannable_text("x" * 20, {"max_scan_bytes": 10}) is None
    assert scanner.scannable_text("a\0b", {"max_scan_bytes": 100}) is None
    assert scanner.scannable_text("ok", {"max_scan_bytes": 10}) == "ok"


def _what_rows(path, line, config=None):
    findings = scan_all(path, line + "\n", config if config is not None else {})
    return [item for item in findings if item["rule"] == "what_comment"]


def test_why_marker_gate():
    for line in (
        "# cached since v2",
        "# deprecated since 2024",
        "# unchanged since release 3",
        "# since 2020",
        "# valid since v1.4.2",
        "# increments the counter",
        "# this function returns the total",
    ):
        assert len(_what_rows("sample.py", line)) == 1, line
    for line in (
        "# skip since the file is locked",
        "# since the lock is held, bail out early",
        "# retry otherwise the socket leaks",
        "# poll twice, otherwise the race wins",
        "# because the socket leaks",
    ):
        assert _what_rows("sample.py", line) == [], line


def test_what_comment_ignores_exempt_paths_and_the_clean_code_switch():
    line = "# increments the counter"
    switches_off = {"punctuation": False, "english": False, "clean_code": False}
    assert _what_rows("sample.py", line, switches_off)
    assert _what_rows(
        "/repo/generated/sample.py",
        line,
        {"exempt_paths": ["generated/*"], "clean_code": False},
    )


def test_named_config_dotfile_is_config_not_code():
    for path in (".pylintrc", ".npmrc", ".editorconfig", "repo/.pylintrc"):
        assert scanner._is_config(path)
        assert not scanner._is_code(path)


def test_shell_dotfiles_are_still_scanned_as_code():
    for path in (".bashrc", ".zshrc", ".profile", ".envrc", ".bash_profile"):
        assert scanner._is_code(path)
        rules = [row["rule"] for row in scan_all(path, "# sets the path\nexport A=1\n", {})]
        assert "what_comment" in rules


def test_dotfile_with_a_real_extension_stays_code():
    assert scanner._is_code(".hidden.py")


def test_what_comment_does_not_fire_on_a_named_config_dotfile():
    assert scan_all(".pylintrc", "# pins the version\nmax-line-length = 120\n", {}) == []


def test_what_comment_still_fires_on_code():
    rules = [row["rule"] for row in scan_all("a.py", "# increments the counter\nx = 1\n", {})]
    assert "what_comment" in rules


EM_DASH_LINE = "A prose line broken by an " + chr(0x2014) + " dash character.\n"
ENGLISH_LINE = "We utilize the parser here.\n"
CHAT_PATH = "last_assistant_message.md"
DROP_ENGLISH = {"exempt_families": {CHAT_PATH: ["english"]}}


def _rules(path, text, cfg):
    return [row["rule"] for row in scan_all(path, text, cfg)]


def test_exempt_families_drops_only_the_named_family():
    rules = _rules(CHAT_PATH, ENGLISH_LINE, DROP_ENGLISH)
    assert "utilize" not in rules


def test_exempt_families_keeps_punctuation_on_the_same_path():
    rules = _rules(CHAT_PATH, EM_DASH_LINE, DROP_ENGLISH)
    assert "banned_dash" in rules


def test_exempt_families_leaves_other_paths_alone():
    assert "utilize" in _rules("docs/guide.md", ENGLISH_LINE, DROP_ENGLISH)


def test_exempt_families_matches_a_bare_name_inside_a_directory():
    assert "utilize" not in _rules("/tmp/session/" + CHAT_PATH, ENGLISH_LINE, DROP_ENGLISH)


def test_exempt_families_cannot_silence_an_always_blocking_rule():
    cfg = {"exempt_families": {"a.py": ["clean_code", "punctuation", "english"]}}
    assert "what_comment" in _rules("a.py", "# increments the counter\nx = 1\n", cfg)


def test_exempt_families_ignores_an_unknown_family_name():
    cfg = {"exempt_families": {"docs/guide.md": ["typo_family"]}}
    assert "utilize" in _rules("docs/guide.md", ENGLISH_LINE, cfg)


def test_exempt_families_ignores_a_malformed_entry():
    for broken in ({"docs/guide.md": "english"}, {"docs/guide.md": None}, ["english"], "english"):
        assert "utilize" in _rules("docs/guide.md", ENGLISH_LINE, {"exempt_families": broken})


def test_exempt_families_defaults_to_scanning_everything():
    assert effective_config({})["exempt_families"] == {}
    assert "utilize" in _rules("docs/guide.md", ENGLISH_LINE, {})


def test_private_single_line_docstrings_are_what_docstrings():
    samples = (
        'def _bounded_text():\n    """Return bounded control-free built-in text."""\n',
        'def _scan_pending(payload, config):\n    """Scan a pending write and block an undecidable result."""\n',
    )
    for text in samples:
        assert "what_docstring" in _rules("sample.py", text, {}), text


def test_what_opener_prevents_an_incidental_weak_marker_bypass():
    text = (
        'def _run(payload, config):\n'
        '    """Scan a pending write, blocking rather than passing the call through when the gate itself cannot decide."""\n'
    )
    assert "what_docstring" in _rules("sample.py", text, {})


def test_public_identifier_echo_is_a_what_docstring():
    snake = 'def validate_cache_entry():\n    """Validate the cache entry."""\n'
    camel = 'def copyCacheRecord():\n    """Copy cache record."""\n'
    assert "what_docstring" in _rules("sample.py", snake, {})
    assert "what_docstring" in _rules("sample.py", camel, {})


def test_public_first_line_summary_that_does_not_echo_is_allowed():
    text = 'def fetch_record():\n    """Load one stable row from storage."""\n'
    assert "what_docstring" not in _rules("sample.py", text, {})


def test_docstring_why_markers_allow_private_lines_and_public_details():
    private = 'def _fetch():\n    """Keep the local copy because callers rely on object identity."""\n'
    public = (
        'def fetch_record():\n'
        '    """Load one stable row from storage.\n'
        '    Keep the local copy because callers rely on object identity.\n'
        '    """\n'
    )
    assert "what_docstring" not in _rules("sample.py", private, {})
    assert "what_docstring" not in _rules("sample.py", public, {})


def test_public_later_docstring_line_without_why_is_blocked():
    text = (
        'def fetch_record():\n'
        '    """Load one stable row from storage.\n'
        '    Returns the cached row.\n'
        '    """\n'
    )
    assert "what_docstring" in _rules("sample.py", text, {})


def test_numeric_budget_comment_is_an_accepted_false_negative():
    assert _what_rows("sample.py", "# 5ms budget") == []


def test_extended_why_markers_allow_comments():
    lines = (
        "# skip unless the lock is held",
        "# retry except when the response is final",
        "# use bytes instead of text",
        "# preserve order rather than sorting",
        "# " + "work" + "around for the platform parser",
        "# works around a bug in sqlite",
        "# keep the object because callers rely on identity",
        "# reject empty input because callers must retry",
        "# preserve this hook because it is relied on by plugins",
        "# invariant: the queue is never empty",
        "# assumes the caller holds the lock",
        "# requires an absolute path",
        "# guarantees stable ordering",
        "# must return a value or raise",
    )
    for line in lines:
        assert _what_rows("sample.py", line) == [], line


def test_what_opener_covers_inflections_without_becoming_a_rule():
    for text in ("Returns a row", "Scanning entries", "Checks input", "Looping through rows", "Copies data"):
        assert scanner.WHAT_OPENER_RE.match(text), text
    assert not scanner.WHAT_OPENER_RE.match("A stable storage row")


def test_identifier_echo_uses_camel_snake_params_and_jaccard_threshold():
    assert scanner._identifier_echo(("validateCacheEntry",), (), "Validate the cache entry")
    assert scanner._identifier_echo(("copy_record",), ("source_id",), "Copy record source id")
    assert not scanner._identifier_echo(("fetch_record",), (), "Load one stable row from storage")


def test_middle_band_docstring_uses_escalation(monkeypatch):
    calls = []
    monkeypatch.setattr(scanner, "classify_what", lambda text, fallback, config: calls.append((text, fallback)) or True)
    text = 'def validate_cache_item():\n    """Cache item validator."""\n'
    assert "what_docstring" in _rules("sample.py", text, {"escalation": {"enabled": True}})
    assert calls == [("Cache item validator.", False)]


def test_prose_semicolon_fires_in_prose_and_comments():
    mark = chr(59)
    prose = _rules("notes.md", "One reason" + mark + " another reason.\n", {"english": False, "clean_code": False})
    comment = _rules("sample.py", "# Keep this because input is unstable" + mark + " retries are bounded.\n", {})
    assert "prose_semicolon" in prose
    assert "prose_semicolon" in comment


def test_prose_semicolon_spares_code_inline_code_and_entities():
    config = {"english": False, "clean_code": False}
    mark = chr(59)
    assert "prose_semicolon" not in _rules("sample.py", "left = 1" + mark + " right = 2\n", config)
    python_string = 'value = "# reason' + mark + ' detail"\n'
    slash_string = 'const value = "// reason' + mark + ' detail"\n'
    assert "prose_semicolon" not in _rules("sample.py", python_string, config)
    assert "prose_semicolon" not in _rules("sample.js", slash_string, config)
    assert "prose_semicolon" not in _rules("notes.md", "Use `left" + mark + "right` here.\n", config)
    assert "prose_semicolon" not in _rules("notes.md", "Use &semi" + mark + " as an entity.\n", config)


def test_prose_semicolon_spares_css_private_fields_and_config_values():
    mark = chr(59)
    cases = (
        ("style.css", "a { color: #fff" + mark + " }\n"),
        ("sample.js", "class A { #count = 0" + mark + " }\n"),
        ("settings.json", '{"path": "/a' + mark + '/b"}\n'),
        ("database.conf", "Server=x" + mark + "Database=y\n"),
        ("settings.ini", mark + " comment\n"),
    )
    for path, text in cases:
        assert "prose_semicolon" not in _rules(path, text, {}), (path, text)


def test_prose_semicolon_spares_markdown_code_tables_and_urls():
    mark = chr(59)
    fenced = "```js\nconst value = 1" + mark + "\n```\n"
    table = "| Name | Code |\n| --- | --- |\n| value | x = 1" + mark + " |\n"
    url = "https://example.com/a" + mark + "b\n"
    for text in (fenced, table, url):
        assert "prose_semicolon" not in _rules("README.md", text, {}), text
    prose = "The pipe | stays visible" + mark + " rewrite this clause.\n"
    assert "prose_semicolon" in _rules("README.md", prose, {})


def test_google_style_public_docstring_is_structured_not_narration():
    text = (
        'def fetch(items):\n'
        '    """Load stable rows from storage.\n\n'
        '    Args:\n'
        '        items: the rows\n'
        '    Returns:\n'
        '        The rows.\n'
        '    """\n'
        '    return items\n'
    )
    assert scan_all("sample.py", text, {}) == []


def test_self_and_cls_do_not_dilute_identifier_echo():
    for receiver in ("self", "cls"):
        text = f'class A:\n    def scan({receiver}):\n        """Scan."""\n'
        assert "what_docstring" in _rules("sample.py", text, {}), receiver


def test_weak_why_markers_do_not_bypass_a_what_opener():
    lines = (
        "# Returns the row unless the cache is empty",
        "# Returns the row instead of raising",
        "# Returns the row rather than None",
        "# Returns the row and assumes valid input",
        "# Returns the row and requires a key",
        "# Returns the row and must cache or raise",
        "# Returns the row, or None instead of raising",
    )
    for line in lines:
        assert _what_rows("sample.py", line), line


def test_strong_causal_markers_clear_a_what_opener():
    lines = (
        "# Returns the cached row because callers need stable identity",
        "# Returns the cached row so that retries preserve ordering",
        "# Returns the cached row in order to avoid another read",
        "# Returns the cached row due to a remote outage",
        "# Returns the cached row to prevent duplicate work",
    )
    for line in lines:
        assert _what_rows("sample.py", line) == [], line


def test_dunder_scope_is_public_and_budget_docstring_is_exempt():
    dunder = 'class A:\n    def __repr__(self):\n        """Render one diagnostic form."""\n'
    budget = 'def _wait():\n    """5ms budget"""\n'
    assert "what_docstring" not in _rules("sample.py", dunder, {})
    assert "what_docstring" not in _rules("sample.py", budget, {})


def test_what_docstring_survives_family_and_path_switches():
    text = 'def _scan():\n    """Scan."""\n'
    config = {"clean_code": False, "exempt_paths": ["sample.py"]}
    assert "what_docstring" in _rules("sample.py", text, config)


def test_identifier_split_keeps_acronym_before_digits():
    assert scanner._identifier_tokens("SHA256_digest") == {"sha", "256", "digest"}


def test_python_ast_is_parsed_once_and_non_python_is_not_parsed(monkeypatch):
    calls = []
    original = scanner.ast.parse
    monkeypatch.setattr(scanner.ast, "parse", lambda text: calls.append(text) or original(text))
    scan_all("sample.py", 'def _f():\n    """Scan."""\n', {})
    scan_all("sample.js", "const value = 1\n", {})
    assert len(calls) == 1


def test_escalation_is_capped_on_cache_misses(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(escalate, "_remote_verdict", lambda text, model: calls.append(text) or False)
    comments = ["Cache item validator."] * 3
    comments.extend(f"Cache item validator {suffix}." for suffix in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta"))
    text = "\n".join(
        f'def validate_cache_item():\n    """{comment}"""'
        for comment in comments
    )
    config = {"escalation": {"enabled": True}, "state_root": str(tmp_path)}
    scan_all("sample.py", text, config)
    assert calls == [
        "Cache item validator.",
        "Cache item validator alpha.",
        "Cache item validator beta.",
        "Cache item validator gamma.",
        "Cache item validator delta.",
    ]


def _corpus_source(row):
    if "source" in row:
        return row["path"], row["source"]
    if row["kind"] == "comment":
        return "sample.py", "# " + row["text"] + "\n"
    name = row.get("name", "_helper")
    return "sample.py", f'def {name}():\n    """{row["text"]}"""\n'


def test_what_comment_corpus_precision_and_recall_stay_above_floor():
    corpus = Path(__file__).with_name("corpus_what_comments.jsonl")
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]
    predicted = []
    target_rules = {"what_comment", "what_docstring", "prose_semicolon"}
    for index, row in enumerate(rows):
        path, source = _corpus_source(row)
        hit = bool(target_rules & set(_rules(path, source, {})))
        predicted.append((index, row["label"] == "what", hit))
    true_positive = sum(expected and actual for _index, expected, actual in predicted)
    false_positive = sum(not expected and actual for _index, expected, actual in predicted)
    false_negative = sum(expected and not actual for _index, expected, actual in predicted)
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert precision >= 0.9, predicted
    assert recall >= 0.9, predicted


def test_escalation_defaults_off_and_uses_configured_model():
    settings = effective_config({})["escalation"]
    assert settings == {"enabled": False, "model": "claude-haiku-4-5-20251001"}


def test_escalation_failure_preserves_heuristic_verdict(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(escalate, "_remote_verdict", lambda text, model: None)
    config = {"escalation": {"enabled": True}, "state_root": str(tmp_path)}
    assert escalate.classify_what("Validate cached item.", True, config) is True
    assert escalate.classify_what("Validate cached item.", False, config) is False


def test_escalation_caches_success_by_comment_hash(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(escalate, "_remote_verdict", lambda text, model: calls.append(text) or True)
    config = {
        "escalation": {"enabled": True},
        "state_root": str(tmp_path),
        "_escalation_remaining": 1,
    }
    assert escalate.classify_what("Validate cached item.", False, config) is True
    assert escalate.classify_what("Validate cached item.", False, config) is True
    assert calls == ["Validate cached item."]
    assert config["_escalation_remaining"] == 0
    cached = list((tmp_path / "escalation").glob("*.json"))
    assert len(cached) == 1



def test_document_markup_masks_nonprose_regions_but_scans_tex_bodies():
    cfg = {"punctuation": False, "clean_code": False}
    tex = "\\section{in order to}\n% in order to\n$in order to$\n"
    findings = scan_all("paper.tex", tex, cfg)
    assert len([row for row in findings if row["rule"] == "wordiness"]) == 1


def test_document_markup_masks_adoc_org_and_typ_blocks():
    cfg = {"punctuation": False, "clean_code": False}
    cases = {
        "guide.adoc": "----\nin order to\n----\n",
        "notes.org": "#+begin_src python\nin order to\n#+end_src\n",
        "manual.typ": "```\nin order to\n```\n",
    }
    for path, text in cases.items():
        assert "wordiness" not in {row["rule"] for row in scan_all(path, text, cfg)}


def test_extensionless_prose_is_sniffed_but_shebangs_stay_code():
    cfg = {"punctuation": False, "clean_code": False}
    assert "wordiness" in {row["rule"] for row in scan_all("letter", "We write in order to finish.\n", cfg)}
    assert not {row["rule"] for row in scan_all("script", "#!/bin/sh\necho in order to\n", cfg)}
