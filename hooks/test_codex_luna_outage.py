from pathlib import Path

import pytest

import record
import stop
from lib import codex_luna, journal, reporting, session_state, turn_retry
from lib.judge_contracts import ReviewKind
from lib.luna_storage import LunaProviderFailure
from test_task4_codex import MixedProvider, Provider, _result


@pytest.fixture(autouse=True)
def isolated_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reporting, "_reports_dir", lambda: tmp_path / "reports")


def _turn(tmp_path: Path, turn_id: str = "turn-1") -> tuple[dict, dict]:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text(f"The archive contains seven records for {turn_id}.\n", encoding="utf-8")
    journal.record_edit("outage", turn_id, turn_id, source, state_root=config["state_root"])
    return {"session_id": "outage", "turn_id": turn_id, "cwd": str(tmp_path)}, config


@pytest.mark.parametrize("category", ["availability", "authentication", "configuration", "timeout", "provider"])
def test_provider_outage_does_not_create_a_stop_loop(tmp_path: Path, category: str) -> None:
    payload, config = _turn(tmp_path)
    provider = Provider(error=LunaProviderFailure("reviewer unavailable", category=category))

    first = stop.run(payload, config, provider=provider)
    retries = [stop.run({**payload, "stop_hook_active": True}, config, provider=provider) for _ in range(5)]
    following, _ = _turn(tmp_path, "turn-2")
    next_turn = stop.run(following, config, provider=provider)

    assert first.get("decision") != "block"
    assert "unavailable" in first["systemMessage"]
    assert len(first["systemMessage"].encode("utf-8")) <= 900
    assert retries == [{}] * 5
    assert next_turn == {}
    assert len(provider.calls) == 1
    assert not session_state.read_state("outage", config["state_root"]).get(codex_luna.STATE_KEY)


def test_provider_retries_after_cooldown_on_a_new_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload, config = _turn(tmp_path)
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1000.0)
    failed = Provider(error=LunaProviderFailure("timed out", category="timeout"))
    stop.run(payload, config, provider=failed)
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1400.0)
    following, _ = _turn(tmp_path, "turn-2")
    recovered = Provider(_result(ReviewKind.DOCUMENT))

    assert stop.run(following, config, provider=recovered) == {}
    assert len(recovered.calls) == 1
    assert session_state.read_state("outage", config["state_root"])[codex_luna.STATE_KEY] == ["turn-2"]


def test_legacy_retry_limit_does_not_trap_an_active_stop(tmp_path: Path) -> None:
    payload, config = _turn(tmp_path)
    session_state.update_state("outage", lambda state: {
        **state,
        codex_luna.FAILED_KEY: [{"turn_id": "turn-1", "attempts": 3, "reason": "Luna judge timed out"}],
        codex_luna.RETRY_KEY: "turn-1",
    }, config["state_root"])
    provider = Provider(error=LunaProviderFailure("Luna judge timed out", category="timeout"))

    first = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)
    assert first.get("decision") != "block"
    assert stop.run({**payload, "stop_hook_active": True}, config, provider=provider) == {}
    assert len(provider.calls) <= 1


def test_provider_outage_preserves_deterministic_stop_blocks(tmp_path: Path) -> None:
    payload, config = _turn(tmp_path)
    provider = Provider(error=LunaProviderFailure("reviewer unavailable", category="availability"))
    stop.run(payload, config, provider=provider)
    source = tmp_path / "oversized.py"
    source.write_text("value = 1\n" * 1000, encoding="utf-8")
    edit = {**payload, "tool_name": "Write", "tool_use_id": "oversized", "tool_input": {"file_path": str(source)}}

    assert record.run(edit, config)["decision"] == "block"
    response = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)
    assert response["decision"] == "block"
    assert "file_too_long" in response["reason"]
    assert len(provider.calls) == 1


def test_invalid_provider_result_uses_the_outage_backoff(tmp_path: Path) -> None:
    payload, config = _turn(tmp_path)
    provider = Provider(result="invalid")

    response = stop.run(payload, config, provider=provider)

    assert response.get("decision") != "block"
    assert "invalid result" in response["systemMessage"]
    assert stop.run({**payload, "stop_hook_active": True}, config, provider=provider) == {}
    assert len(provider.calls) == 1


def test_exhausted_review_deadline_uses_the_outage_backoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload, config = _turn(tmp_path)
    provider = Provider(_result(ReviewKind.DOCUMENT))
    monkeypatch.setattr(codex_luna, "REVIEW_DEADLINE_SECONDS", 0)

    response = stop.run(payload, config, provider=provider)

    assert response.get("decision") != "block"
    assert "deadline" in response["systemMessage"]
    assert stop.run({**payload, "stop_hook_active": True}, config, provider=provider) == {}
    assert provider.calls == []


