from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from lib import claude_native, journal, session_state


def test_generated_preset_contract_has_batched_roles_and_no_pretool_hook() -> None:
    generated = claude_native.generated_hooks("mixed")

    assert set(generated) == {"PostToolUse", "Stop"}
    post = generated["PostToolUse"][0]
    stop = generated["Stop"][0]
    assert post["matcher"] == "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
    assert post["hooks"][0]["type"] == "agent"
    assert post["hooks"][0]["model"] == "haiku"
    assert stop["hooks"][0]["type"] == "agent"
    assert stop["hooks"][0]["model"] == "sonnet"
    assert "batch" in stop["hooks"][0]["prompt"].lower()
    for preset in claude_native.PRESETS:
        assert "PreToolUse" not in claude_native.generated_hooks(preset)
    luna = claude_native.generated_hooks("luna")
    for lifecycle in ("PostToolUse", "Stop"):
        handler = luna[lifecycle][0]["hooks"][0]
        assert handler["type"] == "command"
        assert "model" not in handler
        assert "claude_luna.sh" in handler["command"]
        assert claude_native.MANAGED_MARKER in handler["command"]


@pytest.mark.parametrize("preset", ("mixed", "luna", "haiku", "sonnet"))
def test_preset_switch_is_idempotent_and_preserves_unrelated_settings(tmp_path: Path, preset: str) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "model": "claude-opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }), encoding="utf-8")

    first = claude_native.set_preset(preset, settings_path=settings, preset_path=tmp_path / "preset")
    once = settings.read_text(encoding="utf-8")
    second = claude_native.set_preset(preset, settings_path=settings, preset_path=tmp_path / "preset")

    assert first == second == preset
    assert settings.read_text(encoding="utf-8") == once
    merged = json.loads(once)
    assert merged["model"] == "claude-opus"
    commands = [
        row["hooks"][0]["command"]
        for row in merged["hooks"]["Stop"]
        if row["hooks"][0]["type"] == "command"
    ]
    assert "other" in commands
    managed = [command for command in commands if claude_native.MANAGED_MARKER in command]
    assert len(managed) == (1 if preset == "luna" else 0)


