from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

import session_start
from lib import claude_native, claude_presets, embedding_lease, embedding_session, host


class SessionStartLifecycleTests(unittest.TestCase):
    def test_session_start_runs_retention_and_acquires_a_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"state_root": str(root / "state"), "ledger_root": str(root / "ledger")}
            with patch("session_start.retention.sweep") as sweep:
                session_start.run({"session_id": "s1"}, config)

            sweep.assert_called_once()
            self.assertEqual(
                session_start.session_state.live_session_ids(config["state_root"]), frozenset({"s1"})
            )

    def test_resumed_old_session_is_protected_before_startup_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            session = state_root / "s1"
            session.mkdir(parents=True)
            (session / "state.json").write_text("{}", encoding="utf-8")
            stale = time.time() - 31 * 24 * 60 * 60
            os.utime(session, (stale, stale))

            session_start.run({"session_id": "s1"}, {"state_root": str(state_root)})

            self.assertTrue(session.exists())

    def test_startup_cleanup_is_idempotent_for_the_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"state_root": str(root / "state"), "ledger_root": str(root / "ledger")}
            session = root / "state" / "s1"
            session.mkdir(parents=True)
            (session / "state.json").write_text("{}", encoding="utf-8")
            stale = time.time() - 31 * 24 * 60 * 60
            os.utime(session, (stale, stale))

            session_start.run({"session_id": "s1"}, config)
            session_start.run({"session_id": "s1"}, config)

            self.assertTrue(session.exists())
            self.assertEqual(session_start.session_state.live_session_ids(config["state_root"]), frozenset({"s1"}))


def _context(source: str | None) -> str:
    payload = {} if source is None else {"source": source}
    return session_start.run(payload)["hookSpecificOutput"]["additionalContext"]


class SessionStartContractTests(unittest.TestCase):
    def test_startup_and_an_unknown_source_get_the_full_contract(self) -> None:
        for source in ("startup", None, "unexpected"):
            with self.subTest(source=source):
                self.assertEqual(_context(source), session_start.CONTRACT)

    def test_resume_clear_and_compact_get_one_line(self) -> None:
        for source in ("resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(_context(source), (
                    "ADW is active. Fix each named file and line, then retry the blocked action. "
                    "Do not disable the gate or delete its state."
                ))


