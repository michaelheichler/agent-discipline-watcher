import json
from pathlib import Path

from lib import comment_rules, prose_structure, scanner
from lib.markup import mask_python_strings
from lib.config import ALWAYS_BLOCKING_RULES, effective_config
from lib.scanner import scan_all


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
    assert list(prose_structure._markdown_prose_lines("Heading | Detail\n--- | ---"))[-1] == (2, "")


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
    def rules(count: int) -> set[str]:
        source = "\n".join("x = 1" for _ in range(count))
        return {row["rule"] for row in scan_all("sample.py", source, {})}

    assert not rules(499) & {"file_length_warning", "file_length_critical", "file_too_long"}
    assert "file_length_warning" in rules(500)
    assert "file_length_warning" in rules(749)
    assert "file_length_critical" in rules(750)
    assert "file_length_critical" in rules(999)
    assert "file_too_long" in rules(1000)


def test_file_length_guard_ignores_release_controls():
    config = {
        "clean_code": False,
        "gates": {"clean_code": "off"},
        "kill_switches": {"clean_code": True},
        "exempt_paths": ["sample.py"],
        "rule_gates": {"file_too_long": "off", "file_length_warning": "off"},
    }
    warning = scan_all("sample.py", "\n".join("x = 1" for _ in range(500)), config)
    blocked = scan_all("sample.py", "\n".join("x = 1" for _ in range(1000)), config)
    assert "file_length_warning" in {row["rule"] for row in warning}
    assert "file_too_long" in {row["rule"] for row in blocked}


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