def _partial_review(tmp_path: Path) -> tuple[dict, dict, MixedProvider, dict]:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    for name, text in {
        "note.md": "A sentence.\n",
        "unrelated.md": "The archive contains seven records.\n",
        "code.py": "# Returns the rows because the caller needs a stable order for the report.\nvalue = 1\n",
    }.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        journal.record_edit("partial", "turn-1", name, path, state_root=config["state_root"])
    provider = MixedProvider(fail_on_call=2)
    payload = {"session_id": "partial", "turn_id": "turn-1", "cwd": str(tmp_path)}
    first = stop.run(payload, config, provider=provider)

    assert first["decision"] == "block"
    assert "ADW Luna document review" in first["reason"]
    assert len(provider.calls) == 2
    return payload, config, provider, first


def test_partial_feedback_blocks_unchanged_retries_without_provider_calls(tmp_path: Path) -> None:
    payload, config, provider, first = _partial_review(tmp_path)

    retries = [stop.run({**payload, "stop_hook_active": True}, config, provider=provider) for _ in range(3)]

    assert [response.get("decision") for response in retries] == ["block"] * 3
    assert [response["reason"] for response in retries] == [first["reason"]] * 3
    assert all("systemMessage" not in response for response in retries)
    assert len(provider.calls) == 2
    assert not session_state.read_state("partial", config["state_root"]).get(codex_luna.STATE_KEY)


@pytest.mark.parametrize("name", ["unrelated.md", "code.py", "new.md"])
def test_unrelated_edits_do_not_release_confirmed_feedback(tmp_path: Path, name: str) -> None:
    payload, config, provider, first = _partial_review(tmp_path)
    path = tmp_path / name
    path.write_text("The archive contains eight records.\n", encoding="utf-8")
    journal.record_edit("partial", "turn-1", "repair", path, state_root=config["state_root"])

    response = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)

    assert response.get("decision") == "block"
    assert response["reason"] == first["reason"]
    assert len(provider.calls) == 2


@pytest.mark.parametrize("operation", ["repair", "delete"])
@pytest.mark.parametrize("refresh_journal", [False, True])
def test_changed_feedback_source_releases_stale_feedback(
    tmp_path: Path, operation: str, refresh_journal: bool,
) -> None:
    payload, config, provider, _first = _partial_review(tmp_path)
    source = tmp_path / "note.md"
    if operation == "repair":
        source.write_text("The archive contains eight records.\n", encoding="utf-8")
    else:
        source.unlink()
    if refresh_journal:
        journal.record_edit("partial", "turn-1", "repair", source, state_root=config["state_root"])

    assert stop.run({**payload, "stop_hook_active": True}, config, provider=provider) == {}
    assert len(provider.calls) == 2
    assert not session_state.read_state("partial", config["state_root"]).get(codex_luna.STATE_KEY)


def test_confirmed_feedback_survives_cooldown_expiry_on_a_new_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1000.0)
    payload, config, provider, first = _partial_review(tmp_path)
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1400.0)

    response = stop.run({**payload, "turn_id": "turn-2"}, config, provider=provider)

    assert response.get("decision") == "block"
    assert response["reason"] == first["reason"]
    assert len(provider.calls) == 2


def test_transient_source_read_failure_keeps_confirmed_feedback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload, config, provider, first = _partial_review(tmp_path)
    monkeypatch.setattr(journal, "_read_content", lambda _path: journal._ReadOutcome("transient"))

    response = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)

    assert response.get("decision") == "block"
    assert response["reason"] == first["reason"]
    assert len(provider.calls) == 2


@pytest.mark.parametrize("operation", ["repair", "delete"])
@pytest.mark.parametrize("retry_turn", ["turn-1", "older-turn"])
def test_provider_outage_clears_only_its_legacy_retry_failure(
    tmp_path: Path, operation: str, retry_turn: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1000.0)
    payload, config = _turn(tmp_path)
    historical = {"turn_id": "older-turn", "attempts": 1, "reason": "invalid journal"}
    session_state.update_state("outage", lambda state: {
        **state,
        turn_retry.RETRY_KEY: retry_turn,
        turn_retry.FAILED_KEY: [historical, {"turn_id": "turn-1", "attempts": 3, "reason": "provider unavailable"}],
    }, config["state_root"])
    provider = Provider(error=LunaProviderFailure("provider unavailable", category="availability"))

    assert stop.run(payload, config, provider=provider).get("decision") != "block"
    source = tmp_path / "note.md"
    if operation == "repair":
        source.write_text("The archive contains eight records.\n", encoding="utf-8")
    else:
        source.unlink()
    journal.record_edit("outage", "turn-2", "repair", source, state_root=config["state_root"])
    monkeypatch.setattr(codex_luna.time, "time", lambda: 1400.0)

    assert stop.run({**payload, "stop_hook_active": True}, config, provider=provider) == {}
    state = session_state.read_state("outage", config["state_root"])
    assert state[turn_retry.FAILED_KEY] == [historical]
    assert state.get(turn_retry.RETRY_KEY) == ("older-turn" if retry_turn == "older-turn" else None)
    assert len(provider.calls) == 1