def _on_claude(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(host.CLAUDE_ENV, "1")
    for other in (host.OMP_ENV, host.CODEX_ENV, host.COWORK_ENV):
        monkeypatch.delenv(other, raising=False)
    return claude_native.settings_path()


def test_a_fresh_settings_file_gains_the_haiku_block_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Written once, because the plugin ships no reviewer."""
    settings = _on_claude(monkeypatch)

    session_start.run({"source": "startup"})
    first = settings.read_text(encoding="utf-8")
    session_start.run({"source": "startup"})

    assert settings.read_text(encoding="utf-8") == first
    expected = claude_presets.managed_hooks({"hooks": claude_presets.generated_hooks("haiku")})
    assert expected
    assert claude_presets.managed_hooks(json.loads(first)) == expected


def _moved(settings: Path, preset: str, edit_timeout: bool) -> None:
    claude_native.set_preset(preset, settings_path=settings, preset_path=claude_native.preset_path())
    old_root = claude_presets.PLUGIN_ROOT.parent / "old-revision"
    text = settings.read_text(encoding="utf-8").replace(str(claude_presets.PLUGIN_ROOT), str(old_root))
    moved = json.loads(text)
    if edit_timeout:
        moved["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 45
    settings.write_text(json.dumps(moved), encoding="utf-8")


def test_a_block_from_an_old_plugin_root_is_repointed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repointed, because an old cache revision can vanish."""
    settings = _on_claude(monkeypatch)
    _moved(settings, "mixed", edit_timeout=True)

    session_start.run({"source": "startup"})

    stop = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert stop["prompt"] == claude_presets.stop_prompt("mixed")
    assert stop["timeout"] == 45
    assert claude_native.read_preset() == "mixed"


def test_a_luna_block_from_an_old_plugin_root_is_repointed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repointed, because the handler path goes stale too."""
    settings = _on_claude(monkeypatch)
    _moved(settings, "luna", edit_timeout=False)

    session_start.run({"source": "startup"})

    current = claude_presets.managed_hooks({"hooks": claude_presets.generated_hooks("luna")})
    assert claude_presets.managed_hooks(json.loads(settings.read_text(encoding="utf-8"))) == current


def test_a_block_the_user_changed_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kept, because the user chose it."""
    settings = _on_claude(monkeypatch)
    claude_native.set_preset("mixed", settings_path=settings, preset_path=claude_native.preset_path())
    edited = json.loads(settings.read_text(encoding="utf-8"))
    edited["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 45
    settings.write_text(json.dumps(edited), encoding="utf-8")
    before = settings.read_text(encoding="utf-8")

    session_start.run({"source": "startup"})

    assert settings.read_text(encoding="utf-8") == before


def test_unreadable_settings_give_one_notice(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Continued, because a broken file must not stop the session."""
    settings = _on_claude(monkeypatch)
    settings.write_text("{not json", encoding="utf-8")

    output = session_start.run({"source": "startup"})

    assert output["hookSpecificOutput"]["additionalContext"] == session_start.CONTRACT
    assert settings.read_text(encoding="utf-8") == "{not json"
    notice = capsys.readouterr().err
    assert notice.count("\n") == 1
    assert "Claude settings" in notice


def test_another_host_writes_no_claude_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipped, because Codex never reads Claude settings."""
    settings = _on_claude(monkeypatch)
    monkeypatch.setenv(host.CODEX_ENV, "1")

    session_start.run({"source": "startup"})

    assert not settings.exists()


def _on_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(host.CODEX_ENV, "1")
    for other in (host.OMP_ENV, host.CLAUDE_ENV, host.COWORK_ENV):
        monkeypatch.delenv(other, raising=False)


@pytest.fixture(name="cold_worker")
def _cold_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[list, dict]:
    """Faked, because a test must never load the real model."""
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")
    for name in embedding_session.USER_URL_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(embedding_session, "provisioned", lambda: True)
    launched: list = []
    monkeypatch.setattr(embedding_session, "start_detached", launched.append)
    return launched, {"state_root": str(tmp_path / "state")}


def _leases(config: dict, now: float) -> tuple[str, ...]:
    return embedding_lease.live_sessions(now, embedding_session.lease_root_for(config))


def test_a_codex_start_warms_the_model_without_waiting(cold_worker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warmed, because Codex votes inline within 9 seconds."""
    launched, config = cold_worker
    _on_codex(monkeypatch)

    started = time.monotonic()
    output = session_start.run({"session_id": "s1", "source": "startup"}, config)

    assert time.monotonic() - started < 2.0
    assert output["hookSpecificOutput"]["additionalContext"] == session_start.CONTRACT
    assert launched == [embedding_session.default_root()]
    assert _leases(config, time.time()) == ("s1",)


def test_a_codex_start_without_the_model_stays_quiet(cold_worker, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Skipped, because SessionStart must never download."""
    launched, config = cold_worker
    _on_codex(monkeypatch)
    monkeypatch.setattr(embedding_session, "provisioned", lambda: False)

    output = session_start.run({"session_id": "s1", "source": "startup"}, config)

    assert output["hookSpecificOutput"]["additionalContext"] == session_start.CONTRACT
    assert capsys.readouterr().err == ""
    assert launched == []
    assert _leases(config, time.time()) == ()


def test_a_claude_start_leaves_the_model_to_the_async_route(cold_worker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipped, because the Claude vote waits 120 seconds."""
    launched, config = cold_worker
    _on_claude(monkeypatch)

    session_start.run({"session_id": "s1", "source": "startup"}, config)

    assert launched == []
    assert _leases(config, time.time()) == ()


if __name__ == "__main__":
    unittest.main()
