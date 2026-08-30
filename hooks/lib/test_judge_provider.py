from __future__ import annotations

import ast
from pathlib import Path

from lib import host, judge, judge_provider, pattern_judge

PROVIDER_SOURCE = Path(judge_provider.__file__)


def _provider() -> judge_provider.Provider:
    return judge_provider.Provider("claude-haiku-4-5", "system text")


def _clear(monkeypatch) -> None:
    monkeypatch.delenv(judge_provider.RECURSION_GUARD, raising=False)
    monkeypatch.delenv(host.OMP_ENV, raising=False)


def test_the_seam_names_no_process_launcher_at_all() -> None:
    """Read the source because a banned spawn reintroduced by a later edit must fail here, not in a bill."""
    tree = ast.parse(PROVIDER_SOURCE.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in getattr(node, "names", [])
    }

    assert "subprocess" not in imported
    assert "os.system" not in PROVIDER_SOURCE.read_text(encoding="utf-8")


def test_the_banned_cli_appears_nowhere_in_the_seam() -> None:
    """Pin the literal because 1ceecb3 wired this command to a hook and billed the user's own account."""
    body = PROVIDER_SOURCE.read_text(encoding="utf-8")

    assert '"claude"' not in body
    assert "'-p'" not in body and '"-p"' not in body


def test_every_host_gets_a_named_reason_rather_than_an_empty_result(monkeypatch) -> None:
    """Report the reason because an empty result would read as a clean verdict."""
    _clear(monkeypatch)

    answer = judge_provider.complete("anything", _provider())

    assert answer.text is None
    assert answer.reason


def test_omp_still_names_itself_in_the_reason(monkeypatch) -> None:
    """Keep the host in the message because a maintainer reads it to find which runtime refused."""
    _clear(monkeypatch)
    monkeypatch.setenv(host.OMP_ENV, "1")

    assert host.OMP in judge_provider.complete("anything", _provider()).reason


def test_a_recursing_judge_is_still_named_first(monkeypatch) -> None:
    """Keep the guard because a hook judging its own judge would never terminate."""
    _clear(monkeypatch)
    monkeypatch.setenv(judge_provider.RECURSION_GUARD, "1")

    assert "already runs" in judge_provider.complete("anything", _provider()).reason


def test_availability_is_false_everywhere_now(monkeypatch) -> None:
    """Answer false because the host agent hook judges and python holds no provider of its own."""
    _clear(monkeypatch)

    assert judge_provider.available() is False


def test_the_child_environment_drops_the_key_and_sets_the_guard(monkeypatch) -> None:
    """Drop the key because the session login is the account the user already chose."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value")

    env = judge_provider.child_environment()

    assert "ANTHROPIC_API_KEY" not in env
    assert env[judge_provider.RECURSION_GUARD] == "1"


def test_the_comment_judge_answers_none_rather_than_every_candidate_clean(monkeypatch) -> None:
    """Return None rather than an empty tuple because no verdict differs from every verdict clean."""
    _clear(monkeypatch)

    assert judge.judge((judge.Candidate("a.py", 1, "# Sorts the rows."),)) is None


def test_the_pattern_judge_reports_the_absence_instead_of_swallowing_it(monkeypatch) -> None:
    """Name the reason because an empty keep set is how a judged rule stopped firing unnoticed."""
    _clear(monkeypatch)
    rule = pattern_judge.PatternRule("ai_closer", "cut it", ("bad",), ("good",))

    outcome = pattern_judge.confirm_all(((rule, (pattern_judge.PatternCandidate("a.md", 1, "text"),)),), "m")

    assert outcome.kept == {}
    assert outcome.unjudged == ("ai_closer",)
    assert outcome.reason
