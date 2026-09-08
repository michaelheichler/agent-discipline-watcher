from pathlib import Path

import pytest

import pre_write


@pytest.fixture
def wired_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".codex" / "config.toml"
    target.parent.mkdir()
    target.write_text(
        'model = "gpt-6-astra"\n'
        'hook_command = "agent-discipline-watcher/hooks/run.sh"\n'
        'model_reasoning_effort = "low"\n'
        '\n[projects."/tmp/verification"]\ntrust_level = "trusted"\n',
        encoding="utf-8",
    )
    return target


def patch_findings(target: Path, patch: str, listed=False):
    tool_input = {"command": ["apply_patch", patch]} if listed else {"patch": patch}
    decoded = pre_write._decode(tool_input)
    findings, _ = pre_write._pending_findings(
        decoded, target.parent.parent, {"baseline": "none"},
    )
    return {finding["rule"] for finding in findings}


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("listed", [False, True])
def test_patch_preserves_wiring_across_multiple_hunks(wired_config, relative, listed):
    target = ".codex/config.toml" if relative else str(wired_config)
    patch = (
        f"*** Begin Patch\n*** Update File: {target}\n@@\n"
        '-model = "gpt-6-astra"\n+model = "gpt-6-sol"\n'
        '@@\n-model_reasoning_effort = "low"\n'
        '+model_reasoning_effort = "medium"\n*** End Patch\n'
    )

    assert "watcher_wiring_removal" not in patch_findings(wired_config, patch, listed)


def test_deletion_only_patch_preserves_wiring(wired_config):
    patch = (
        f"*** Begin Patch\n*** Update File: {wired_config}\n@@\n"
        '-[projects."/tmp/verification"]\n-trust_level = "trusted"\n'
        "*** End Patch\n"
    )

    assert "watcher_wiring_removal" not in patch_findings(wired_config, patch)


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("listed", [False, True])
def test_patch_removing_wiring_is_blocked(wired_config, relative, listed):
    target = ".codex/config.toml" if relative else str(wired_config)
    patch = (
        f"*** Begin Patch\n*** Update File: {target}\n@@\n"
        '-hook_command = "agent-discipline-watcher/hooks/run.sh"\n'
        "*** End Patch\n"
    )

    assert "watcher_wiring_removal" in patch_findings(wired_config, patch, listed)


@pytest.mark.parametrize("listed", [False, True])
def test_patch_moving_wired_config_is_blocked(wired_config, listed):
    patch = (
        f"*** Begin Patch\n*** Update File: {wired_config}\n"
        f"*** Move to: {wired_config}.old\n@@\n"
        '-model = "gpt-6-astra"\n+model = "gpt-6-sol"\n*** End Patch\n'
    )
    assert "watcher_wiring_removal" in patch_findings(wired_config, patch, listed)


def test_patch_overwriting_wired_destination_is_blocked(wired_config):
    source = wired_config.parent / "other.toml"
    source.write_text('model = "gpt-6-astra"\n', encoding="utf-8")
    patch = (
        f"*** Begin Patch\n*** Update File: {source}\n"
        f"*** Move to: {wired_config}\n@@\n"
        '-model = "gpt-6-astra"\n+model = "gpt-6-sol"\n*** End Patch\n'
    )
    assert "watcher_wiring_removal" in patch_findings(wired_config, patch)


def test_unmatched_patch_does_not_clear_protection(wired_config):
    patch = (
        f"*** Begin Patch\n*** Update File: {wired_config}\n@@\n"
        '-missing = true\n+model = "gpt-6-sol"\n*** End Patch\n'
    )
    assert "watcher_wiring_removal" in patch_findings(wired_config, patch)