def test_unterminated_string_masking_blanks_from_the_failure_point_onward():
    marker = "TO" + "DO"
    text = 'text = """unterminated\n# ' + marker + ' fix\n'
    rules = {item["rule"] for item in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert not rules & {"what_comment", "deferred_work_comment"}


def test_mask_python_strings_still_blanks_well_formed_strings():
    assert "value" not in mask_python_strings('x = "value"\n')


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


def test_exempt_paths_cannot_skip_strict_comment_rules():
    text = (
        "# first narrating line of prose\n"
        "# second narrating line of prose\n"
        "x = 1\n"
    )
    cfg = {"exempt_paths": ["scripts/legacy_contract_test.py"]}
    rules = {row["rule"] for row in scanner.scan_all("/repo/scripts/legacy_contract_test.py", text, cfg)}
    assert {"what_comment", "prose_comment_block"} <= rules
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


def test_strict_why_marker_gate():
    for line in (
        "# increments the counter",
        "# resets the counter",
        "# returns the total",
    ):
        assert len(_what_rows("sample.py", line)) == 1, line
    for line in (
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
        assert not scanner._code_file(path, "")


def test_shell_dotfiles_are_still_scanned_as_code():
    for path in (".bashrc", ".zshrc", ".profile", ".envrc", ".bash_profile"):
        assert scanner._code_file(path, "")
        rules = [row["rule"] for row in scan_all(path, "# sets the path\nexport A=1\n", {})]
        assert "what_comment" in rules


def test_dotfile_with_a_real_extension_stays_code():
    assert scanner._code_file(".hidden.py", "")


def test_file_length_findings_agrees_with_scan_all_for_mixed_language_files():
    text = "\n".join("<div></div>" for _ in range(800))
    assert "file_length_critical" in {row["rule"] for row in scan_all("page.html", text, {})}
    assert "file_length_critical" in {row["rule"] for row in scanner.file_length_findings("page.html", text)}


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
    marker = "craftsman" + "-ignore: PY002"
    cfg = {"exempt_families": {"a.py": ["clean_code", "punctuation", "english"]}}
    assert "suppression_escape_hatch" in _rules("a.py", "# " + marker + "\n", cfg)


def test_exempt_families_cannot_silence_what_comment():
    cfg = {"exempt_families": {"a.py": ["clean_code"]}}
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


def test_public_first_line_summary_without_why_is_blocked():
    text = 'def fetch_record():\n    """Load one stable row from storage."""\n'
    assert "what_docstring" in _rules("sample.py", text, {})


def test_only_one_line_why_docstrings_are_allowed():
    private = 'def _fetch():\n    """Keep the local copy because callers rely on object identity."""\n'
    public = (
        'def fetch_record():\n'
        '    """Load one stable row from storage.\n'
        '    Keep the local copy because callers rely on object identity.\n'
        '    """\n'
    )
    assert "what_docstring" not in _rules("sample.py", private, {})
    assert "docstring_narration" in _rules("sample.py", public, {})


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
        assert comment_rules.WHAT_OPENER_RE.match(text), text
    assert not comment_rules.WHAT_OPENER_RE.match("A stable storage row")


def test_middle_band_docstring_without_why_is_blocked():
    text = 'def validate_cache_item():\n    """Cache item validator."""\n'
    assert "what_docstring" in _rules("sample.py", text, {})


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
    url = "https://example.com/a" + mark + "b\n"
    for text in (fenced, url):
        assert "prose_semicolon" not in _rules("README.md", text, {}), text

    table = "| Name | Code |\n| --- | --- |\n| value | x = 1" + mark + " |\n"
    assert "prose_semicolon" in _rules("README.md", table, {})

    inline_code = "| code | `left" + mark + "right` |\n"
    assert "prose_semicolon" not in _rules("README.md", inline_code, {})

    findings_table = (
        "| Metric | Notes |\n"
        "| --- | --- |\n"
        "| Latency | Improved this quarter" + mark + " still above SLO |\n"
    )
    assert "prose_semicolon" in _rules("README.md", findings_table, {})

    dash_table = (
        "| Metric | Notes |\n"
        "| --- | --- |\n"
        "| Latency | word" + "-" * 2 + "word break |\n"
    )
    assert "dash_break" in _rules("README.md", dash_table, {})

    prose = "The pipe | stays visible" + mark + " rewrite this clause.\n"
    assert "prose_semicolon" in _rules("README.md", prose, {})


def test_table_separator_rows_are_hidden_without_hiding_cell_content():
    cases = (
        "| --- | --- |\n",
        "|:---|---:|\n",
        "|---|\n",
    )
    for text in cases:
        assert scanner._is_table_separator_row(text)
    for text in ("", "|", "| Name |", "| - note |"):
        assert not scanner._is_table_separator_row(text)


def test_google_style_multiline_docstring_is_blocked():
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
    rules = {row["rule"] for row in scan_all("sample.py", text, {})}
    assert "docstring_narration" in rules


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
        rules = _rules("sample.py", line + "\n", {})
        assert "weak_why_comment" in rules or "what_comment" in rules, line


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


def test_dunder_and_budget_docstrings_without_why_are_blocked():
    dunder = 'class A:\n    def __repr__(self):\n        """Render one diagnostic form."""\n'
    budget = 'def _wait():\n    """5ms budget"""\n'
    assert "what_docstring" in _rules("sample.py", dunder, {})
    assert "what_docstring" in _rules("sample.py", budget, {})


def test_what_docstring_ignores_family_and_path_switches():
    text = 'def _scan():\n    """Scan."""\n'
    config = {"clean_code": False, "exempt_paths": ["sample.py"]}
    assert "what_docstring" in _rules("sample.py", text, config)


def test_identifier_split_keeps_acronym_before_digits():
    assert comment_rules._identifier_tokens("SHA256_digest") == {"sha", "256", "digest"}


def test_python_ast_is_parsed_once_and_non_python_is_not_parsed(monkeypatch):
    calls = []
    original = scanner.ast.parse
    monkeypatch.setattr(scanner.ast, "parse", lambda text: calls.append(text) or original(text))
    scan_all("sample.py", 'def _f():\n    """Scan."""\n', {})
    scan_all("sample.js", "const value = 1\n", {})
    assert len(calls) == 1


def _corpus_source(row):
    if "source" in row:
        return row["path"], row["source"]
    if row["kind"] == "comment":
        return "sample.py", "# " + row["text"] + "\n"
    name = row.get("name", "_helper")
    return "sample.py", f'def {name}():\n    """{row["text"]}"""\n'


def test_what_comment_corpus_keeps_recall_for_what_examples():
    corpus = Path(__file__).with_name("corpus_what_comments.jsonl")
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]
    predicted = []
    target_rules = {"what_comment", "what_docstring", "prose_semicolon"}
    for index, row in enumerate(rows):
        path, source = _corpus_source(row)
        hit = bool(target_rules & set(_rules(path, source, {})))
        predicted.append((index, row["label"] == "what", hit))
    true_positive = sum(expected and actual for _index, expected, actual in predicted)
    false_negative = sum(expected and not actual for _index, expected, actual in predicted)
    recall = true_positive / (true_positive + false_negative)
    assert recall >= 0.9, predicted


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


def test_weak_why_comment_fires_for_a_weak_marker_only():
    rows = scan_all("sample.py", "# skip unless the lock is held\nx = 1\n", {})
    rules = {row["rule"] for row in rows}
    assert "weak_why_comment" in rules
    assert "what_comment" not in rules


def test_weak_why_comment_spares_a_strong_marker_comment():
    rows = scan_all("sample.py", "# skip because the lock is held\nx = 1\n", {})
    assert "weak_why_comment" not in {row["rule"] for row in rows}


def test_weak_why_comment_is_an_unconditional_blocker():
    assert "weak_why_comment" in ALWAYS_BLOCKING_RULES
    assert effective_config({})["rule_gates"].get("weak_why_comment") is None


def test_why_line_does_not_protect_a_multiline_docstring():
    text = "\n".join([
        '"""module summary',
        'second line because callers rely on this exact ordering"""',
        "x = 1",
    ])
    rules = {row["rule"] for row in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "docstring_narration" in rules


def test_why_line_does_not_protect_a_comment_block():
    text = "# first line\n# second line because docs live in the wiki\nprint(1)\n"
    rules = {row["rule"] for row in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "prose_comment_block" in rules


def test_shell_glob_slash_star_does_not_swallow_the_rest_of_the_script():
    text = (
        'if [[ "$value" == */* ]]; then\n'
        '  echo yes\n'
        'fi\n'
        'case "$path" in\n'
        '  "$root"/*) echo match ;;\n'
        'esac\n'
    )
    assert scan_all("patch-chain.sh", text, {"punctuation": False, "english": False}) == []


def test_shell_narrating_hash_comment_block_still_flags():
    text = "# first line\n# second line because docs live in the wiki\necho 1\n"
    rules = {row["rule"] for row in scan_all("patch-chain.sh", text, {"punctuation": False, "english": False})}
    assert "prose_comment_block" in rules


def test_c_style_block_comment_still_flags_outside_shell_files():
    text = "/* first line\n   second line */\nprint(1)\n"
    rules = {row["rule"] for row in scan_all("sample.py", text, {"punctuation": False, "english": False})}
    assert "prose_comment_block" in rules
