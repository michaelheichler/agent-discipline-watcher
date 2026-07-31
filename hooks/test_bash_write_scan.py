"""Shell-write scan tests: a heredoc or redirect must face the same rules a Write faces."""
from __future__ import annotations

import pytest

import pre_bash

PROSE = "We leverage a rich tapestry of utilities."
CODE = "# this function returns the total\nvalue = 1\n"


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
    "curl https://example.invalid/report | tee out.md",
    "generate-report | cat > out.md",
    'echo "$REPORT_BODY" > out.md',
    "echo $(build-report) > out.md",
    "cat > out.md <<EOF\n$REPORT_BODY\nEOF",
    "cat > out.md <<EOF\nunterminated body with no closing word",
])
def test_undeterminable_content_is_allowed_silently(command):
    assert pre_bash.write_targets(command) == []
    assert content_rules(command) == []
    assert pre_bash.run({"tool_input": {"command": command}}) == {}


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


def test_oversized_heredoc_is_skipped():
    body = "leverage " * 5000
    config = {"max_scan_bytes": 100}
    assert content_rules(f"cat > out.md <<'EOF'\n{body}\nEOF", config) == []


def test_dev_null_is_not_a_write_target():
    assert pre_bash.write_targets(f"echo '{PROSE}' > /dev/null") == []


def test_two_writes_on_one_line_pair_positionally():
    command = f"echo '{PROSE}' > a.md && echo clean > b.md"
    assert pre_bash.write_targets(command) == [("a.md", PROSE), ("b.md", "clean")]
