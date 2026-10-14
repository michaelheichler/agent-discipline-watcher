from __future__ import annotations

import pytest

import pre_bash


def verdict(command: str) -> dict:
    return pre_bash.run({"tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    """perl -e 'open my $h, ">", "x"; print $h "y"'""",
    """perl -e 'sysopen my $h, "x", 1'""",
    """perl -e 'syswrite STDOUT, "y"'""",
    """perl -e 'rename "a", "b"'""",
    """perl -e 'unlink "a"'""",
    """perl -e 'eval "1"'""",
    """perl -e 'system "true"'""",
    """perl -e 'exec "true"'""",
    """perl -e 'link "a", "b"'""",
    """perl -e 'symlink "a", "b"'""",
    """perl -e 'mkdir "d"'""",
    """perl -e 'rmdir "d"'""",
    """perl -e 'chmod 0644, "a"'""",
    """perl -e 'utime undef, undef, "a"'""",
    """perl -e 'truncate "a", 0'""",
    """perl -e 'print qx{date}'""",
    """perl -e 'print `date`'""",
    """ruby -e 'IO.popen("date")'""",
    """ruby -e 'FileUtils.touch "a"'""",
    """ruby -e 'puts %x(date)'""",
    """perl -pe 'BEGIN { $^I = "" } s/a/b/' f.txt""",
    """ruby -e 'open "x", "w"'""",
    """ruby -e 'File.write("x", "y")'""",
    """ruby -e 'IO.write("x", "y")'""",
    """ruby -e 'File.open("x", "w") { |f| f.puts 1 }'""",
    """ruby -e 'File::open("x", "w")'""",
    """ruby -e 'Object.const_get(:Kernel)'""",
])
def test_a_perl_or_ruby_write_form_without_parentheses_blocks(command: str) -> None:
    result = verdict(command)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("command", [
    "perl -e 'print 1+2'",
    """perl -ne 'print if /a/' f.txt""",
    "ruby -e 'puts [1, 2].sum'",
    """ruby -e 'puts "a,b".split(",").first'""",
])
def test_a_read_only_perl_or_ruby_payload_passes(command: str) -> None:
    assert verdict(command) == {}
