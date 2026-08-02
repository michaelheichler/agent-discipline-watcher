import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import hookio
import pre_commit
import pre_write
import record
import session_start


WHAT_COMMENT_ACTION = (
    "Only WHY comments are allowed. WHAT comments are never allowed. "
    "State the reason the code is this way, or delete the comment."
)


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


def _edit_config(tmp_path):
    return {"ledger_path": _ledger_path(), "clean_code": True, "baseline": "none"}


def test_pre_write_maps_edit_finding_to_post_edit_line(tmp_path):
    target = tmp_path / "large.py"
    target.write_text("".join(f"value_{index} = {index}\n" for index in range(120)), encoding="utf-8")
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "old_string": "value_49 = 49\n",
                         "new_string": "# Validate the cache entry\nvalue_49 = 49\n"}},
        _edit_config(tmp_path),
    )
    assert response["decision"] == "block"
    assert f"{target}:50 clean_code/what_comment" in response["reason"]


def test_pre_write_edit_ignores_preexisting_debt(tmp_path):
    target = tmp_path / "legacy.py"
    target.write_text("# Validate the old entry\nvalue = 1\n", encoding="utf-8")
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "old_string": "value = 1\n", "new_string": "value = 2\n"}},
        _edit_config(tmp_path),
    )
    assert response == {}


def test_pre_write_maps_multiedit_findings_to_each_post_edit_line(tmp_path):
    target = tmp_path / "multi.py"
    target.write_text("".join(f"value_{index} = {index}\n" for index in range(120)), encoding="utf-8")
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "edits": [
            {"old_string": "value_19 = 19\n", "new_string": "# Validate the first entry\nvalue_19 = 19\n"},
            {"old_string": "value_79 = 79\n", "new_string": "# Validate the second entry\nvalue_79 = 79\n"},
        ]}},
        _edit_config(tmp_path),
    )
    assert response["decision"] == "block"
    assert f"{target}:20 clean_code/what_comment" in response["reason"]
    assert f"{target}:81 clean_code/what_comment" in response["reason"]


def test_pre_write_edit_keeps_hollow_test_finding_anchored_on_unchanged_line(tmp_path):
    target = tmp_path / "hollow.py"
    target.write_text("def test_case():\n    value = 1\n    assert value\n", encoding="utf-8")
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "old_string": "    assert value\n", "new_string": ""}},
        _edit_config(tmp_path),
    )
    assert response["decision"] == "block"
    assert f"{target}:1 clean_code/hollow_test" in response["reason"]


def test_pre_write_edit_keeps_file_length_finding_anchored_on_unchanged_line(tmp_path):
    target = tmp_path / "long.py"
    target.write_text("".join(f"value_{index} = {index}\n" for index in range(991)), encoding="utf-8")
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "old_string": "value_990 = 990\n",
                         "new_string": "value_990 = 990\n" + "value_added = 1\n" * 10}},
        _edit_config(tmp_path),
    )
    assert response["decision"] == "block"
    assert f"{target}:1 clean_code/file_too_long" in response["reason"]


def test_pre_write_edit_fallback_labels_pending_edit_text(tmp_path):
    target = tmp_path / "missing.py"
    response = pre_write.run(
        {"tool_input": {"file_path": str(target), "old_string": "not present\n",
                         "new_string": "# Validate the cache entry\n"}},
        _edit_config(tmp_path),
    )
    assert response["decision"] == "block"
    report_path = response["reason"].rsplit("Full report: ", 1)[1]
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert "pending edit text" in report[0]["detail"]


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


WHAT_PAYLOAD = {"tool_input": {"file_path": "a.py", "content": "# Validate the cache entry\nvalidate()\n"}}


def test_pre_write_enforces_what_comment_by_default():
    response = pre_write.run(WHAT_PAYLOAD, {"ledger_path": _ledger_path(), "clean_code": True})
    assert response["decision"] == "block"
    assert "clean_code/what_comment" in response["reason"]
    assert WHAT_COMMENT_ACTION in response["reason"]


def test_pre_write_blocks_what_comment_once_the_rule_is_enforced():
    config = {"ledger_path": _ledger_path(), "clean_code": True,
              "rule_gates": {"what_comment": "enforce"}}
    response = pre_write.run(WHAT_PAYLOAD, config)
    assert response["decision"] == "block"
    assert "clean_code/what_comment" in response["reason"]


def test_pre_write_allows_a_why_comment():
    why_payload = {
        "tool_input": {
            "file_path": "a.py",
            "content": "# Keep this check because stale entries break ordering\nvalidate()\n",
        }
    }
    assert pre_write.run(why_payload, {"ledger_path": _ledger_path(), "clean_code": True}) == {}


