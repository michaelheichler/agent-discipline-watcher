from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from lib import luna_provider
from lib.judge_contracts import JudgeRequest, ReviewKind
from lib.luna_provider import LunaJudge, LunaProviderFailure, OpenAICodexSdk


SUCCESS = {
    "ok": True,
    "result": {
        "payload": {"items": [{"index": 0, "verdict": "clean", "reason": "specific"}]},
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "effort": "high",
        "rubric_version": "adw-rubric-v1",
        "usage": {"total_tokens": 7},
        "cached": False,
    },
}


def _request() -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.PATTERN,
        candidates=("candidate",),
        rule_name="named-pattern",
        rule_action="remove it",
    )


def _worker_script(tmp_path: Path, source: str) -> Path:
    script = tmp_path / "controlled-worker.py"
    script.write_text(
        f"#!{sys.executable}\n" + textwrap.dedent(source), encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def _judge(tmp_path: Path, monkeypatch, source: str) -> LunaJudge:
    script = _worker_script(tmp_path, source)
    monkeypatch.setattr(luna_provider.sys, "executable", str(script))
    return LunaJudge(
        sdk=OpenAICodexSdk(),
        runtime_root=tmp_path / "runtime",
        cache_root=tmp_path / "cache",
        auth_source=tmp_path / "missing-auth.json",
    )


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_until_gone(pid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.01)
    return not _is_process_alive(pid)


def _kill_if_alive(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_worker_spawn_time_consumes_the_single_parent_deadline(tmp_path: Path, monkeypatch) -> None:
    judge = _judge(tmp_path, monkeypatch, f"""
        import json
        import sys
        sys.stdin.read()
        print({json.dumps(json.dumps(SUCCESS))})
    """)
    real_popen = subprocess.Popen

    def delayed_popen(*args, **kwargs):
        time.sleep(0.08)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(luna_provider.subprocess, "Popen", delayed_popen)
    monkeypatch.setattr(luna_provider, "JUDGE_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(LunaProviderFailure, match="timed out"):
        judge.judge(_request())


@pytest.mark.parametrize("stage", ("startup", "sdk-run", "close"))
def test_parent_deadline_covers_each_worker_stage(
    tmp_path: Path, monkeypatch, stage: str,
) -> None:
    marker = tmp_path / f"{stage}.marker"
    before_read = f"Path({str(marker)!r}).write_text('startup')" if stage == "startup" else ""
    after_read = f"Path({str(marker)!r}).write_text({stage!r})" if stage != "startup" else ""
    judge = _judge(tmp_path, monkeypatch, f"""
        from pathlib import Path
        import sys
        import time
        {before_read}
        {'sys.stdin.read()' if stage != 'startup' else ''}
        {after_read}
        time.sleep(30)
    """)
    monkeypatch.setattr(luna_provider, "JUDGE_TIMEOUT_SECONDS", 0.5)

    with pytest.raises(LunaProviderFailure, match="timed out"):
        judge.judge(_request())

    # Startup may legitimately not run before a deadline that includes spawn;
    # sdk-run and close still prove the worker reached each later stage.
    if stage != "startup":
        assert marker.exists()


def test_base_exception_after_spawn_terminates_and_reaps_worker(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "pid"
    judge = _judge(tmp_path, monkeypatch, f"""
        from pathlib import Path
        import os
        import sys
        import time
        Path({str(marker)!r}).write_text(str(os.getpid()))
        sys.stdin.read()
        time.sleep(30)
    """)
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen] = []

    def interrupting_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)

        def interrupted_communicate(*_args, **_kwargs):
            deadline = time.monotonic() + 1
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            raise KeyboardInterrupt("controlled interruption")

        process.communicate = interrupted_communicate
        return process

    monkeypatch.setattr(luna_provider.subprocess, "Popen", interrupting_popen)

    try:
        with pytest.raises(KeyboardInterrupt, match="controlled interruption"):
            judge.judge(_request())

        assert processes[0].returncode is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(processes[0].pid, os.WNOHANG)
    finally:
        if processes and processes[0].poll() is None:
            os.killpg(processes[0].pid, signal.SIGKILL)
            processes[0].wait()


def test_timeout_kills_descendants_even_when_group_leader_exits_on_term(
    tmp_path: Path, monkeypatch,
) -> None:
    child_marker = tmp_path / "child-pid"
    judge = _judge(tmp_path, monkeypatch, f"""
        from pathlib import Path
        import signal
        import subprocess
        import sys
        import time
        child = subprocess.Popen(
            [sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        Path({str(child_marker)!r}).write_text(str(child.pid))
        sys.stdin.read()
        time.sleep(30)
    """)
    monkeypatch.setattr(luna_provider, "JUDGE_TIMEOUT_SECONDS", 0.5)
    child_pid = -1

    try:
        with pytest.raises(LunaProviderFailure, match="timed out"):
            judge.judge(_request())
        child_pid = int(child_marker.read_text())
        assert _wait_until_gone(child_pid)
    finally:
        if child_pid > 0:
            _kill_if_alive(child_pid)


def test_malformed_worker_exit_terminates_its_remaining_process_group(
    tmp_path: Path, monkeypatch,
) -> None:
    child_marker = tmp_path / "malformed-child-pid"
    judge = _judge(tmp_path, monkeypatch, f"""
        from pathlib import Path
        import subprocess
        import sys
        child = subprocess.Popen(
            [sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        Path({str(child_marker)!r}).write_text(str(child.pid))
        sys.stdin.read()
        print('not-json')
    """)
    child_pid = -1

    try:
        with pytest.raises(LunaProviderFailure, match="malformed"):
            judge.judge(_request())
        child_pid = int(child_marker.read_text())
        assert _wait_until_gone(child_pid)
    finally:
        if child_pid > 0:
            _kill_if_alive(child_pid)


def test_term_exit_race_still_reaps_the_worker(tmp_path: Path, monkeypatch) -> None:
    judge = _judge(tmp_path, monkeypatch, """
        import signal
        import sys
        import time
        signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
        sys.stdin.read()
        time.sleep(30)
    """)
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen] = []

    def recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(luna_provider.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(luna_provider, "JUDGE_TIMEOUT_SECONDS", 0.5)

    with pytest.raises(LunaProviderFailure, match="timed out"):
        judge.judge(_request())

    assert processes[0].returncode is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(processes[0].pid, os.WNOHANG)


def test_parent_preserves_typed_worker_error_without_stderr(tmp_path: Path, monkeypatch) -> None:
    judge = _judge(tmp_path, monkeypatch, """
        import json
        import sys
        sys.stdin.read()
        sys.stderr.write('credential-shaped stderr must stay hidden')
        print(json.dumps({
            'ok': False,
            'error': {'category': 'transport', 'message': 'Luna SDK transport failed'},
        }))
        raise SystemExit(70)
    """)

    with pytest.raises(LunaProviderFailure) as caught:
        judge.judge(_request())

    assert caught.value.category == "transport"
    assert str(caught.value) == "Luna SDK transport failed"
    assert "credential-shaped" not in str(caught.value)


def test_successful_worker_exit_is_not_signalled(tmp_path: Path, monkeypatch) -> None:
    judge = _judge(tmp_path, monkeypatch, f"""
        import sys
        sys.stdin.read()
        print({json.dumps(json.dumps(SUCCESS))})
    """)
    signals: list[tuple[int, int]] = []
    real_killpg = os.killpg

    def recording_killpg(process_group: int, sent_signal: int) -> None:
        signals.append((process_group, sent_signal))
        real_killpg(process_group, sent_signal)

    monkeypatch.setattr(luna_provider.os, "killpg", recording_killpg)

    result = judge.judge(_request())

    assert result.payload["items"][0]["verdict"] == "clean"
    assert signals == []


def test_runtime_leaves_cannot_be_swapped_into_external_worker_markers(
    tmp_path: Path, monkeypatch,
) -> None:
    outside_cwd = tmp_path / "outside-cwd"
    outside_home = tmp_path / "outside-home"
    outside_cwd.mkdir()
    outside_home.mkdir()
    judge = _judge(tmp_path, monkeypatch, f"""
        import json
        import os
        from pathlib import Path
        import sys

        from lib.luna_worker import _decode_request, _prepare_descriptor_launch

        request = json.loads(sys.stdin.read())
        try:
            _request, launch = _decode_request(request)
            _prepare_descriptor_launch(launch)
            if launch.cwd_fd is None:
                Path("cwd.marker").write_text("worker cwd", encoding="utf-8")
                Path(os.environ["CODEX_HOME"], "home.marker").write_text(
                    "worker home", encoding="utf-8",
                )
            else:
                with os.fdopen(os.open(
                    "cwd.marker", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=launch.cwd_fd,
                ), "w", encoding="utf-8") as marker:
                    marker.write("worker cwd")
                with os.fdopen(os.open(
                    "home.marker", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=launch.codex_home_fd,
                ), "w", encoding="utf-8") as marker:
                    marker.write("worker home")
            print({json.dumps(json.dumps(SUCCESS))})
        except BaseException as exc:
            print(json.dumps({{
                "ok": False,
                "error": {{"category": getattr(exc, "category", "configuration"), "message": str(exc)}},
            }}))
    """)
    real_popen = subprocess.Popen

    def swap_runtime_leaves_before_spawn(*args, **kwargs):
        call_dirs = list((tmp_path / "runtime").iterdir())
        assert len(call_dirs) == 1
        call_dir = call_dirs[0]
        os.chmod(call_dir, 0o700)
        (call_dir / "cwd").rename(tmp_path / "displaced-cwd")
        (call_dir / "cwd").symlink_to(outside_cwd, target_is_directory=True)
        (call_dir / "home").rename(tmp_path / "displaced-home")
        (call_dir / "home").symlink_to(outside_home, target_is_directory=True)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(luna_provider.subprocess, "Popen", swap_runtime_leaves_before_spawn)

    with pytest.raises(LunaProviderFailure, match="runtime descriptor"):
        judge.judge(_request())

    assert not (outside_cwd / "cwd.marker").exists()
    assert not (outside_home / "home.marker").exists()
    assert not tuple((tmp_path / "displaced-cwd").iterdir())
    assert not tuple((tmp_path / "displaced-home").iterdir())
    assert not tuple((tmp_path / "runtime").iterdir())
