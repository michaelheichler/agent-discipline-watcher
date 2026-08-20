"""Because a write the scanner cannot see is a write it cannot judge, every opaque Bash route proven here must hard block. The residual gaps left for the next hardening pass, pinned as allowed in test_bash_write_scan.py, are echo of an expanded variable, curl piped into tee, a stream transform between two files, a module run, and xargs feeding tee."""
from __future__ import annotations

import pytest

import pre_bash

RULES = (
    "inline_interpreter_write",
    "shell_payload_block",
    "interpreter_heredoc_write",
    "dynamic_heredoc_write",
    "decode_pipe_write",
    "inplace_edit_write",
    "opaque_source_write",
)


def blocked(command, config=None):
    result = pre_bash.run({"tool_input": {"command": command}}, config)
    assert result.get("decision") == "block", result
    return result["reason"]


def allowed(command, config=None):
    return pre_bash.run({"tool_input": {"command": command}}, config)


@pytest.mark.parametrize("command", [
    """python3 -c 'open("x.txt", "w").write("y")'""",
    'python3 -c "$CODE"',
    """node -e 'require("fs").writeFileSync("a.txt","body")'""",
    """php -r 'file_put_contents("a.txt","body");'""",
    """env -i python3 -c 'open("x.txt", "w").write("y")'""",
    """sudo -u root python3 -c 'open("x.txt", "w").write("y")'""",
    """command -p python3 -c 'open("x.txt", "w").write("y")'""",
    """time -p python3 -c 'open("x.txt", "w").write("y")'""",
    """'sudo' python3 -c 'open("x.txt", "w").write("y")'""",
    """python3 -uc 'open("x.txt", "w").write("y")'""",
    """perl -we 'open(F, ">x")'""",
    """perl -E 'open(F, ">x")'""",
    """node --eval 'require("fs").writeFileSync("a.txt","body")'""",
    """node -pe 'require("fs").writeFileSync("a.txt","body")'""",
    """python3.12 -c 'open("x.txt", "w").write("y")'""",
    """/usr/bin/python3.11 -c 'open("x.txt", "w").write("y")'""",
    """env -S 'python3 -c "import os"'""",
    """env --split-string 'python3 -c "import os"'""",
    """env -S python3 -c 'open("x.txt", "w").write("y")'""",
    """env --split-string=python3 -c 'open("x.txt", "w").write("y")'""",
    """env -iS 'python3 -c "import os"'""",
    """env -S'python3 -c "import os"'""",
    '''env -S"python3 -c 'import os'"''',
    """env --split-string='python3 -c "import os"'""",
    '''env --split-string="python3 -c 'import os'"''',
    """env -S='python3 -c "import os"'""",
    """python3 -c 'from pathlib import Path; Path("x.txt").write_text("y")'""",
    """python3 -c 'from pathlib import Path; Path("x.txt").write_bytes(b"y")'""",
    """python3 -c 'from os import remove; remove("x.txt")'""",
    """python3 -c 'from shutil import rmtree; rmtree("x")'""",
    """python3 -c 'from io import FileIO; FileIO("x.txt","w")'""",
    """> out.log python3 -c 'open("x.txt", "w").write("y")'""",
    """< in.txt python3 -c 'open("x.txt", "w").write("y")'""",
])
def test_inline_interpreter_write_blocks(command):
    reason = blocked(command)
    assert "inline_interpreter_write" in reason
    assert "Write or Edit" in reason


@pytest.mark.parametrize("command", [
    'sh -c "$CMD"',
    'sh -c \'sh -c "ls -la"\'',
])
def test_shell_payload_block_blocks(command):
    reason = blocked(command)
    assert "shell_payload_block" in reason
    assert "Write or Edit" in reason


# Pin this case because a write token in the first fragment must block even if the fragment join regresses.
def test_adjacent_quoted_fragments_in_a_python_payload_still_block():
    reason = blocked("""python3 -c 'open("x'"t.txt"'","w").write("y")'""")
    assert "inline_interpreter_write" in reason


# Pin the exact probe because only the joined word carries the write token, so this test holds the fragment join.
def test_a_write_call_split_across_the_operand_boundary_still_blocks():
    reason = blocked("""python3 -c 'a=1'"; open('t.txt','w').write('y')\"""")
    assert "inline_interpreter_write" in reason


def test_a_literal_shell_payload_reenters_the_full_gate():
    reason = blocked("sh -c 'rm -rf ~/.agent-discipline'")
    assert "state_deletion" in reason


def test_a_clean_literal_shell_payload_stays_allowed():
    assert allowed("sh -c 'ls -la'") == {}


def test_a_literal_shell_payload_content_is_scanned():
    bare = "echo 'We leverage a rich tapestry of utilities.' > out.md"
    reason = blocked(f'sh -c "{bare}"')
    assert "dead_metaphor" in reason
    assert "inflated_diction" in reason