def test_preset_default_is_haiku_and_the_mix_is_opt_in(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert claude_native.default_preset({}, preset_path=missing) == "haiku"
    assert claude_native.default_preset({"CLAUDE_CODE_REMOTE": "true"}, preset_path=missing) == "haiku"
    assert claude_native.default_preset({"CLAUDE_CODE_REMOTE": "TRUE"}, preset_path=missing) == "haiku"
    assert claude_native.default_preset({"ADW_CLAUDE_HAIKU_ONLY": "1"}, preset_path=missing) == "haiku"
    assert claude_native.default_preset({"TERM_PROGRAM": "Claude"}, preset_path=missing) == "haiku"
    assert claude_native.default_preset({"ADW_CLAUDE_PRESET": "mixed"}, preset_path=missing) == "mixed"

    stored = tmp_path / "preset"
    claude_native.set_preset("mixed", settings_path=tmp_path / "settings.json", preset_path=stored)
    assert claude_native.default_preset({}, preset_path=stored) == "mixed"
    assert claude_native.default_preset({"ADW_CLAUDE_HAIKU_ONLY": "1"}, preset_path=stored) == "haiku"


def test_candidate_journal_deduplicates_final_content_hash_and_excludes_unrelated_files(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    unrelated = tmp_path / "b.py"
    unrelated.write_text("value = 2\n", encoding="utf-8")

    first = journal.record_edit("session", "turn-1", "tool-1", source, state_root=tmp_path / "state")
    second = journal.record_edit("session", "turn-1", "tool-2", source, state_root=tmp_path / "state")

    assert first
    assert second == []
    rows = journal.read("session", state_root=tmp_path / "state")
    assert len(rows) == 1
    assert rows[0]["path"] == str(source)
    assert rows[0]["content_hash"]
    assert str(unrelated) not in json.dumps(rows)


def test_candidate_journal_drops_a_previous_candidate_when_final_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    state_root = tmp_path / "state"

    journal.record_edit("session", "turn-1", "tool-1", source, state_root=state_root)
    source.write_text("value = 2\n", encoding="utf-8")
    journal.record_edit("session", "turn-2", "tool-2", source, state_root=state_root)

    assert journal.read("session", state_root=state_root) == []


def test_candidate_journal_canonicalizes_relative_absolute_and_symlink_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "a.md"
    alias = tmp_path / "alias.md"
    state_root = tmp_path / "state"
    source.write_text("A paragraph that should be reviewed.\n", encoding="utf-8")
    alias.symlink_to(source)
    monkeypatch.chdir(tmp_path)

    relative = journal.record_edit("session", "turn-1", "tool-1", "a.md", state_root=state_root)
    absolute = journal.record_edit("session", "turn-2", "tool-2", source, state_root=state_root)
    linked = journal.record_edit("session", "turn-3", "tool-3", alias, state_root=state_root)

    assert relative
    assert absolute == []
    assert linked == []
    rows = journal.read("session", state_root=state_root)
    assert len(rows) == 1
    assert rows[0]["path"] == str(source.resolve())
    assert rows[0]["path_identity"] == str(source.resolve())


def test_candidate_journal_prunes_the_old_path_after_a_move(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    state_root = tmp_path / "state"
    old.write_text("A paragraph that should be reviewed.\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool-1", old, state_root=state_root)
    old.rename(new)

    journal.record_edit("session", "turn-2", "tool-2", new, state_root=state_root)

    rows = journal.read("session", state_root=state_root)
    assert len(rows) == 1
    assert rows[0]["path"] == str(new.resolve())


def test_candidate_journal_discards_malformed_stale_path_rows_without_crashing(tmp_path: Path) -> None:
    source = tmp_path / "new.md"
    state_root = tmp_path / "state"
    source.write_text("A paragraph that should be reviewed.\n", encoding="utf-8")
    session_state.write_state("session", {
        journal.STATE_KEY: [{
            "role": "document", "path": "\x00invalid", "source_context": "stale",
            "content_hash": "stale",
        }],
    }, state_root)

    journal.record_edit("session", "turn", "tool", source, state_root=state_root)

    rows = journal.read("session", state_root=state_root)
    assert len(rows) == 1
    assert rows[0]["path"] == str(source.resolve())


def test_candidate_journal_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "candidate.md"
    os.mkfifo(fifo)
    finished = threading.Event()
    result: list[list[dict]] = []

    def read_fifo() -> None:
        result.append(journal.record_edit("session", "turn", "tool", fifo, state_root=tmp_path / "state"))
        finished.set()

    thread = threading.Thread(target=read_fifo, daemon=True)
    thread.start()
    assert finished.wait(0.5), "FIFO journal read blocked"
    thread.join(1)
    assert result == [[]]


def test_candidate_journal_rejects_oversized_regular_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "large.md"
    monkeypatch.setattr(journal, "MAX_FILE_BYTES", 32, raising=False)
    source.write_text("A paragraph that is larger than the bounded journal read.\n", encoding="utf-8")

    assert journal.record_edit("session", "turn", "tool", source, state_root=tmp_path / "state") == []


def test_managed_luna_command_and_agent_entries_are_replaced_without_touching_unrelated_hooks() -> None:
    old_agent = {
        "type": "agent", "model": "haiku", "prompt": claude_native.MANAGED_MARKER,
    }
    old_command = {
        "type": "command", "command": f"ADW_CLAUDE_MANAGED={claude_native.MANAGED_MARKER} /old-handler",
    }
    managed_luna_command = {
        "type": "command",
        "command": f"ADW_CLAUDE_MANAGED={claude_native.MANAGED_MARKER} {claude_native.LUNA_HANDLER_PATH}",
    }
    unrelated_luna_command = {"type": "command", "command": "/other/claude_luna.sh"}
    unrelated = {"type": "command", "command": "keep-this"}
    merged = claude_native.settings_for_preset(
        {"hooks": {"PostToolUse": [{"hooks": [old_agent, old_command, managed_luna_command, unrelated_luna_command, unrelated]}]}}, "mixed",
    )

    handlers = [
        hook
        for group in merged["hooks"]["PostToolUse"]
        for hook in group["hooks"]
    ]
    assert old_agent not in handlers
    assert old_command not in handlers
    assert managed_luna_command not in handlers
    assert unrelated_luna_command in handlers
    assert unrelated in handlers
    assert any(handler["type"] == "agent" for handler in handlers)


def test_cli_rejects_extra_preset_arguments(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(Path(__file__).parents[2] / "bin" / "adw-judge"), "mixed", "sonnet"],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "ADW_CLAUDE_SETTINGS": str(tmp_path / "settings.json"),
            "ADW_CLAUDE_PRESET_FILE": str(tmp_path / "preset"),
        }, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2


def test_adw_judge_launcher_uses_the_newest_compatible_python(tmp_path: Path) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3").write_text(
        '#!/bin/sh\nif [ "$1" = "-c" ]; then printf "3.9.0\\n"; exit 0; fi\nexit 97\n', encoding="utf-8",
    )
    (binaries / "python3").chmod(0o755)
    (binaries / "python3.14").write_text(
        f'#!/bin/sh\nif [ "$1" = "-c" ]; then printf "3.14.0\\n"; exit 0; fi\nexec "{os.environ["PYTHON"] if "PYTHON" in os.environ else __import__("sys").executable}" "$@"\n',
        encoding="utf-8",
    )
    (binaries / "python3.14").chmod(0o755)
    result = subprocess.run(
        [str(Path(__file__).parents[2] / "bin" / "adw-judge"), "status"],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
            "ADW_CLAUDE_SETTINGS": str(tmp_path / "settings.json"),
            "ADW_CLAUDE_PRESET_FILE": str(tmp_path / "preset"),
        }, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"preset": "haiku"' in result.stdout


def test_adw_judge_launcher_resolves_a_symlinked_install(tmp_path: Path) -> None:
    launcher = Path(__file__).parents[2] / "bin" / "adw-judge"
    link = tmp_path / "bin" / "adw-judge"
    link.parent.mkdir()
    link.symlink_to(launcher)
    result = subprocess.run(
        [str(link), "status"],
        env={
            **os.environ,
            "ADW_PYTHON": __import__("sys").executable,
            "HOME": str(tmp_path / "home"),
            "ADW_CLAUDE_SETTINGS": str(tmp_path / "settings.json"),
            "ADW_CLAUDE_PRESET_FILE": str(tmp_path / "preset"),
        }, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"preset": "haiku"' in result.stdout


def test_luna_failure_switches_to_role_fallback_once(tmp_path: Path) -> None:
    claude_native.set_preset("luna", settings_path=tmp_path / "settings.json", preset_path=tmp_path / "preset")

    result = claude_native.fallback_after_luna_failure(
        "comment", "subscription unavailable", settings_path=tmp_path / "settings.json", preset_path=tmp_path / "preset",
    )

    assert result["preset"] == "mixed"
    assert "subscription unavailable" in result["message"]
    assert claude_native.read_preset(tmp_path / "preset") == "mixed"


def test_concurrent_role_failures_serialize_to_one_consistent_fallback(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    start = threading.Barrier(3)

    def transition(role: str) -> dict:
        start.wait()
        return claude_native.fallback_after_luna_failure(
            role, "subscription unavailable", settings_path=settings, preset_path=preset,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(transition, role) for role in ("comment", "document")]
        start.wait()
        results = [future.result() for future in futures]

    selected = claude_native.read_preset(preset)
    configured = json.loads(settings.read_text(encoding="utf-8"))
    assert selected == "mixed"
    assert all(result["preset"] == selected for result in results)
    assert sum(result["switched"] is True for result in results) == 1
    handlers = [
        hook
        for groups in configured["hooks"].values()
        if isinstance(groups, list)
        for group in groups
        if isinstance(group, dict)
        for hook in group.get("hooks", [])
        if isinstance(hook, dict) and claude_native.MANAGED_MARKER in str(hook.get("prompt", ""))
    ]
    assert handlers
    assert {
        group_name: next(hook["model"] for hook in configured["hooks"][group_name][0]["hooks"] if hook.get("type") == "agent")
        for group_name in ("PostToolUse", "Stop")
    } == {"PostToolUse": "haiku", "Stop": "sonnet"}


def test_fallback_recovers_a_crash_between_settings_and_preset_replacements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    original = claude_native._atomic_write
    crashed = False

    def crash_before_preset(path: Path, text: str) -> None:
        nonlocal crashed
        if Path(path) == preset and not crashed:
            crashed = True
            raise RuntimeError("injected crash")
        original(path, text)

    monkeypatch.setattr(claude_native, "_atomic_write", crash_before_preset)
    with pytest.raises(RuntimeError, match="injected crash"):
        claude_native.fallback_after_luna_failure(
            "comment", "subscription unavailable", settings_path=settings, preset_path=preset,
        )
    monkeypatch.setattr(claude_native, "_atomic_write", original)

    status = claude_native.status(settings_path=settings, preset_path=preset)
    assert status["preset"] == "mixed"
    configured = json.loads(settings.read_text(encoding="utf-8"))
    managed = [
        hook
        for group in configured["hooks"].values()
        for row in group
        for hook in row.get("hooks", [])
        if isinstance(hook, dict) and hook.get("type") == "agent"
    ]
    assert managed
    assert {
        lifecycle: next(hook["model"] for hook in configured["hooks"][lifecycle][0]["hooks"] if hook.get("type") == "agent")
        for lifecycle in ("PostToolUse", "Stop")
    } == {"PostToolUse": "haiku", "Stop": "sonnet"}
    assert not preset.with_name(preset.name + ".txn").exists()


def test_corrupt_preset_transaction_is_removed_and_current_state_remains_usable(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    transaction = preset.with_name(preset.name + ".txn")
    transaction.write_text("not-json", encoding="utf-8")

    current = claude_native.status(settings_path=settings, preset_path=preset)

    assert current["preset"] == "luna"
    assert not transaction.exists()


@pytest.mark.parametrize("leaf_kind", ("directory", "symlink"))
def test_corrupt_transaction_leaf_is_quarantined_without_dos_or_target_deletion(
    tmp_path: Path, leaf_kind: str,
) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    transaction = preset.with_name(preset.name + ".txn")
    target = tmp_path / "transaction-target"
    if leaf_kind == "directory":
        transaction.mkdir()
        (transaction / "keep").write_text("do not delete", encoding="utf-8")
    else:
        target.write_text("do not delete", encoding="utf-8")
        transaction.symlink_to(target)

    current = claude_native.status(settings_path=settings, preset_path=preset)

    assert current["preset"] == "luna"
    assert not transaction.exists() and not transaction.is_symlink()
    quarantined = list(tmp_path.glob("preset.txn.corrupt-*"))
    assert len(quarantined) == 1
    assert target.read_text(encoding="utf-8") == "do not delete" if leaf_kind == "symlink" else True


def test_corrupt_transaction_quarantine_is_bounded_and_preserves_unrelated_leaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    monkeypatch.setattr(claude_native, "MAX_CORRUPT_QUARANTINES", 2, raising=False)
    monkeypatch.setattr(claude_native, "MAX_CORRUPT_QUARANTINE_BYTES", 10, raising=False)
    transaction = preset.with_name(preset.name + ".txn")
    for index in range(5):
        transaction.with_name(f"{transaction.name}{claude_native.CORRUPT_SUFFIX}{index:016x}").write_text(
            "0123456789", encoding="utf-8",
        )
    unrelated = tmp_path / "preset.txn.corrupt-not-owned"
    unrelated.write_text("preserve", encoding="utf-8")
    transaction.write_text("corrupt", encoding="utf-8")

    assert claude_native.status(settings_path=settings, preset_path=preset)["preset"] == "luna"
    quarantined = [
        item for item in tmp_path.iterdir()
        if item.name.startswith(transaction.name + claude_native.CORRUPT_SUFFIX)
        and item.name[-16:].isalnum()
    ]
    assert len(quarantined) <= 2
    assert sum(item.stat().st_size for item in quarantined if item.is_file()) <= 10
    assert unrelated.read_text(encoding="utf-8") == "preserve"


def test_preset_parent_symlink_is_rejected_without_following_target(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    settings = tmp_path / "settings.json"

    with pytest.raises((OSError, ValueError)):
        claude_native.set_preset(
            "luna", settings_path=settings, preset_path=alias_parent / "preset",
        )

    assert not (real_parent / "preset").exists()
    assert not settings.exists()


def test_symlinked_settings_leaf_is_updated_when_parent_chain_is_safe(tmp_path: Path) -> None:
    real_settings = tmp_path / "settings.json"
    settings_alias = tmp_path / "settings-alias.json"
    real_settings.write_text("{}", encoding="utf-8")
    settings_alias.symlink_to(real_settings)

    claude_native.set_preset(
        "luna", settings_path=settings_alias, preset_path=tmp_path / "preset",
    )

    assert settings_alias.is_symlink()
    assert json.loads(real_settings.read_text(encoding="utf-8"))["hooks"]["Stop"]


def test_settings_update_retries_after_external_regular_target_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    original = claude_native._atomic_write_regular_open
    mutated = False

    def mutate_before_replace(parent_fd: int, name: str, leaf: os.stat_result | None, text: str, **kwargs) -> None:
        nonlocal mutated
        if name == settings.name and not mutated:
            mutated = True
            settings.write_text(json.dumps({"external_setting": "keep me"}), encoding="utf-8")
        original(parent_fd, name, leaf, text, **kwargs)

    monkeypatch.setattr(claude_native, "_atomic_write_regular_open", mutate_before_replace)
    claude_native.set_preset("sonnet", settings_path=settings, preset_path=preset)

    configured = json.loads(settings.read_text(encoding="utf-8"))
    assert configured["external_setting"] == "keep me"
    assert configured["hooks"]["PostToolUse"][0]["hooks"][0]["model"] == "sonnet"


def test_descriptor_open_failure_does_not_leak_parent_fd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "preset"
    before = len(os.listdir("/dev/fd"))

    def fail_lstat(_parent_fd: int, _name: str):
        raise OSError("injected lstat failure")

    monkeypatch.setattr(claude_native, "_leaf_lstat", fail_lstat)
    with pytest.raises(OSError, match="injected lstat failure"):
        claude_native._atomic_write(target, "luna\n")

    after = len(os.listdir("/dev/fd"))
    assert after <= before


def test_transaction_symlink_and_embedded_settings_target_cannot_redirect_recovery(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    outside = tmp_path / "outside-settings.json"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    outside.write_text("outside", encoding="utf-8")
    transaction = preset.with_name(preset.name + ".txn")
    transaction.write_text(json.dumps({
        "version": 2,
        "preset": "mixed",
        "base_preset": "luna",
        "base_settings_hash": hashlib.sha256(settings.read_bytes()).hexdigest(),
        "settings_path": str(outside),
    }), encoding="utf-8")
    external = tmp_path / "external-transaction.json"
    external.write_text(transaction.read_text(encoding="utf-8"), encoding="utf-8")
    transaction.unlink()
    transaction.symlink_to(external)

    current = claude_native.status(settings_path=settings, preset_path=preset)

    assert current["preset"] == "luna"
    assert settings.read_text(encoding="utf-8") != "outside"
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not transaction.exists()


def test_regular_transaction_cannot_use_an_embedded_settings_path(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    outside = tmp_path / "outside-settings.json"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    outside.write_text("outside", encoding="utf-8")
    transaction = preset.with_name(preset.name + ".txn")
    transaction.write_text(json.dumps({
        "version": 2,
        "preset": "mixed",
        "base_preset": "luna",
        "base_settings_hash": hashlib.sha256(settings.read_bytes()).hexdigest(),
        "settings_path": str(outside),
    }), encoding="utf-8")

    current = claude_native.status(settings_path=settings, preset_path=preset)

    assert current["preset"] == "luna"
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not transaction.exists()


def test_preset_lock_symlink_is_not_followed(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    external = tmp_path / "external-lock"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    external.write_text("do not modify", encoding="utf-8")
    lock = preset.with_name(preset.name + ".lock")
    lock.unlink()
    lock.symlink_to(external)

    with pytest.raises(OSError):
        claude_native.status(settings_path=settings, preset_path=preset)
    assert external.read_text(encoding="utf-8") == "do not modify"


def test_recovery_merges_managed_hooks_onto_new_external_settings_and_is_idempotent(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    base_hash = hashlib.sha256(settings.read_bytes()).hexdigest()
    transaction = preset.with_name(preset.name + ".txn")
    transaction.write_text(json.dumps({
        "version": 2,
        "preset": "mixed",
        "base_preset": "luna",
        "base_settings_hash": base_hash,
    }), encoding="utf-8")
    changed = json.loads(settings.read_text(encoding="utf-8"))
    changed["external_setting"] = "keep me"
    settings.write_text(json.dumps(changed), encoding="utf-8")

    first = claude_native.status(settings_path=settings, preset_path=preset)
    first_text = settings.read_text(encoding="utf-8")
    second = claude_native.status(settings_path=settings, preset_path=preset)

    assert first["preset"] == second["preset"] == "mixed"
    assert json.loads(first_text)["external_setting"] == "keep me"
    assert settings.read_text(encoding="utf-8") == first_text
    assert not transaction.exists()


def test_recovery_discards_stale_intent_after_external_managed_hook_edit(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    transaction = preset.with_name(preset.name + ".txn")
    base_hash = hashlib.sha256(settings.read_bytes()).hexdigest()
    transaction.write_text(json.dumps({
        "version": 2,
        "preset": "mixed",
        "base_preset": "luna",
        "base_settings_hash": base_hash,
    }), encoding="utf-8")
    changed = json.loads(settings.read_text(encoding="utf-8"))
    changed["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = (
        f"ADW_CLAUDE_MANAGED={claude_native.MANAGED_MARKER} /external/new-handler"
    )
    settings.write_text(json.dumps(changed), encoding="utf-8")

    current = claude_native.status(settings_path=settings, preset_path=preset)

    assert current["preset"] == "luna"
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"][0]["command"].endswith("/external/new-handler")
    assert not transaction.exists()
    assert list(tmp_path.glob("preset.txn.corrupt-*"))
