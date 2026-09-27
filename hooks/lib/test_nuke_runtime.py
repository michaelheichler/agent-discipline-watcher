from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import claude_cache, claude_presets, nuke_runtime


NAME = "agent-discipline-watcher"
PLUGIN_ID = f"{NAME}@{NAME}"
USER_GROUP = {"matcher": "Bash", "hooks": [{"type": "command", "command": "gitnexus"}]}
USER_TOML = 'model = "o3"\n\n[projects."/work"]\ntrust_level = "trusted"\n'
USER_RC = "export EDITOR=vim\nalias ll='ls -l'\n"
FENCE = "# >>> agent-discipline-watcher >>>\nexport PATH=\"$HOME/.adw/bin:$PATH\"\n# <<< agent-discipline-watcher <<<\n"
Env = dict[str, str]
Outcome = tuple[int, str, bool]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _link(path: Path, target: Path | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def _json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2) + "\n")


def _install(home: Path) -> Path:
    installed = home / ".adw/install" / NAME
    for relative in ("bin/adw", "bin/adw-judge", "bin/adw-nuke", "bin/agent-discipline", "skills/agent-discipline-watcher/SKILL.md",
                     "pi/extensions/agent-discipline-watcher/index.ts"):
        _write(installed / relative, "x\n")
    for relative in ("state/session.json", "ledger/rows.jsonl", "reports/turn.json", "models/embed.bin",
                     "runtime/codex/venv/pyvenv.cfg", "updates/installed.json", "update-marketplace/.claude-plugin/marketplace.json"):
        _write(home / ".adw" / relative, "{}\n")
    for name in ("adw", "adw-nuke", "adw-judge"):
        _link(home / ".adw/bin" / name, installed / "bin" / name)
    return installed


def _claude(home: Path, installed: Path) -> None:
    root = home / ".claude"
    managed = {"type": "command", "command": f"ADW_CLAUDE_MANAGED={claude_presets.MANAGED_MARKER} {installed}/hooks/claude_luna.sh"}
    legacy = {"type": "command", "command": f'"{installed}/hooks/run.sh" PreToolUse'}
    _json(root / "settings.json", {
        "hooks": {"PreToolUse": [USER_GROUP, {"hooks": [legacy]}], "Stop": [{"hooks": [managed]}]},
        "enabledPlugins": {PLUGIN_ID: True, "other@market": True}, "theme": "dark",
    })
    _json(root / "plugins/installed_plugins.json", {"version": 2, "plugins": {PLUGIN_ID: [{"scope": "user"}], "other@market": [{"scope": "user"}]}})
    _json(root / "plugins/known_marketplaces.json", {NAME: {"source": {"source": "directory"}}, "market": {"source": {}}})
    _write(root / "plugins/cache" / NAME / NAME / "abc123/hooks/run.sh", "x\n")
    _write(root / "plugins/marketplaces" / NAME / "README.md", "x\n")
    _write(root / "commands/adw/judge.md", "x\n")
    _link(root / "skills" / NAME, installed / "skills" / NAME)


def _codex(home: Path, installed: Path) -> None:
    codex = home / ".codex"
    watcher = {"hooks": [{"type": "command", "command": f'ADW_CODEX_HOOK=1 "{installed}/hooks/run.sh" Stop'}]}
    _json(codex / "hooks.json", {"hooks": {"Stop": [USER_GROUP, watcher], "SessionEnd": [watcher]}})
    block = f'# >>> {NAME} >>>\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype = "command"\ncommand = "run.sh Stop"\n# <<< {NAME} <<<\n'
    _write(codex / "config.toml", USER_TOML + "\n" + block)
    _write(codex / "skills" / NAME / "SKILL.md", "x\n")
    _write(codex / f"config.toml.{NAME}.bak.20260101000000", USER_TOML)
    _write(codex / f"hooks.json.{NAME}.bak.20260101000000", "{}\n")


def _omp_and_shell(home: Path, installed: Path) -> None:
    extension = installed / "pi/extensions" / NAME
    _json(home / ".omp/agent/settings.json", {"extensions": [str(extension / "index.ts"), "/opt/other/index.ts"], "model": "x"})
    _link(home / ".omp/agent/extensions" / NAME, extension)
    _link(home / ".agents/skills" / NAME, installed)
    for name in ("adw-judge", "agent-discipline"):
        _link(home / ".local/bin" / name, installed / "bin" / name)
    _link(home / ".local/bin/adw-cli", f"/old/{NAME}/bin/adw-cli")
    _write(home / ".zshrc", USER_RC + FENCE)
    _write(home / ".bashrc", FENCE + USER_RC)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    account = tmp_path / "account"
    account.mkdir()
    installed = _install(account)
    _claude(account, installed)
    _codex(account, installed)
    _omp_and_shell(account, installed)
    return account


def _steps(home: Path, environment: Env | None = None, run_claude=nuke_runtime._no_claude) -> nuke_runtime.NukeSteps:
    return nuke_runtime.NukeSteps(
        account_home=lambda: home, environment=lambda: dict(environment or {"PATH": ""}),
        claude_cache=claude_cache, without_managed=claude_presets.without_managed, run_claude=run_claude,
    )