def test_a_literal_shell_payload_with_an_outer_redirect_is_scanned():
    reason = blocked("""sh -c "echo 'We leverage a rich tapestry of utilities.'" > out.md""")
    assert "dead_metaphor" in reason
    assert "inflated_diction" in reason


def test_a_literal_shell_payload_with_an_outer_redirect_and_unreadable_content_stays_allowed():
    assert allowed("sh -c 'cat somefile' > out.md") == {}


def test_a_fused_shell_c_flag_still_reenters_the_full_gate():
    bare = "echo 'We leverage a rich tapestry of utilities.' > out.md"
    reason = blocked(f'bash -lc "{bare}"')
    assert "dead_metaphor" in reason
    assert "inflated_diction" in reason


def test_a_literal_shell_payload_oversize_write_blocks():
    bare = f"echo '{'x' * 200}' > out.md"
    reason = blocked(f'sh -c "{bare}"')
    assert "exceeds the 100-character cap" in reason


@pytest.mark.parametrize("command", [
    "python3 <<EOF\nimport os\nos.remove('x')\nEOF",
    'python3 <<EOF\n$CODE\nEOF',
    "cat notes.py | python3",
    "python3.12 <<EOF\nimport os\nos.remove('x')\nEOF",
    "sudo -u root python3 <<EOF\nimport os\nos.remove('x')\nEOF",
])
def test_interpreter_heredoc_write_blocks(command):
    reason = blocked(command)
    assert "interpreter_heredoc_write" in reason
    assert "Write or Edit" in reason


def test_a_heredoc_into_a_shell_consumer_reenters_the_full_gate():
    bare = "echo 'We leverage a rich tapestry of utilities.' > out.md"
    reason = blocked(f"sh <<'EOF'\n{bare}\nEOF")
    assert "dead_metaphor" in reason
    assert "inflated_diction" in reason


def test_a_heredoc_into_a_shell_consumer_catches_an_inplace_edit():
    reason = blocked("bash <<'EOF'\nsed -i '' 's/a/b/' f.txt\nEOF")
    assert "inplace_edit_write" in reason


def test_a_dynamic_heredoc_into_a_shell_consumer_still_blocks():
    reason = blocked("sh <<EOF\n$CMD\nEOF")
    assert "interpreter_heredoc_write" in reason
    assert "Write or Edit" in reason


def test_a_pipe_into_a_shell_consumer_reenters_the_full_gate():
    bare = "echo 'We leverage a rich tapestry of utilities.' > out.md"
    reason = blocked(f'echo "{bare}" | sh')
    assert "dead_metaphor" in reason
    assert "inflated_diction" in reason


def test_a_pipe_into_a_shell_consumer_catches_state_deletion():
    reason = blocked('echo "rm -rf ~/.agent-discipline" | sh')
    assert "state_deletion" in reason


def test_a_mid_pipeline_interpreter_with_write_capable_producer_text_blocks():
    reason = blocked('echo "import os" | python3 | cat')
    assert "interpreter_heredoc_write" in reason


def test_a_mid_pipeline_shell_stage_reenters_the_full_gate():
    reason = blocked('echo "rm -rf ~/.agent-discipline" | sh | cat')
    assert "state_deletion" in reason


def test_a_mid_pipeline_with_no_interpreter_stage_stays_allowed():
    assert allowed("cat file | grep x | head") == {}


def test_a_clean_literal_heredoc_into_a_shell_consumer_stays_allowed():
    assert allowed("bash <<'EOF'\nls -la\nEOF") == {}


def test_a_nested_heredoc_write_inside_a_shell_consumer_heredoc_is_scanned():
    bare = "We leverage a rich tapestry of utilities."
    command = f"bash <<EOF\ncat > out.md <<'IN'\n{bare}\nIN\nEOF"
    reason = blocked(command)
    assert "dead_metaphor" in reason


@pytest.mark.parametrize("command", [
    "cat > out.md <<EOF\n$REPORT_BODY\nEOF",
    "cat > out.md <<EOF\nunterminated body with no closing word",
])
def test_dynamic_heredoc_write_blocks(command):
    reason = blocked(command)
    assert "dynamic_heredoc_write" in reason
    assert "Write or Edit" in reason


@pytest.mark.parametrize("command", [
    "base64 -d blob.txt > out.bin",
    "base64 --decode blob.txt | tee out.bin",
    "base64 -d -o out.bin blob.txt",
    "uudecode file.uu",
    "openssl enc -d -out out.bin",
    "openssl base64 -d -out out.bin",
    "xxd -r blob.txt > out.bin",
    "xxd -r | tee out.bin",
    "env -S 'base64 -d blob.txt > out.bin'",
    "env -S 'base64 -d blob.txt | tee out.bin'",
    "env -S'base64 -d blob.txt > out.bin'",
    "env --split-string='base64 -d blob.txt > out.bin'",
])
def test_decode_pipe_write_blocks(command):
    reason = blocked(command)
    assert "decode_pipe_write" in reason
    assert "Write or Edit" in reason


