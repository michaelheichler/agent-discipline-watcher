from __future__ import annotations

from types import SimpleNamespace

from lib import host, judge, judge_provider, pattern_judge


def _provider() -> judge_provider.Provider:
    return judge_provider.Provider("claude-haiku-4-5", "system text")


def _recorder(seen: list[list[str]]):
    def record(command, **_kwargs) -> SimpleNamespace:
        seen.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    return record


def _clear(monkeypatch) -> None:
    monkeypatch.delenv(judge_provider.RECURSION_GUARD, raising=False)
    monkeypatch.delenv(host.OMP_ENV, raising=False)


def test_omp_gets_a_named_reason_instead_of_an_empty_result(monkeypatch) -> None:
    """Report the reason because an empty result would read as a clean verdict."""
    _clear(monkeypatch)
    monkeypatch.setenv(host.OMP_ENV, "1")

    answer = judge_provider.complete("anything", _provider())

    assert answer.text is None
    assert host.OMP in answer.reason


def test_a_recursing_judge_refuses_before_it_spawns(monkeypatch) -> None:
    """Guard the tree because a hook judging its own judge would never terminate."""
    _clear(monkeypatch)
    monkeypatch.setenv(judge_provider.RECURSION_GUARD, "1")

    answer = judge_provider.complete("anything", _provider())

    assert answer.text is None
    assert "already runs" in answer.reason


def test_no_subprocess_starts_while_a_reason_stands(monkeypatch) -> None:
    """Skip the spawn because a nested CLI would bill an account nobody chose."""
    spawned: list[object] = []
    monkeypatch.setattr(judge_provider.subprocess, "run", lambda *a, **k: spawned.append(a))
    _clear(monkeypatch)
    monkeypatch.setenv(host.OMP_ENV, "1")

    judge_provider.complete("anything", _provider())

    assert spawned == []


def test_a_clean_exit_returns_the_output_with_no_reason(monkeypatch) -> None:
    """Leave the reason empty because a caller branches on it to decide failure."""
    _clear(monkeypatch)
    monkeypatch.setattr(
        judge_provider.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="body", stderr=""),
    )

    answer = judge_provider.complete("anything", _provider())

    assert answer == judge_provider.Completion("body", "")


def test_a_failing_exit_names_the_status(monkeypatch) -> None:
    """Name the status because a silent None hides a broken install from the user."""
    _clear(monkeypatch)
    monkeypatch.setattr(
        judge_provider.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=3, stdout="", stderr=""),
    )

    answer = judge_provider.complete("anything", _provider())

    assert answer.text is None
    assert "status 3" in answer.reason


def test_a_missing_binary_names_the_failure(monkeypatch) -> None:
    """Survive an absent binary because a hook must never crash the session it gates."""
    _clear(monkeypatch)

    def explode(*_args, **_kwargs) -> None:
        raise OSError("no such file")

    monkeypatch.setattr(judge_provider.subprocess, "run", explode)

    answer = judge_provider.complete("anything", _provider())

    assert answer.text is None
    assert "OSError" in answer.reason


def test_the_child_environment_drops_the_key_and_sets_the_guard(monkeypatch) -> None:
    """Drop the key because the session login is the account the user already chose."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value")

    env = judge_provider.child_environment()

    assert "ANTHROPIC_API_KEY" not in env
    assert env[judge_provider.RECURSION_GUARD] == "1"


def test_the_spawned_judge_gets_no_tools_and_no_settings(monkeypatch) -> None:
    """Strip both because a judge with tools could edit the file it was asked to read."""
    seen: list[list[str]] = []
    _clear(monkeypatch)
    monkeypatch.setattr(judge_provider.subprocess, "run", _recorder(seen))

    judge_provider.complete("a prompt", _provider())

    command = seen[0]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    assert command[command.index("--model") + 1] == "claude-haiku-4-5"


def test_both_judges_spawn_through_the_one_provider(monkeypatch) -> None:
    """Patch one place and stop both, because a second spawn is a second place to miss a change."""
    seen: list[list[str]] = []
    _clear(monkeypatch)
    monkeypatch.setattr(judge_provider.subprocess, "run", _recorder(seen))

    judge.judge((judge.Candidate("a.py", 1, "# Returns the rows."),))
    rule = pattern_judge.PatternRule("ai_closer", "cut it", ("bad",), ("good",))
    pattern_judge.confirm(rule, (pattern_judge.PatternCandidate("a.md", 1, "text"),), "claude-haiku-4-5")

    assert len(seen) == 2
    assert all(command[:2] == ["claude", "-p"] for command in seen)


def test_the_judge_entry_point_answers_nothing_without_a_provider(monkeypatch) -> None:
    """Return None rather than an empty tuple because no verdict differs from every verdict clean."""
    _clear(monkeypatch)
    monkeypatch.setenv(host.OMP_ENV, "1")

    candidate = judge.Candidate("a.py", 1, "# Sorts the rows before returning them.")

    assert judge.judge((candidate,)) is None