def _tree(root: Path) -> dict[str, object]:
    rows: dict[str, object] = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in (*directories, *names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            rows[relative] = os.readlink(path) if path.is_symlink() else (path.read_bytes() if path.is_file() else "dir")
    return rows


def _expected_lines(home: Path) -> set[str]:
    edits = (".claude/plugins/installed_plugins.json", ".claude/plugins/known_marketplaces.json", ".claude/settings.json",
             ".codex/hooks.json", ".codex/config.toml", ".omp/agent/settings.json", ".zshrc", ".bashrc")
    removals = (
        ".local/bin/agent-discipline", ".local/bin/adw-cli", ".local/bin/adw-judge", f".codex/skills/{NAME}",
        f".omp/agent/extensions/{NAME}", f".agents/skills/{NAME}", f".claude/skills/{NAME}",
        f".claude/plugins/marketplaces/{NAME}", f".claude/plugins/cache/{NAME}", ".claude/commands/adw",
        f".codex/config.toml.{NAME}.bak.20260101000000", f".codex/hooks.json.{NAME}.bak.20260101000000", ".adw",
    )
    return {f"edit {home / path}" for path in edits} | {f"remove {home / path}" for path in removals}


def test_dry_run_lists_every_artifact_and_writes_nothing(home, capsys) -> None:
    before = _tree(home)
    assert nuke_runtime.main(["--dry-run"], steps=_steps(home)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert set(lines) == _expected_lines(home)
    assert lines[:2] == [f"edit {home}/.claude/plugins/installed_plugins.json", f"edit {home}/.claude/plugins/known_marketplaces.json"]
    assert lines[-1] == f"remove {home / '.adw'}"
    assert _tree(home) == before


def test_without_yes_prints_the_list_and_refuses(home, capsys) -> None:
    before = _tree(home)
    assert nuke_runtime.main([], steps=_steps(home)) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "Run again with --yes to remove them."
    assert set(lines[:-1]) == _expected_lines(home)
    assert _tree(home) == before


def test_yes_removes_every_artifact(home, capsys) -> None:
    assert nuke_runtime.main(["--yes"], steps=_steps(home)) == 0
    output = capsys.readouterr().out
    removed = [line.removeprefix("remove ") for line in _expected_lines(home) if line.startswith("remove ")]
    assert [path for path in removed if os.path.lexists(path)] == []
    assert output.rstrip().endswith("Restart Claude Code, Codex, and OMP, then run ./install.sh from a checkout.")
    assert output.split("\nEdited config files:")[0].splitlines()[-1] == f"removed {home / '.adw'}"
    assert nuke_runtime.main(["--dry-run"], steps=_steps(home)) == 0
    assert capsys.readouterr().out == "Nothing of ADW is left on this machine.\n"


def test_yes_keeps_every_foreign_entry(home) -> None:
    assert nuke_runtime.main(["--yes"], steps=_steps(home)) == 0
    settings = json.loads((home / ".claude/settings.json").read_text())
    assert settings == {"hooks": {"PreToolUse": [USER_GROUP]}, "enabledPlugins": {"other@market": True}, "theme": "dark"}
    assert json.loads((home / ".codex/hooks.json").read_text()) == {"hooks": {"Stop": [USER_GROUP]}}
    assert (home / ".codex/config.toml").read_text() == USER_TOML + "\n"
    omp = json.loads((home / ".omp/agent/settings.json").read_text())
    assert omp == {"extensions": ["/opt/other/index.ts"], "model": "x"}
    assert (home / ".zshrc").read_text() == USER_RC
    assert (home / ".bashrc").read_text() == USER_RC


def test_absent_claude_binary_edits_the_records_directly(home, capsys) -> None:
    assert nuke_runtime.main(["--yes"], steps=_steps(home)) == 0
    output = capsys.readouterr().out
    installed = json.loads((home / ".claude/plugins/installed_plugins.json").read_text())
    known = json.loads((home / ".claude/plugins/known_marketplaces.json").read_text())
    assert installed == {"version": 2, "plugins": {"other@market": [{"scope": "user"}]}}
    assert known == {"market": {"source": {}}}
    assert f"edited {home}/.claude/plugins/installed_plugins.json directly because the claude CLI is not installed" in output


def test_failed_claude_call_falls_back_to_the_json_edit(home, capsys) -> None:
    assert nuke_runtime.main(["--yes"], steps=_steps(home, run_claude=lambda arguments, environment: "failed")) == 0
    assert "directly because the claude CLI failed" in capsys.readouterr().out
    assert PLUGIN_ID not in (home / ".claude/plugins/installed_plugins.json").read_text()


def test_claude_cli_route_runs_first_without_the_session_marker(home, capsys) -> None:
    calls: list[tuple[list[str], Env]] = []

    def fake_claude(arguments: list[str], environment: Env) -> str:
        calls.append((arguments, environment))
        root = Path(environment["CLAUDE_CONFIG_DIR"])
        _json(root / "plugins/installed_plugins.json", {"version": 2, "plugins": {"other@market": [{"scope": "user"}]}})
        _json(root / "plugins/known_marketplaces.json", {"market": {"source": {}}})
        return "ok"

    environment = {"PATH": "", "CLAUDECODE": "1"}
    assert nuke_runtime.main(["--yes"], steps=_steps(home, environment, fake_claude)) == 0
    assert [arguments for arguments, _ in calls] == [["plugin", "uninstall", PLUGIN_ID], ["plugin", "marketplace", "remove", NAME]]
    assert all("CLAUDECODE" not in env and env["HOME"] == str(home) for _, env in calls)
    assert capsys.readouterr().out.splitlines()[0] == f"claude CLI removed the plugin records in {home / '.claude'}"


def test_run_claude_reports_an_absent_or_failing_binary(tmp_path) -> None:
    assert nuke_runtime.run_claude(["plugin"], {"PATH": str(tmp_path), "HOME": str(tmp_path)}) == "absent"
    fake = _write(tmp_path / "claude", "#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    assert nuke_runtime.run_claude(["plugin"], {"PATH": str(tmp_path), "HOME": str(tmp_path)}) == "failed"


def _run_refused(home: Path, capsys, environment: Env | None = None) -> Outcome:
    before = _tree(home)
    code = nuke_runtime.main(["--yes"], steps=_steps(home, environment))
    return code, capsys.readouterr().err, _tree(home) == before


def test_config_root_outside_home_stops_the_run(home, tmp_path, capsys) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    code, error, untouched = _run_refused(home, capsys, {"PATH": "", "CLAUDE_CONFIG_DIR": str(outside)})
    assert (code, untouched) == (2, True)
    assert f"outside the home directory: {outside}" in error


def test_symlinked_config_root_stops_the_run(home, tmp_path, capsys) -> None:
    real = tmp_path / "real-claude"
    real.mkdir()
    _link(home / ".config/claude-code", real)
    code, error, untouched = _run_refused(home, capsys)
    assert (code, untouched) == (2, True)
    assert f"refusing symlink path: {home / '.config/claude-code'}" in error


def test_foreign_link_at_a_link_path_stops_the_run(home, capsys) -> None:
    link = home / ".local/bin/adw-judge"
    link.unlink()
    link.symlink_to("/usr/bin/true")
    code, error, untouched = _run_refused(home, capsys)
    assert (code, untouched) == (2, True)
    assert f"refusing a foreign link path: {link}" in error


def test_symlinked_state_tree_stops_the_run(tmp_path, capsys) -> None:
    account = tmp_path / "account"
    real = tmp_path / "real-adw"
    _write(real / "state/session.json", "{}\n")
    _link(account / ".adw", real)
    code, error, untouched = _run_refused(account, capsys)
    assert (code, untouched) == (2, True)
    assert f"refusing symlink path: {account / '.adw'}" in error


def test_symlinked_edit_target_stops_the_run(home, tmp_path, capsys) -> None:
    dotfile = _write(tmp_path / "dotfiles/zshrc", USER_RC + FENCE)
    (home / ".zshrc").unlink()
    _link(home / ".zshrc", dotfile)
    code, error, untouched = _run_refused(home, capsys)
    assert (code, untouched) == (2, True)
    assert f"refusing symlink path: {home / '.zshrc'}" in error
    assert dotfile.read_text() == USER_RC + FENCE


def test_a_home_below_a_symlinked_parent_is_wiped(tmp_path, capsys) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _link(tmp_path / "linked", real)
    account = tmp_path / "linked/account"
    account.mkdir()
    _claude(account, _install(account))
    assert nuke_runtime.main(["--yes"], steps=_steps(account)) == 0, capsys.readouterr().err
    assert PLUGIN_ID not in (account / ".claude/plugins/installed_plugins.json").read_text()
    assert not (account / ".adw").exists()


def test_an_open_rc_fence_is_left_alone() -> None:
    text = USER_RC + "# >>> agent-discipline-watcher >>>\nexport X=1\n"
    assert nuke_runtime.strip_rc_block(text) == text


@pytest.mark.parametrize("arguments", [["--dry-run", "--yes"], ["--force"], ["--ye"]])
def test_only_one_of_the_two_flags_is_accepted(arguments, tmp_path) -> None:
    with pytest.raises(SystemExit) as error:
        nuke_runtime.main(arguments, steps=_steps(tmp_path))
    assert error.value.code == 2


def test_yes_removes_a_read_only_luna_sandbox(home, capsys) -> None:
    sandbox = home / ".adw" / "runtime" / "luna-0d49"
    (sandbox / "cwd").mkdir(parents=True)
    (sandbox / "cwd" / "call.json").write_text("{}", encoding="utf-8")
    (sandbox / "cwd").chmod(0o500)
    sandbox.chmod(0o500)
    assert nuke_runtime.main(["--yes"], steps=_steps(home)) == 0
    assert not (home / ".adw").exists()
    assert f"removed {home / '.adw'}" in capsys.readouterr().out
