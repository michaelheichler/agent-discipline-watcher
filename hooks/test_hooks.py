import json
import os
import subprocess
import tempfile
from pathlib import Path

import gate
import pre_commit
import pre_write
import prompt_inject
import record
import session_start
from lib.ledger import read_ledger, record_findings
from lib.correction import is_correction
from lib.persona import section


def _disable_git_background_tasks() -> None:
    config = {
        "maintenance.auto": "false",
        "gc.auto": "0",
        "core.fsmonitor": "false",
    }
    try:
        offset = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        offset = 0
    for index, (key, value) in enumerate(config.items(), start=offset):
        os.environ[f"GIT_CONFIG_KEY_{index}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{index}"] = value
    os.environ["GIT_CONFIG_COUNT"] = str(offset + len(config))


_disable_git_background_tasks()


def test_pre_write_denies_forced_pending_write():
    payload = {"tool_input": {"file_path": "a.txt", "content": "bad\u2014dash"}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path()})
    assert response["decision"] == "block"
    assert "punctuation/banned_dash" in response["reason"]


def test_pre_write_denies_plain_english_violation():
    payload = {"tool_input": {"file_path": "a.txt", "content": "util" + "ize"}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path(), "english": True})
    assert response["decision"] == "block"
    assert "english/utilize" in response["reason"]


def test_pre_write_denies_clean_code_violation():
    payload = {"tool_input": {"file_path": "a.py", "content": "# " + ("TO" + "DO") + " later"}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path(), "clean_code": True})
    assert response["decision"] == "block"
    assert "clean_code/deferred_work_comment" in response["reason"]


def test_pre_write_denies_prose_comment_block():
    payload = {"tool_input": {"file_path": "a.py", "content": "# first line\n# second line\nprint(1)\n"}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path(), "clean_code": True})
    assert response["decision"] == "block"
    assert "clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_allows_non_commit_bash():
    response = pre_commit.run({"tool_input": {"command": "git status"}})
    assert response == {}


def test_pre_commit_blocks_staged_forced_findings(tmp_path):
    _git(tmp_path, "init")
    target = tmp_path / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]
    assert "Create one or update" in response["reason"]


def test_pre_commit_allows_git_commit_as_argument(tmp_path):
    _git(tmp_path, "init")
    target = tmp_path / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "echo git commit"}})
    assert response == {}


