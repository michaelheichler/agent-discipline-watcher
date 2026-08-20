"""Shell-write scan tests: a heredoc or redirect must face the same rules a Write faces."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
import record
from lib import shell_parse
from testing import make_repo, run_git as git

PROSE = "We leverage a rich tapestry of utilities."
CODE = "# Returns the total value\nvalue = 1\n"
CLEAN_ADDITION = CODE + "other = 2\n"


def _commit(repo, name, body):
    path = repo / name
    path.write_text(body, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "seed")
    return path


def content_rules(command, config=None):
    return sorted(f["rule"] for f in pre_bash.write_findings(command, config))


@pytest.mark.parametrize("command", [
    f"cat > out.md <<EOF\n{PROSE}\nEOF",
    f"cat > out.md <<'EOF'\n{PROSE}\nEOF",
    f'cat > out.md <<"EOF"\n{PROSE}\nEOF',
    f"cat > out.md <<-\tEOF\n\t{PROSE}\n\tEOF",
    f"cat > out.md <<REPORT\n{PROSE}\nREPORT",
    f'echo "{PROSE}" > out.md',
    f"printf '{PROSE}' >> out.md",
    f"tee out.md <<EOF\n{PROSE}\nEOF",
    f"printf '{PROSE}' | tee out.md",
    f"printf '{PROSE}' | tee -a out.md",
])
def test_every_write_form_is_scanned(command):
    assert "inflated_diction" in content_rules(command)


def test_prose_target_gets_prose_rules():
    rules = content_rules(f"echo '{PROSE}' > report.md")
    assert "inflated_diction" in rules and "dead_metaphor" in rules


def test_code_target_gets_code_rules():
    rules = content_rules(f"cat > module.py <<'EOF'\n{CODE}EOF")
    assert "what_comment" in rules
    assert "inflated_diction" not in rules


def test_prose_rules_do_not_reach_a_code_target():
    assert content_rules(f"echo '{PROSE}' > module.py") == []


def test_heredoc_target_and_content_are_paired():
    assert pre_bash.write_targets(f"cat > out.md <<EOF\n{PROSE}\nEOF") == [("out.md", PROSE)]


@pytest.mark.parametrize("command", [
    "echo 'plain clean text' > out.md",
    "cat > out.md <<EOF\nplain clean text\nEOF",
    "printf 'total = 1\\n' > module.py",
])
def test_clean_content_passes(command):
    assert content_rules(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


def test_bash_write_is_blocked_before_execution(tmp_path):
    target = tmp_path / "target.py"
    command = 'echo "# ' + ("TO" + "DO") + r' later\nvalue = 1\n" > target.py'
    pre_response = pre_bash.run(
        {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": command}}
    )
    assert pre_response["decision"] == "block"
    assert "deferred_work_comment" in pre_response["reason"]
    assert not target.exists()


def test_tilde_bash_postwrite_blocks_without_mutation(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    target = Path("~/notes.py").expanduser()
    command = 'echo "# ' + ("TO" + "DO") + r' later\nvalue = 1\n" > ~/notes.py'

    assert pre_bash.write_paths(command) == ["~/notes.py"]
    target.write_text(pre_bash.write_targets(command)[0][1], encoding="utf-8")

    response = record.run(
        {
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": command},
        },
        {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")},
    )

    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]
    assert target.read_text(encoding="utf-8") == pre_bash.write_targets(command)[0][1]


@pytest.mark.parametrize("command", [
    "cat notes.md",
    "grep -rn tapestry docs/",
    "git diff -- notes.md",
    "python3 -m json.tool config.json",
    "wc -l notes.md",
])
def test_read_only_commands_stay_clean(command):
    assert content_rules(command) == []


@pytest.mark.parametrize("command", [
    f"grep '{PROSE}' notes.md 2>/dev/null",
    f"grep '{PROSE}' notes.md 2>>errors.log",
    f"grep '{PROSE}' notes.md 2>&1",
])
def test_stderr_redirection_is_not_a_write(command):
    assert pre_bash.write_targets(command) == []
    assert content_rules(command) == []


@pytest.mark.parametrize("command", [
    "grep tapestry notes.md 22>out.md",
    "grep tapestry notes.md 102>out.md",
])
def test_a_descriptor_merely_ending_in_2_is_a_real_write(command):
    assert pre_bash.write_paths(command) == ["out.md"]


def test_clobber_operator_is_still_a_write_target():
    assert pre_bash.write_targets(f"echo '{PROSE}' >|out.md") == [("out.md", PROSE)]


def test_heredoc_on_a_shared_line_does_not_leak_into_an_unrelated_write():
    command = f"cat <<EOF > clean.txt; echo '{PROSE}' > out.md\nclean\nEOF"
    assert pre_bash.write_targets(command) == [("clean.txt", "clean"), ("out.md", PROSE)]


def test_pipe_fed_content_still_pairs_across_segments():
    assert pre_bash.write_targets(f"printf '{PROSE}' | tee out.md") == [("out.md", PROSE)]


def test_hyphenated_heredoc_delimiter_still_scans():
    command = f"cat > out.md <<END-OF\n{PROSE}\nEND-OF"
    assert pre_bash.write_targets(command) == [("out.md", PROSE)]


def test_pipe_with_stderr_operator_is_still_a_write():
    assert pre_bash.write_targets(f"printf '{PROSE}' |& tee out.md") == [("out.md", PROSE)]


@pytest.mark.parametrize("command", [
    "curl https://example.invalid/report | tee out.md",
    "generate-report | cat > out.md",
    'echo "$REPORT_BODY" > out.md',
    "echo $(build-report) > out.md",
])
def test_undeterminable_content_is_allowed_silently(command):
    assert pre_bash.write_targets(command) == []
    assert content_rules(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


def test_a_stream_transform_between_two_files_is_a_documented_residual_gap():
    command = "sed 's/x/y/' in > out"
    assert pre_bash.write_targets(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


def test_xargs_feeding_tee_is_a_documented_residual_gap():
    command = "xargs tee out.md"
    assert pre_bash.write_targets(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


def test_a_module_run_is_a_documented_residual_gap():
    command = "python3 -m json.tool file.json"
    assert pre_bash.write_targets(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


@pytest.mark.parametrize("command", [
    "cat > out.md <<EOF\n$REPORT_BODY\nEOF",
    "cat > out.md <<EOF\nunterminated body with no closing word",
])
def test_a_dynamic_or_unterminated_heredoc_aimed_at_a_file_blocks(command):
    result = pre_bash.run({"tool_input": {"command": command}})
    assert result["decision"] == "block"
    assert "dynamic_heredoc_write" in result["reason"]


def test_single_quoted_dollar_stays_literal():
    assert pre_bash.write_targets("echo '$5 budget' > out.md") == [("out.md", "$5 budget")]


def test_self_protection_still_blocks_and_takes_precedence():
    command = f"git commit --no-verify -m x && echo '{PROSE}' > out.md"
    result = pre_bash.run({"tool_input": {"command": command}})
    assert result["decision"] == "block"
    assert "commit_gate_bypass" in result["reason"]
    assert "inflated_diction" not in result["reason"]


def test_content_finding_blocks_through_the_hook_contract():
    result = pre_bash.run({"tool_input": {"command": f"echo '{PROSE}' > out.md"}})
    assert result["decision"] == "block"
    assert "inflated_diction" in result["reason"]


def test_observed_family_reports_without_blocking():
    config = {"gates": {"english": "observe", "punctuation": "observe"}}
    result = pre_bash.run({"tool_input": {"command": f"echo '{PROSE}' > out.md"}}, config)
    assert "decision" not in result
    assert "inflated_diction" in result["systemMessage"]


def test_disabled_family_releases_the_write():
    config = {"gates": {"english": "off", "punctuation": "off", "clean_code": "off"}}
    assert pre_bash.run({"tool_input": {"command": f"echo '{PROSE}' > out.md"}}, config) == {}


def test_exempt_path_drops_the_content_scan():
    config = {"exempt_paths": ["out.md"]}
    assert content_rules(f"echo '{PROSE}' > out.md", config) == []


def test_css_hash_id_selector_written_through_bash_is_not_a_deferred_work_marker():
    marker = "to" + "do"
    command = f"cat > style.css <<'EOF'\n#{marker} {{ color: #fff; }}\nEOF"
    assert content_rules(command) == []


def test_markdown_url_written_through_bash_keeps_its_semicolon_unflagged():
    command = "cat > out.md <<'EOF'\nhttps://example.com/a" + chr(59) + "b\nEOF"
    assert content_rules(command) == []


def test_markdown_table_written_through_bash_keeps_its_separator_row_unflagged():
    command = (
        "cat > out.md <<'EOF'\n"
        "| Name | Code |\n"
        "| --- | --- |\n"
        "| value | clean |\n"
        "EOF"
    )
    assert content_rules(command) == []


def test_python_string_written_through_bash_masks_a_hash_marker_inside_it():
    marker = "to" + "do"
    command = f"cat > out.py <<'EOF'\nvalue = \"# {marker} fix this\"\nEOF"
    assert content_rules(command) == []


def test_oversized_heredoc_is_skipped():
    body = "leverage " * 5000
    config = {"max_scan_bytes": 100}
    assert content_rules(f"cat > out.md <<'EOF'\n{body}\nEOF", config) == []


def test_dev_null_is_not_a_write_target():
    assert pre_bash.write_targets(f"echo '{PROSE}' > /dev/null") == []


def test_two_writes_on_one_line_pair_positionally():
    command = f"echo '{PROSE}' > a.md && echo clean > b.md"
    assert pre_bash.write_targets(command) == [("a.md", PROSE), ("b.md", "clean")]


@pytest.mark.parametrize("command, append", [
    ("echo 'x' > out.md", False),
    ("echo 'x' >> out.md", True),
    ("echo 'x' >|out.md", False),
])
def test_literal_writes_distinguishes_overwrite_from_append(command, append):
    assert shell_parse.literal_writes(command) == [shell_parse.LiteralWrite("out.md", "x", append)]


@pytest.mark.parametrize("command, append", [
    ("printf 'x' | tee out.md", False),
    ("printf 'x' | tee -a out.md", True),
    ("printf 'x' | tee --append out.md", True),
    ("printf 'x' | tee '-a' out.md", True),
])
def test_literal_writes_distinguishes_tee_from_tee_append(command, append):
    assert shell_parse.literal_writes(command) == [shell_parse.LiteralWrite("out.md", "x", append)]


def test_write_targets_stays_a_thin_projection_of_literal_writes():
    command = f"cat > out.md <<EOF\n{PROSE}\nEOF"
    assert pre_bash.write_targets(command) == [("out.md", PROSE)]


@pytest.mark.parametrize("command, interpreter, flag", [
    ("python3 -c 'print(1)'", "python3", "-c"),
    ("node -e 'console.log(1)'", "node", "-e"),
    ("env python3 -c 'print(1)'", "python3", "-c"),
    ("sudo python3 -c 'print(1)'", "python3", "-c"),
    ("env -i python3 -c 'print(1)'", "python3", "-c"),
    ("sudo -u root python3 -c 'print(1)'", "python3", "-c"),
    ("command -p python3 -c 'print(1)'", "python3", "-c"),
    ("time -p python3 -c 'print(1)'", "python3", "-c"),
    ("'sudo' python3 -c 'print(1)'", "python3", "-c"),
    ("'python3' -c 'print(1)'", "python3", "-c"),
    ('"python3" -c \'print(1)\'', "python3", "-c"),
    ("env 'python3' -c 'x'", "python3", "-c"),
    ("bash -lc 'echo 1'", "bash", "-c"),
    ("python3 -uc 'print(1)'", "python3", "-c"),
    ("perl -we 'print 1'", "perl", "-e"),
    ("perl -E 'print 1'", "perl", "-E"),
    ("node --eval '1'", "node", "--eval"),
    ("node -pe '1'", "node", "-e"),
    ("python3.12 -c 'print(1)'", "python3.12", "-c"),
    ("/usr/bin/python3.11 -c 'print(1)'", "python3.11", "-c"),
    ("env -S 'python3 -c \"print(1)\"'", "python3", "-c"),
    ("env --split-string 'python3 -c \"print(1)\"'", "python3", "-c"),
    ("env -S python3 -c 'print(1)'", "python3", "-c"),
    ("env --split-string=python3 -c 'print(1)'", "python3", "-c"),
    ("env -S'python3 -c \"print(1)\"'", "python3", "-c"),
    ('''env -S"python3 -c 'print(1)'"''', "python3", "-c"),
    ("env --split-string='python3 -c \"print(1)\"'", "python3", "-c"),
    ('''env --split-string="python3 -c 'print(1)'"''', "python3", "-c"),
    ("env -S='python3 -c \"print(1)\"'", "python3", "-c"),
])
def test_interpreter_invocation_reads_literal_payload(command, interpreter, flag):
    segment = shell_parse._segments(command)[0]
    invocation = shell_parse.interpreter_invocation(segment)
    assert invocation.interpreter == interpreter
    assert invocation.flag == flag
    assert invocation.payload is not None


def test_interpreter_invocation_returns_none_payload_for_a_dynamic_code_argument():
    segment = shell_parse._segments('python3 -c "$CODE"')[0]
    invocation = shell_parse.interpreter_invocation(segment)
    assert invocation.interpreter == "python3"
    assert invocation.payload is None


def test_interpreter_invocation_returns_a_token_for_a_literal_code_argument():
    segment = shell_parse._segments("python3 -c 'print(1)'")[0]
    assert shell_parse.interpreter_invocation(segment).payload == "print(1)"


def test_interpreter_invocation_reads_a_quoted_flag_token():
    segment = shell_parse._segments("python3 '-c' 'print(1)'")[0]
    invocation = shell_parse.interpreter_invocation(segment)
    assert invocation.interpreter == "python3"
    assert invocation.flag == "-c"
    assert invocation.payload == "print(1)"


def test_interpreter_invocation_reads_a_flag_attached_to_its_payload():
    segment = shell_parse._segments("python3 -c'print(1)'")[0]
    invocation = shell_parse.interpreter_invocation(segment)
    assert invocation.interpreter == "python3"
    assert invocation.flag == "-c"
    assert invocation.payload == "print(1)"


@pytest.mark.parametrize("command", [
    "grep 'python -c' docs/",
    "ls -la",
    "python3 script.py",
])
def test_interpreter_invocation_does_not_match_quoted_or_absent_flags(command):
    segment = shell_parse._segments(command)[0]
    assert shell_parse.interpreter_invocation(segment) is None


def test_heredoc_events_reports_body_and_write_target_for_a_clean_heredoc():
    command = f"cat > out.md <<EOF\n{PROSE}\nEOF"
    events = shell_parse.heredoc_events(command)
    assert len(events) == 1
    assert events[0].body == PROSE
    assert events[0].dynamic is False
    assert events[0].group_has_write_target is True
    assert events[0].consumer_segment[0] == "cat"


def test_heredoc_events_reports_dynamic_heredoc():
    command = "cat > out.md <<EOF\n$REPORT_BODY\nEOF"
    events = shell_parse.heredoc_events(command)
    assert len(events) == 1
    assert events[0].dynamic is True
    assert events[0].group_has_write_target is True


def test_heredoc_events_reports_unterminated_heredoc_as_dynamic():
    command = "cat > out.md <<EOF\nunterminated body with no closing word"
    events = shell_parse.heredoc_events(command)
    assert len(events) == 1
    assert events[0].dynamic is True


def test_heredoc_events_reports_no_write_target_for_a_streaming_consumer():
    command = "cat <<EOF | psql\nselect 1;\nEOF"
    events = shell_parse.heredoc_events(command)
    assert len(events) == 1
    assert events[0].group_has_write_target is False


@pytest.mark.parametrize("segment, expected", [
    ("diff <(cmd1) <(cmd2)", True),
    ("tee >(cmd)", True),
    ('echo "literal <(not real)"', False),
    ("cat > out.md", False),
])
def test_has_process_substitution(segment, expected):
    assert shell_parse.has_process_substitution(segment) is expected


def test_bash_append_with_a_clean_body_is_allowed(tmp_path):
    command = "echo 'plain clean text' >> notes.md"
    assert pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)}) == {}


def test_bash_append_with_an_offending_body_blocks_and_labels_it_as_appended_text(tmp_path):
    command = f"echo '{PROSE}' >> notes.md"
    findings = pre_bash.write_findings(command, cwd=tmp_path)
    assert any(f["rule"] == "inflated_diction" and "of appended text" in f["detail"] for f in findings)
    result = pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)})
    assert result["decision"] == "block"
    assert "inflated_diction" in result["reason"]


def test_bash_overwrite_of_a_committed_file_with_inherited_debt_reports_without_blocking(tmp_path):
    repo = make_repo(tmp_path)
    _commit(repo, "module.py", CODE)
    command = f"cat > module.py <<'EOF'\n{CLEAN_ADDITION}EOF"
    result = pre_bash.run({"tool_input": {"command": command}, "cwd": str(repo)})
    assert "decision" not in result
    assert "already carried" in result["systemMessage"]
    assert "what_comment" in result["systemMessage"]


def test_bash_overwrite_still_blocks_on_debt_the_command_itself_introduced(tmp_path):
    repo = make_repo(tmp_path)
    _commit(repo, "module.py", CODE)
    offending = CODE + "# Sets the second value\nother = 2\n"
    command = f"cat > module.py <<'EOF'\n{offending}EOF"
    findings = pre_bash.write_findings(command, cwd=repo)
    assert any(f["rule"] == "what_comment" and "Sets the second value" in f["snippet"] for f in findings)
    result = pre_bash.run({"tool_input": {"command": command}, "cwd": str(repo)})
    assert result["decision"] == "block"
    assert "what_comment" in result["reason"]


def test_bash_append_growing_a_file_past_the_length_limit_blocks(tmp_path):
    target = tmp_path / "big.py"
    target.write_text("x = 1\n" * 999, encoding="utf-8")
    body = "\n".join(f"y{i} = {i}" for i in range(5))
    command = f"cat >> big.py <<'EOF'\n{body}\nEOF"
    result = pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)})
    assert result["decision"] == "block"
    assert "file_too_long" in result["reason"]


def test_bash_append_under_the_length_limit_stays_clean(tmp_path):
    target = tmp_path / "small.py"
    target.write_text("x = 1\n" * 10, encoding="utf-8")
    command = "echo 'y = 2' >> small.py"
    assert pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)}) == {}


def test_bash_append_to_a_long_prose_file_is_not_a_length_violation(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("one ordinary line\n" * 1200, encoding="utf-8")
    command = "echo 'one more plain line of ordinary text' >> notes.md"
    assert pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)}) == {}


def test_bash_append_of_clean_lines_to_an_already_too_long_file_does_not_own_the_debt(tmp_path):
    target = tmp_path / "big.py"
    target.write_text("x = 1\n" * 1200, encoding="utf-8")
    command = "echo 'y = 2' >> big.py"
    assert pre_bash.run({"tool_input": {"command": command}, "cwd": str(tmp_path)}) == {}
