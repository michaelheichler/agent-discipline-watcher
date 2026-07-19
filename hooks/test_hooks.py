import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import gate
import pre_commit
import pre_write
import record
import session_start
from lib.ledger import read_ledger, record_findings


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


def test_pre_write_allows_css_semicolons_in_style_block():
    content = "\n".join([
        "<style>",
        "body { margin:0; color:#222; }",
        "</style>",
        "<p>visible prose stays scanned</p>",
        "",
    ])
    payload = {"tool_input": {"file_path": "board.html", "content": content}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path()})
    assert response == {}


def test_pre_write_still_denies_prose_splice_in_html_body():
    content = "<p>we run it; it works</p>"
    payload = {"tool_input": {"file_path": "a.html", "content": content}}
    response = pre_write.run(payload, {"ledger_path": _ledger_path()})
    assert response["decision"] == "block"
    assert "punctuation/semicolon_splice" in response["reason"]


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
    post_response = record.run({"tool_input": {"file_path": str(target)}}, cfg)
    assert post_response["decision"] == "block"
    assert "clean_code/deferred_work_comment" in post_response["reason"]
    assert len(read_ledger(cfg)) == 1
    response = gate.run({}, cfg)
    assert response["decision"] == "block"
    assert "clean_code/deferred_work_comment" in response["reason"]


def test_record_allows_clean_post_write(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    assert record.run({"tool_input": {"file_path": str(target)}}, cfg) == {}


def test_record_allows_advisory_post_write(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("I came home, I went to bed.\n", encoding="utf-8")
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    assert record.run({"tool_input": {"file_path": str(target)}}, cfg) == {}


def test_run_sh_blocks_forced_posttooluse(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("bad\u2014dash\n", encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "PostToolUse"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "punctuation/banned_dash" in result.stderr


def test_stop_does_not_apply_pah_empty_validator_gate():
    response = gate.run(
        {"last_assistant_message": "You are right. MD5 is fine."},
        {"ledger_path": _ledger_path()},
    )
    assert response == {}


def test_stop_does_not_apply_pah_flattery_gate():
    response = gate.run(
        {"last_assistant_message": "You're absolutely right. The cache can wait."},
        {"ledger_path": _ledger_path()},
    )
    assert response == {}


def test_stop_keeps_advisory_report_without_pah_block(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("I came home, I went to bed.", encoding="utf-8")
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    record_findings(str(note), [], cfg)
    response = gate.run({"last_assistant_message": "You are right. Ship it."}, cfg)
    assert "systemMessage" in response
    assert "Professional Agent Helper" not in response["systemMessage"]


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
    assert "Professional Agent Helper" not in response["systemMessage"]
    assert "agent-discipline-watcher: keep punctuation ASCII" in response["systemMessage"]


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


def test_run_sh_rejects_user_prompt_submit():
    payload = json.dumps({"prompt": "Add a cache to this function."})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "UserPromptSubmit"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "UserPromptSubmit" not in result.stderr


def _ledger_path():
    handle, path = tempfile.mkstemp(prefix="agent-discipline-watcher-test-", suffix=".json")
    os.close(handle)
    os.unlink(path)
    return path


@contextmanager
def _temporary_test_directory():
    path = Path(tempfile.mkdtemp(prefix="agent-discipline-watcher-test-"))
    try:
        yield path
    finally:
        _remove_temporary_tree(path)


def _remove_temporary_tree(path: Path) -> None:
    last_error = None
    for _ in range(30):
        try:
            shutil.rmtree(path, onexc=_reset_permissions)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            last_error = error
            time.sleep(0.1)
    if last_error is not None:
        raise last_error


def _reset_permissions(function, path, _exc_info):
    os.chmod(path, 0o700)
    function(path)


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
    with _temporary_test_directory() as directory:
        test_pre_commit_blocks_staged_forced_findings(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_allows_git_commit_as_argument(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_git_c_repo(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_cd_then_git_commit(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_pipeline_git_commit(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_command_wrapper(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_env_wrapper(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_grouped_cd_commit(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_all_commit_cwds(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_staged_blob_when_worktree_is_clean(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_ignores_dirty_worktree_when_staged_blob_is_clean(directory)
    with _temporary_test_directory() as directory:
        test_pre_commit_scans_from_repo_subdirectory(directory)
    with _temporary_test_directory() as directory:
        test_record_and_stop_share_one_ledger(directory)
    test_stop_does_not_apply_pah_empty_validator_gate()
    test_stop_does_not_apply_pah_flattery_gate()
    with _temporary_test_directory() as directory:
        test_stop_keeps_advisory_report_without_pah_block(directory)
    test_stop_allows_clean_direct_reply()
    test_stop_opener_ignores_later_quote()
    with _temporary_test_directory() as directory:
        test_session_start_clears_stale_ledger(directory)
    test_run_sh_routes_pretooluse()
    test_run_sh_routes_precommit_non_commit()
    test_run_sh_rejects_user_prompt_submit()
    with _temporary_test_directory() as directory:
        test_run_sh_selects_sibling_model_loader_python(directory)
