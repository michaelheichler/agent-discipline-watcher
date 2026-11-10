"""Preserve executable boundaries because quoted data must not terminate substitutions."""
from __future__ import annotations

import operator
import shlex

import pytest

from lib.shell_lines import command_lines
from lib.shell_text import shell_text, shell_words, split_redirects


@pytest.mark.parametrize("command,expected", [
    pytest.param("$(printf ')'; echo ok)", "printf ')'; echo ok\n$SUBSTITUTED",
                 id="quoted-close"),
    pytest.param(r"$(printf \); echo ok)", "printf \\); echo ok\n$SUBSTITUTED",
                 id="escaped-close"),
    pytest.param("$(printf '('; echo ok)", "printf '('; echo ok\n$SUBSTITUTED",
                 id="quoted-open"),
    pytest.param('$(printf "$(printf \')\')"; echo ok)',
                 'printf \')\'\nprintf "$(printf \')\')"; echo ok\n$SUBSTITUTED',
                 id="nested-quotes"),
    pytest.param("$(printf 'unterminated)", "printf 'unterminated)\n$SUBSTITUTED",
                 id="unmatched-quote"),
    pytest.param("$(printf ok # )\n; printf done)",
                 "printf ok \n; printf done\n$SUBSTITUTED", id="comment-close"),
])
def test_substitution_boundaries_ignore_data_parentheses(command, expected) -> None:
    assert shell_text(command) == expected


@pytest.mark.parametrize("header", [
    pytest.param("cat <<'END'", id="quoted"),
    pytest.param("cat <<'END' # literal body", id="comment-after-header"),
])
def test_literal_heredoc_bodies_remain_attached_to_their_command(header) -> None:
    command = f"{header}\n$(printf ')')\nEND\nprintf done"

    lines = command_lines(command)

    assert [(line.text.strip(), line.bodies) for line in lines] == [
        ("cat <<'END'", ("$(printf ')')\n",)), ("printf done", ()),
    ]


def test_a_literal_heredoc_substitution_remains_data_in_executable_text() -> None:
    command = "cat <<'END'\n$(printf ')')\nEND\nprintf done"

    words, redirects = split_redirects(shlex.split(shell_text(command)))

    assert words == ["cat", "printf", "done"]
    assert [(redirect.operator, redirect.target) for redirect in redirects] == [
        ("<<", "$(printf ')')\n"),
    ]


@pytest.mark.parametrize("suffix", [
    pytest.param("", id="plain-header"),
    pytest.param(" # literal body", id="comment-after-header"),
])
def test_literal_heredoc_quotes_and_parentheses_cannot_end_an_outer_substitution(suffix) -> None:
    body = "Don't misread this ) or (.\n"
    substitution = f"$(cat <<'EOF'{suffix}\n{body}EOF\n)"
    command = f'git commit -m "{substitution}"'

    words, redirects = split_redirects(shlex.split(shell_text(command)))

    assert words == ["cat", "git", "commit", "-m", substitution]
    assert [(redirect.operator, redirect.target) for redirect in redirects] == [("<<", body)]


def test_shell_word_results_cannot_poison_a_later_parse() -> None:
    words = shell_words('echo a"b c"d')

    with pytest.raises(TypeError):
        operator.setitem(words, 0, "changed")
    assert shell_words('echo a"b c"d') == ("echo", "a", '"b c"', "d")
