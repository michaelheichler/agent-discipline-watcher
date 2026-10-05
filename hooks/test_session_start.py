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


def test_a_fresh_settings_file_gains_the_sonnet_command_block_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Written once, because the plugin ships no reviewer."""
    settings = _on_claude(monkeypatch)

    session_start.run({"source": "startup"})
    first = settings.read_text(encoding="utf-8")
    session_start.run({"source": "startup"})

    assert settings.read_text(encoding="utf-8") == first
    expected = claude_presets.managed_hooks({"hooks": claude_presets.generated_hooks("mixed")})
    assert expected
    assert claude_presets.managed_hooks(json.loads(first)) == expected
    assert claude_native.read_preset() == "mixed"


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
    assert stop["command"] == claude_presets.sonnet_command()
    assert stop["timeout"] == 45
    assert claude_native.read_preset() == "mixed"


def _retired_agent(model: str, prompt_line: str) -> dict:
    prompt = f"{claude_presets.MANAGED_MARKER}\nreview one finished turn\n1. {prompt_line}"
    return {"type": "agent", "model": model, "timeout": 120, "prompt": prompt}


RETIRED_AGENT_BLOCKS = {
    "haiku": ("claude-haiku-4-5", "Run this exact helper: '/old/hooks/read_claude_journal.sh'"),
    "mixed": ("claude-sonnet-5-5", "Run this exact helper with --documents: '/old/hooks/read_claude_journal.sh'"),
    "luna-native": ("luna", "Run this exact helper: '/old/hooks/read_claude_journal.sh'"),
}


@pytest.mark.parametrize("retired", sorted(RETIRED_AGENT_BLOCKS))
def test_a_retired_agent_block_is_replaced_by_the_sonnet_command(monkeypatch: pytest.MonkeyPatch, retired: str) -> None:
    """Replaced, because an agent hook cannot run the helper and silently drops every model verdict."""
    settings = _on_claude(monkeypatch)
    unrelated = {"type": "command", "command": "keep-this"}
    model, line = RETIRED_AGENT_BLOCKS[retired]
    settings.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [_retired_agent(model, line)]}, {"hooks": [unrelated]},
    ]}}), encoding="utf-8")
    claude_native.preset_path().parent.mkdir(parents=True, exist_ok=True)
    claude_native.preset_path().write_text(f"{retired}\n", encoding="utf-8")

    session_start.run({"source": "startup"})

    configured = json.loads(settings.read_text(encoding="utf-8"))
    handlers = [hook for group in configured["hooks"]["Stop"] for hook in group["hooks"]]
    assert unrelated in handlers
    assert {hook["type"] for hook in handlers} == {"command"}
    assert claude_presets.managed_hooks(configured) == claude_presets.managed_hooks(
        {"hooks": claude_presets.generated_hooks("mixed")}
    )
    assert claude_native.read_preset() == "mixed"


def test_a_luna_block_from_an_old_plugin_root_is_repointed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repointed, because the handler path goes stale too."""
    settings = _on_claude(monkeypatch)
    _moved(settings, "luna", edit_timeout=False)

    session_start.run({"source": "startup"})

    current = claude_presets.managed_hooks({"hooks": claude_presets.generated_hooks("luna")})
    assert claude_presets.managed_hooks(json.loads(settings.read_text(encoding="utf-8"))) == current
    assert claude_native.read_preset() == "luna"


def test_a_missing_block_is_seeded_with_the_stored_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded as stored, because a lost block must not silently downgrade a chosen Luna."""
    settings = _on_claude(monkeypatch)
    claude_native.preset_path().parent.mkdir(parents=True, exist_ok=True)
    claude_native.preset_path().write_text("luna\n", encoding="utf-8")

    session_start.run({"source": "startup"})

    assert claude_presets.managed_hooks(json.loads(settings.read_text(encoding="utf-8"))) == claude_presets.managed_hooks(
        {"hooks": claude_presets.generated_hooks("luna")}
    )
    assert claude_native.read_preset() == "luna"


CACHE_REVISION = Path(".claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher")


def _from_a_plugin_cache(monkeypatch: pytest.MonkeyPatch, home: Path, stable_installed: bool) -> Path:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(claude_presets, "PLUGIN_ROOT", home / CACHE_REVISION / "1.0.0")
    stable = home / claude_presets.STABLE_ROOT
    if stable_installed:
        (stable / "hooks").mkdir(parents=True)
        (stable / "hooks" / "claude_sonnet.sh").write_text("", encoding="utf-8")
    return stable if stable_installed else home / CACHE_REVISION / "1.0.0"


def _stop_command(settings: Path) -> str:
    return json.loads(settings.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]


@pytest.mark.parametrize("stable_installed", [True, False])
def test_a_plugin_cache_run_seeds_the_stable_handler_when_it_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stable_installed: bool) -> None:
    """Stable first, because adw-judge writes it and a cache revision vanishes on update."""
    settings = _on_claude(monkeypatch)
    root = _from_a_plugin_cache(monkeypatch, tmp_path, stable_installed)

    session_start.run({"source": "startup"})

    assert _stop_command(settings).endswith(f" {root}/hooks/claude_sonnet.sh")


@pytest.mark.parametrize("stable_installed", [True, False])
def test_an_old_cache_block_is_repointed_to_the_same_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stable_installed: bool) -> None:
    """Repointed to one root, because the two writers must agree."""
    settings = _on_claude(monkeypatch)
    root = _from_a_plugin_cache(monkeypatch, tmp_path, stable_installed)
    old = tmp_path / CACHE_REVISION / "0.9.0"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": f"ADW_CLAUDE_MANAGED={claude_presets.MANAGED_MARKER} {old}/hooks/claude_sonnet.sh", "timeout": 45},
    ]}]}}), encoding="utf-8")

    session_start.run({"source": "startup"})

    assert _stop_command(settings).endswith(f" {root}/hooks/claude_sonnet.sh")


def test_a_current_luna_block_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kept, because the user chose Luna."""
    settings = _on_claude(monkeypatch)
    claude_native.set_preset("luna", settings_path=settings, preset_path=claude_native.preset_path())
    before = settings.read_text(encoding="utf-8")

    session_start.run({"source": "startup"})

    assert settings.read_text(encoding="utf-8") == before
    assert claude_native.read_preset() == "luna"


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


def _warm_at_start(config: dict) -> None:
    session_start.run({"session_id": "s1", "source": "startup"}, config)


def _open_a_turn(config: dict) -> None:
    embedding_session.open_turn("s1", embedding_session.lease_root_for(config))


@pytest.mark.parametrize("take_lease", [_warm_at_start, _open_a_turn], ids=["warm-up", "turn"])
def test_an_idle_codex_session_stops_pinning_the_model_after_the_ttl(cold_worker, monkeypatch: pytest.MonkeyPatch, take_lease) -> None:
    """Expired, because a session without prose must free 709 MB."""
    _, config = cold_worker
    _on_codex(monkeypatch)
    monkeypatch.setattr(embedding_session, "CONSUMER_REGISTERED", True)
    server_root = embedding_session.default_root()
    taken = time.time()

    take_lease(config)

    assert _leases(config, taken + embedding_lease.LEASE_TTL_SECONDS - 5) == ("s1",)
    assert embedding_lease.has_live_leases(server_root, taken + embedding_lease.LEASE_TTL_SECONDS + 5) is False


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