def test_what_comment_survives_the_clean_code_switch_and_path_exemption():
    disabled_and_exempt = {
        "ledger_path": _ledger_path(),
        "clean_code": False,
        "exempt_paths": ["a.py"],
    }
    response = pre_write.run(WHAT_PAYLOAD, disabled_and_exempt)
    assert response["decision"] == "block"
    assert "clean_code/what_comment" in response["reason"]


def test_pre_write_enforces_vue_comment_contract():
    config = {"ledger_path": _ledger_path(), "clean_code": True}
    two_comments = {
        "tool_input": {
            "file_path": "component.vue",
            "content": (
                "// Keep the fallback because old clients omit the field\n"
                "// Preserve the default because empty values are valid\n"
                "const value = fallback\n"
            ),
        }
    }
    response = pre_write.run(two_comments, config)
    assert response["decision"] == "block"
    assert "clean_code/prose_comment_block" in response["reason"]

    one_comment = {
        "tool_input": {
            "file_path": "component.vue",
            "content": "// Keep the fallback because old clients omit the field\nconst value = fallback\n",
        }
    }
    assert pre_write.run(one_comment, config) == {}


def test_pre_write_allows_comment_exemptions_and_css_selectors():
    cases = [
        ("script.py", "#!/usr/bin/env python3\nprint(1)\n"),
        (
            "script.py",
            "# SPDX-FileCopyrightText: 2026 Example\n# SPDX-License-Identifier: MIT\n# coding: utf-8\nprint(1)\n",
        ),
        ("Dockerfile", "# syntax=docker/dockerfile:1\nFROM scratch\n"),
        ("Dockerfile", "# escape=`\nFROM scratch\n"),
        ("Dockerfile", "# check=skip=JSONArgsRecommended\nFROM scratch\n"),
        ("script.py", "# noqa: E501\nprint(1)\n"),
        ("script.py", "# type: ignore\nprint(1)\n"),
        ("script.py", "# pragma: no cover\nprint(1)\n"),
        ("script.py", "# ruff: noqa\nprint(1)\n"),
        ("script.py", "# fmt: off\nprint(1)\n"),
        ("script.js", "# eslint-disable-next-line\nrun()\n"),
        ("script.ts", "// @ts-expect-error\nrun()\n"),
        ("component.vue", "<style>\n#app { color: #222; }\n.widget { color: red; }\n</style>\n"),
    ]
    for path, content in cases:
        payload = {"tool_input": {"file_path": path, "content": content}}
        assert pre_write.run(payload, {"ledger_path": _ledger_path()}) == {}, (path, content)


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
    assert "punctuation/prose_semicolon" in response["reason"]


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


def test_record_blocks_forced_post_write(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
    post_response = record.run({"tool_input": {"file_path": str(target)}})
    assert post_response["decision"] == "block"
    assert "clean_code/deferred_work_comment" in post_response["reason"]


def test_record_allows_clean_post_write(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    assert record.run({"tool_input": {"file_path": str(target)}}, cfg) == {}


def test_record_ignores_uncertain_punctuation(tmp_path):
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


def test_session_start_injects_policy():
    response = session_start.run({})
    assert "systemMessage" in response
    assert "Professional Agent Helper" not in response["systemMessage"]
    assert "agent-discipline-watcher: keep punctuation ASCII" in response["systemMessage"]


def test_session_start_reaches_the_model_channel():
    injected = session_start.run({})["hookSpecificOutput"]
    assert injected["hookEventName"] == "SessionStart"
    assert injected["additionalContext"].startswith(hookio.CONTRACT)
    assert session_start.READABLE_OUTPUT_HEADING in injected["additionalContext"]
    assert "override the agent definition" in injected["additionalContext"]
    assert "Professional Agent Helper" not in injected["additionalContext"]


def test_read_payload_parses_good_input():
    result = subprocess.run(
        [sys.executable, "-c", "from lib.hookio import read_payload; print(read_payload()['a'])"],
        input='{"a": 7}', text=True, capture_output=True, cwd=str(Path(__file__).parent), check=True,
    )
    assert result.stdout.strip() == "7"


def test_read_payload_fails_soft_on_malformed_input():
    result = subprocess.run(
        [sys.executable, "-c", "from lib.hookio import read_payload; print(read_payload())"],
        input="{not json", text=True, capture_output=True, cwd=str(Path(__file__).parent), check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "{}"
    assert result.stderr.strip().startswith("agent-discipline-watcher: unreadable hook payload")
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr


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


def test_run_sh_routes_user_prompt_submit_to_the_firewall():
    payload = json.dumps({"prompt": "Add a cache to this function."})
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "UserPromptSubmit"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout or "{}").get("decision") != "block"


def test_run_sh_routes_stop_to_the_stop_gate():
    result = subprocess.run(
        [str(Path(__file__).parent / "run.sh"), "Stop"],
        input="{}",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout or "{}").get("decision") != "block"


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