@pytest.mark.parametrize("command", [
    "sed -i '' 's/a/b/' file.txt",
    "sed -i.bak 's/a/b/' file.txt",
    "perl -pi -e 's/a/b/' file.txt",
    "sed -Ei 's/a/b/' file.txt",
    "sed -Ei.bak 's/a/b/' file.txt",
    "sed -nEi 's/a/b/' f.txt",
    "sed -ri 's/a/b/' f.txt",
    "sed -i -E 's/a/b/' f.txt",
    "awk -i inplace '{gsub(/a/,\"b\")}1' f.txt",
    "gawk -i inplace '{gsub(/a/,\"b\")}1' f.txt",
    "gawk --inplace '{gsub(/a/,\"b\")}1' f.txt",
    "gawk -iinplace '{gsub(/a/,\"b\")}1' f.txt",
    "sudo -u root sed -i '' 's/a/b/' file.txt",
    "'sudo' sed -i '' 's/a/b/' file.txt",
    "env -S 'sed -i s/a/b/ file.txt'",
])
def test_inplace_edit_write_blocks(command):
    reason = blocked(command)
    assert "inplace_edit_write" in reason
    assert "Write or Edit" in reason


@pytest.mark.parametrize("command", [
    "perl -Ilib script.pl",
    "ruby -Ilib -e 'puts 1'",
    "sed -E 's/a/b/' file.txt",
    "sed -nE 's/a/b/' file.txt",
    "sed -fi edits.sed file.txt",
    "sed -f edits.sed file.txt",
    "awk '{print $1}' f.txt",
    "gawk -i somelib '{print $1}' f.txt",
    "gawk --include somelib '{print $1}' f.txt",
])
def test_include_path_flag_is_not_an_inplace_flag(command):
    assert allowed(command) == {}


@pytest.mark.parametrize("command", [
    "dd if=/dev/zero of=out.bin",
    "cat <(cmd) > out.bin",
    "env -i dd if=/dev/zero of=out.bin",
])
def test_opaque_source_write_blocks(command):
    reason = blocked(command)
    assert "opaque_source_write" in reason
    assert "Write or Edit" in reason


TRIGGERS = (
    """python3 -c 'open("x.txt", "w").write("y")'""",
    'sh -c "$CMD"',
    "python3 <<EOF\nimport os\nos.remove('x')\nEOF",
    "cat > out.md <<EOF\n$REPORT_BODY\nEOF",
    "base64 -d blob.txt > out.bin",
    "sed -i '' 's/a/b/' file.txt",
    "dd if=/dev/zero of=out.bin",
)


@pytest.mark.parametrize("command", TRIGGERS)
def test_the_environment_escape_releases_every_rule(command, monkeypatch):
    monkeypatch.setenv("ADW_ALLOW_PROTECTED_EDIT", "1")
    assert allowed(command) == {}


@pytest.mark.parametrize("command", TRIGGERS)
def test_a_config_key_releases_no_rule(command):
    config = {
        "protected_paths_authorized": True,
        "rule_gates": {rule: "off" for rule in RULES},
        "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
    }
    result = pre_bash.run({"tool_input": {"command": command}}, config)
    assert result.get("decision") == "block", result


@pytest.mark.parametrize("command", [
    "python3 -c 'print(1)'",
    "python3 -c '1 + 1'",
    "env -i python3 -c 'print(1)'",
    "python3.12 -c 'print(1)'",
    "env -S 'python3 -c \"print(1)\"'",
    "env --split-string 'python3 -c \"print(1)\"'",
    "env -S'python3 -c \"print(1)\"'",
    "env --split-string='python3 -c \"print(1)\"'",
    "base64 -d blob.txt",
    "base64 -o out.bin blob.txt",
    "openssl enc -out out.bin",
    "xxd -r blob.txt",
    "xxd -r -o 0x1000",
    "xxd -r -o 0x1000 infile",
    "xxd -r -o 16 dump.txt",
    "sed 's/a/b/' file.txt",
    "cat <<EOF\nsome text\nEOF",
    "cat <<EOF | psql\n$VAR\nEOF",
    "sh -c 'ls -la'",
    "bash script.sh",
    "grep 'python3 -c' docs/",
    "grep 'sed -i' docs/",
    "grep 'tee -a' docs/",
    "echo 'reminder to run dd if=/dev/zero later'",
    """echo env -S 'python3 -c "import os"'""",
    "dd if=/dev/zero of=/dev/null",
    "printf 'clean text' | python3 -c 'print(1)'",
    "awk '{print $1}' file.txt",
    "> out.log ls",
])
def test_read_only_idioms_stay_allowed(command):
    assert allowed(command) == {}
