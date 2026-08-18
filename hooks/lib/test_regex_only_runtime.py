"""Guard dead-runtime removal and force-key blindness with real execution, because a text grep only proves today's wording is absent, not that the behavior stayed gone."""
import subprocess
from pathlib import Path
from unittest import mock

import pre_commit
import pre_write
import record
from lib.scanner import scan_all as real_scan_all

ROOT = Path(__file__).resolve().parents[2]


def test_stop_runtime_is_removed():
    launcher = (ROOT / "hooks" / "run.sh").read_text()

    assert not (ROOT / "hooks" / "gate.py").exists()
    assert not (ROOT / "hooks" / "lib" / "ledger.py").exists()
    assert "run.sh Stop" not in launcher
    assert "skill-model-loader" not in launcher
    assert "SML_PYTHON" not in launcher


def test_model_jury_module_is_removed():
    assert not (ROOT / "hooks" / "lib" / "model_jury.py").exists()


def _strip_report_paths(value):
    """Blank the random tempfile path in a report line, because two separate runs never share that path even when every finding matches."""
    if isinstance(value, str):
        return "\n".join(
            "Full report: <path>" if line.startswith("Full report: ") else line
            for line in value.splitlines()
        )
    if isinstance(value, dict):
        return {key: _strip_report_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_report_paths(item) for item in value]
    return value


def _forced_scan(force_value):
    """Wrap the real scanner so a finding carries the given force value, because scan_all itself always emits True and offers no other way to vary it."""
    def scan(path, text, cfg):
        return [{**row, "force": force_value} for row in real_scan_all(path, text, cfg)]
    return scan


def _isolated_cfg(tmp_path: Path, label: str) -> dict:
    return {
        "state_root": str(tmp_path / f"state-{label}"),
        "ledger_root": str(tmp_path / f"ledger-{label}"),
    }


def _run_with_force_flipped(target: str, run_fn, make_payload):
    """Run one gate twice with only the finding's force value changed, because that isolates the single variable a source grep could never exercise."""
    with mock.patch(target, side_effect=_forced_scan(True)):
        forced = run_fn(make_payload(), "forced")
    with mock.patch(target, side_effect=_forced_scan(False)):
        unforced = run_fn(make_payload(), "unforced")
    return forced, unforced


def test_pre_write_decision_is_unaffected_by_the_force_key(tmp_path):
    """Run the real pre_write gate with force flipped, because a source grep for the key proves nothing once the check itself goes stale."""
    def make_payload():
        return {
            "cwd": str(tmp_path),
            "tool_input": {"file_path": "a.txt", "content": "bad" + chr(0x2014) + "dash\n"},
        }

    forced, unforced = _run_with_force_flipped(
        "pre_write.scan_all",
        lambda payload, label: pre_write.run(payload, _isolated_cfg(tmp_path, label)),
        make_payload,
    )

    assert forced.get("decision") == "block"
    assert _strip_report_paths(forced) == _strip_report_paths(unforced)


def test_record_decision_is_unaffected_by_the_force_key(tmp_path):
    """Run the real record gate with force flipped, because a source grep for the key proves nothing once the check itself goes stale."""
    target = tmp_path / "a.py"
    target.write_text("bad" + chr(0x2014) + "dash\n", encoding="utf-8")

    def make_payload():
        return {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_use_id": "toolu_1",
            "tool_input": {"file_path": str(target)},
        }

    forced, unforced = _run_with_force_flipped(
        "record.scan_all",
        lambda payload, label: record.run(payload, _isolated_cfg(tmp_path, label)),
        make_payload,
    )

    assert forced.get("decision") == "block"
    assert _strip_report_paths(forced) == _strip_report_paths(unforced)


def _staged_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "user.email", "gate@example.test"],
        ["config", "user.name", "Gate Test"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "notes.md").write_text("bad" + chr(0x2014) + "dash\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    return repo


def _run_commit(tmp_path: Path, payload: dict, label: str) -> dict:
    cfg = _isolated_cfg(tmp_path, label)
    return pre_commit.run(payload, None, ledger_root=cfg["ledger_root"], state_root=cfg["state_root"])


def test_pre_commit_decision_is_unaffected_by_the_force_key(tmp_path):
    """Run the real pre_commit gate with force flipped, because a source grep for the key proves nothing once the check itself goes stale."""
    repo = _staged_repo(tmp_path)

    def make_payload():
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "commit-force-session",
            "tool_name": "Bash",
            "tool_use_id": "toolu_commit",
            "tool_input": {"command": 'git commit -m "docs(x): add notes"'},
            "cwd": str(repo),
        }

    forced, unforced = _run_with_force_flipped(
        "pre_commit.scan_all",
        lambda payload, label: _run_commit(tmp_path, payload, label),
        make_payload,
    )

    assert forced.get("decision") == "block"
    assert _strip_report_paths(forced) == _strip_report_paths(unforced)