def test_pre_commit_scans_git_c_repo(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    _git(clean, "init")
    _git(dirty, "init")
    target = dirty / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(dirty, "add", "a.py")
    response = pre_commit.run({"cwd": str(clean), "tool_input": {"command": f"git -C {dirty} commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_cd_then_git_commit(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    _git(clean, "init")
    _git(dirty, "init")
    target = dirty / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(dirty, "add", "a.py")
    response = pre_commit.run({"cwd": str(clean), "tool_input": {"command": f"cd {dirty} && git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_pipeline_git_commit(tmp_path):
    _git(tmp_path, "init")
    _stage_bad_python(tmp_path)
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "printf x | git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_command_wrapper(tmp_path):
    _git(tmp_path, "init")
    _stage_bad_python(tmp_path)
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "command git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_env_wrapper(tmp_path):
    _git(tmp_path, "init")
    _stage_bad_python(tmp_path)
    command = "env -i GIT_AUTHOR_NAME=x git commit -m test"
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": command}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_grouped_cd_commit(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    _git(clean, "init")
    _git(dirty, "init")
    _stage_bad_python(dirty)
    response = pre_commit.run({"cwd": str(clean), "tool_input": {"command": f"(cd {dirty} && git commit -m test)"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_all_commit_cwds(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    _git(clean, "init")
    _git(dirty, "init")
    _stage_bad_python(dirty)
    command = f"git -C {clean} commit --allow-empty -m empty; git -C {dirty} commit -m test"
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": command}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_scans_staged_blob_when_worktree_is_clean(tmp_path):
    _git(tmp_path, "init")
    target = tmp_path / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    target.write_text("print(1)\n", encoding="utf-8")
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_pre_commit_ignores_dirty_worktree_when_staged_blob_is_clean(tmp_path):
    _git(tmp_path, "init")
    target = tmp_path / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    response = pre_commit.run({"cwd": str(tmp_path), "tool_input": {"command": "git commit -m test"}})
    assert response == {}


def test_pre_commit_scans_from_repo_subdirectory(tmp_path):
    _git(tmp_path, "init")
    subdir = tmp_path / "pkg"
    subdir.mkdir()
    target = tmp_path / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    response = pre_commit.run({"cwd": str(subdir), "tool_input": {"command": "git commit -m test"}})
    assert response["decision"] == "block"
    assert "a.py:1 clean_code/prose_comment_block" in response["reason"]


def test_record_and_stop_share_one_ledger(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    record.run({"tool_input": {"file_path": str(target)}}, cfg)
    assert len(read_ledger(cfg)) == 1
    response = gate.run({}, cfg)
    assert response["decision"] == "block"
    assert "clean_code/deferred_work_comment" in response["reason"]


def test_stop_blocks_pah_empty_validator():
    response = gate.run(
        {"last_assistant_message": "You are right. MD5 is fine."},
        {"ledger_path": _ledger_path()},
    )
    assert response["decision"] == "block"
    assert "Professional Agent Helper" in response["reason"]
    assert "empty validator" in response["reason"]


def test_stop_blocks_pah_flattery():
    response = gate.run(
        {"last_assistant_message": "You're absolutely right. The cache can wait."},
        {"ledger_path": _ledger_path()},
    )
    assert response["decision"] == "block"
    assert "reflexive flattery" in response["reason"]


def test_stop_pah_block_keeps_advisory_report(tmp_path):
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    record_findings(
        "note.md",
        [{"family": "english", "rule": "maybe", "line": 1, "force": False, "action": "Review wording."}],
        cfg,
    )
    response = gate.run({"last_assistant_message": "You are right. Ship it."}, cfg)
    assert response["decision"] == "block"
    assert "Professional Agent Helper" in response["reason"]
    assert "advisory findings in full report" in response["reason"]
    assert "Full report:" in response["reason"]


def test_stop_allows_clean_direct_reply():
    response = gate.run(
        {"last_assistant_message": "MD5 is wrong for passwords. Use Argon2."},
        {"ledger_path": _ledger_path()},
    )
    assert response == {}


def test_stop_opener_ignores_later_quote():
    response = gate.run(
        {"last_assistant_message": "MD5 is wrong for passwords.\n\n> You are right."},
        {"ledger_path": _ledger_path()},
    )
    assert response == {}


def test_session_start_clears_stale_ledger(tmp_path):
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    Path(cfg["ledger_path"]).write_text(json.dumps([{"path": "old", "findings": [{}]}]), encoding="utf-8")
    response = session_start.run({}, cfg)
    assert read_ledger(cfg) == []
    assert "systemMessage" in response
    assert "Professional Agent Helper" in response["systemMessage"]
    assert "Verify before you claim" in response["systemMessage"]
    assert "agent-discipline-watcher: keep punctuation ASCII" in response["systemMessage"]


def test_persona_sections_are_present():
    assert "Professional Agent Helper" in section("CHARTER")
    assert "Probe before you agree" in section("REFLEX")
    assert "correcting or challenging" in section("NUDGE")
    assert "Weak:" in section("CHARTER")
    assert "Strong:" in section("CHARTER")


def test_prompt_inject_emits_reflex_without_nudge_on_neutral():
    response = prompt_inject.run({"prompt": "Add a cache to this function."})
    context = response["hookSpecificOutput"]["additionalContext"]
    assert response["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Probe before you agree" in context
    assert "correcting or challenging" not in context


def test_prompt_inject_appends_nudge_on_correction():
    response = prompt_inject.run({"prompt": "But what about cache invalidation?"})
    context = response["hookSpecificOutput"]["additionalContext"]
    assert "Probe before you agree" in context
    assert "correcting or challenging" in context


def test_correction_detects_english_and_german_cues():
    for text in (
        "But what about cache invalidation?",
        "Are you sure?",
        "Actually, the timeout is 30s.",
        "Aber was ist mit dem Cache?",
        "Bist du sicher?",
        "Das ist falsch.",
        "Ich glaube nicht.",
        "Warum hast du das gemacht?",
    ):
        assert is_correction(text)
    assert not is_correction("Add a cache to this function.")


def test_run_sh_routes_pretooluse():
    payload = json.dumps({"tool_input": {"file_path": "a.txt", "content": "util" + "ize"}})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "PreToolUse"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout)["decision"] == "block"


def test_run_sh_routes_precommit_non_commit():
    payload = json.dumps({"tool_input": {"command": "git status"}})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "PreCommit"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {}


def test_run_sh_routes_user_prompt_submit():
    payload = json.dumps({"prompt": "Add a cache to this function."})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "UserPromptSubmit"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Probe before you agree" in output["hookSpecificOutput"]["additionalContext"]


def test_run_sh_selects_sibling_model_loader_python(tmp_path):
    skills_root = tmp_path / "skills"
    fake_python = skills_root / "skill-model-loader" / ".venv" / "bin" / "python"
    marker = tmp_path / "selected.txt"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$0\" > \"$ADW_TEST_MARKER\"\n"
        "printf '%s\\n' \"$1\" >> \"$ADW_TEST_MARKER\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.pop("SML_PYTHON", None)
    env["ADW_SKILLS_ROOT"] = str(skills_root)
    env["ADW_TEST_MARKER"] = str(marker)
    subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "Stop"],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    selected, script = marker.read_text(encoding="utf-8").splitlines()
    assert selected == str(fake_python)
    assert script == str(Path(__file__).parent / "gate.py")


def _ledger_path():
    handle, path = tempfile.mkstemp(prefix="agent-discipline-watcher-test-", suffix=".json")
    os.close(handle)
    os.unlink(path)
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def _stage_bad_python(cwd: Path) -> None:
    target = cwd / "a.py"
    target.write_text("# first line\n# second line\nprint(1)\n", encoding="utf-8")
    _git(cwd, "add", "a.py")


if __name__ == "__main__":
    test_pre_write_denies_forced_pending_write()
    test_pre_write_denies_plain_english_violation()
    test_pre_write_denies_clean_code_violation()
    test_pre_write_denies_prose_comment_block()
    test_pre_commit_allows_non_commit_bash()
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_blocks_staged_forced_findings(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_allows_git_commit_as_argument(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_git_c_repo(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_cd_then_git_commit(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_pipeline_git_commit(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_command_wrapper(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_env_wrapper(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_grouped_cd_commit(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_all_commit_cwds(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_staged_blob_when_worktree_is_clean(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_ignores_dirty_worktree_when_staged_blob_is_clean(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_pre_commit_scans_from_repo_subdirectory(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_record_and_stop_share_one_ledger(Path(directory))
    test_stop_blocks_pah_empty_validator()
    test_stop_blocks_pah_flattery()
    with tempfile.TemporaryDirectory() as directory:
        test_stop_pah_block_keeps_advisory_report(Path(directory))
    test_stop_allows_clean_direct_reply()
    test_stop_opener_ignores_later_quote()
    with tempfile.TemporaryDirectory() as directory:
        test_session_start_clears_stale_ledger(Path(directory))
    test_persona_sections_are_present()
    test_prompt_inject_emits_reflex_without_nudge_on_neutral()
    test_prompt_inject_appends_nudge_on_correction()
    test_correction_detects_english_and_german_cues()
    test_run_sh_routes_pretooluse()
    test_run_sh_routes_precommit_non_commit()
    test_run_sh_routes_user_prompt_submit()
    with tempfile.TemporaryDirectory() as directory:
        test_run_sh_selects_sibling_model_loader_python(Path(directory))
