"""Because detached workers outlive hooks, their process records must follow every exit path."""

from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from lib import luna_process, luna_worker, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from lib.luna_provider import CONFIG_OVERRIDES, LunaJudge, OpenAICodexSdk


def successful_run() -> int:
    return 19


def failing_run() -> int:
    raise RuntimeError("worker failure")


def terminated_run() -> int:
    signal.raise_signal(signal.SIGTERM)
    raise AssertionError("SIGTERM must interrupt worker execution")


@pytest.fixture
def registration(tmp_path: Path) -> tuple[dict, list]:
    events = []
    record = tmp_path / "worker.json"

    def register(role: str, *, state_root: object) -> Path:
        events.append(("register", role, state_root))
        return record

    def unregister(path: Path) -> None:
        events.append(("unregister", path))

    return {"register": register, "unregister": unregister, "state_root": tmp_path}, events


def test_successful_worker_unregisters_its_returned_record_once(registration: tuple) -> None:
    options, events = registration

    status = luna_worker.registered_main(run=successful_run, **options)

    assert status == 19
    root = options["state_root"]
    assert events == [("register", "luna-worker", root), ("unregister", root / "worker.json")]


@pytest.mark.parametrize("run, error", [(failing_run, RuntimeError), (terminated_run, SystemExit)])
def test_exception_and_sigterm_unregister_the_worker_record(registration: tuple, run, error) -> None:
    options, events = registration
    prior_handler = signal.getsignal(signal.SIGTERM)

    with pytest.raises(error):
        luna_worker.registered_main(run=run, **options)

    root = options["state_root"]
    assert events == [("register", "luna-worker", root), ("unregister", root / "worker.json")]
    assert signal.getsignal(signal.SIGTERM) == prior_handler


def test_registration_failure_prevents_worker_execution(tmp_path: Path, capsys) -> None:
    calls = []

    def register(role: str, *, state_root: object) -> Path:
        calls.append((role, state_root))
        raise OSError("record root unavailable")

    status = luna_worker.registered_main(run=lambda: calls.append("run"), register=register,
                                         unregister=lambda path: calls.append(path), state_root=tmp_path)

    assert status == 70
    assert calls == [("luna-worker", tmp_path)]
    assert json.loads(capsys.readouterr().out)["error"]["category"] == "configuration"


def test_worker_entrypoint_registers_before_decoding_input(tmp_path: Path) -> None:
    state_root = tmp_path / "not-a-directory"
    state_root.write_text("occupied", encoding="utf-8")
    environment = {**os.environ, "HOME": str(tmp_path), "ADW_PROCESS_STATE_ROOT": str(state_root)}

    result = subprocess.run([sys.executable, "-m", "lib.luna_worker"], input="not-json",
                            text=True, capture_output=True, cwd=Path(__file__).parents[1],
                            env=environment, check=False, timeout=10)

    assert result.returncode == 70
    assert json.loads(result.stdout)["error"]["category"] == "configuration"


def test_registered_worker_uses_the_shared_process_record_contract(tmp_path: Path) -> None:
    from lib import process_records

    seen = []

    def run() -> int:
        seen.extend(process_records.records(tmp_path))
        return 0

    status = luna_worker.registered_main(run=run, state_root=tmp_path)

    assert status == 0
    assert len(seen) == 1
    record = seen[0]
    assert record.pid == os.getpid()
    assert record.role == "luna-worker"
    assert record.argv0 == sys.executable
    assert record.process_start == process_records.process_start(os.getpid())
    assert record.adw_root == str(Path(__file__).resolve().parents[2])
    assert process_records.records(tmp_path) == []


def test_direct_worker_main_does_not_register_before_using_its_runner(
    tmp_path: Path, monkeypatch,
) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("ADW_PROCESS_STATE_ROOT", str(occupied))
    request = JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context="A clear sentence.")
    payload = {**asdict(request), "codex_home": str(tmp_path / "home"), "cwd": str(tmp_path),
               "config_overrides": list(CONFIG_OVERRIDES)}
    calls = []

    def run(received, launch) -> JudgeResult:
        calls.append((received, launch.cwd))
        return response_for(request)

    output = io.StringIO()
    with redirect_stdout(output):
        status = luna_worker.main(stdin=io.StringIO(json.dumps(payload)), run=run)

    assert status == 0
    assert calls == [(request, tmp_path)]
    assert json.loads(output.getvalue())["result"]["payload"] == {"notes": []}


def response_for(request: JudgeRequest) -> JudgeResult:
    return JudgeResult(payload={"notes": []}, provider="openai-codex", model="gpt-5.6-luna",
                       effort="high", rubric_version=request.rubric_version, usage={})


@pytest.fixture
def captured_worker(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.setenv("HOME", str(tmp_path))
    request = JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context="A clear sentence.")
    launches, exchanges = [], []

    @dataclass(frozen=True, slots=True)
    class Worker:
        returncode: int = 0

        def communicate(self, payload: str, *, timeout: float) -> tuple[str, None]:
            exchanges.append((json.loads(payload), timeout))
            return json.dumps({"ok": True, "result": asdict(response_for(request))}), None

    def launch(args, **options) -> Worker:
        launches.append((args, options))
        return Worker()

    monkeypatch.setattr(subprocess, "Popen", launch)
    judge = LunaJudge(sdk=OpenAICodexSdk(), runtime_root=tmp_path / "runtime",
                      cache_root=tmp_path / "cache", auth_source=tmp_path / "missing-auth")
    return {"judge": judge, "request": request, "launches": launches, "exchanges": exchanges}


def test_parent_state_root_reaches_only_the_worker_environment(captured_worker: dict) -> None:
    result = captured_worker["judge"].judge(captured_worker["request"])

    assert result.payload == {"notes": []}
    (command, options), = captured_worker["launches"]
    assert command[-2:] == ["-m", "lib.luna_worker"]
    environment = options["env"]
    assert environment["ADW_PROCESS_STATE_ROOT"] == str(session_state.plugin_data_home())
    assert "ADW_PROCESS_STATE_ROOT" not in luna_process.sdk_environment(environment)
    (sent, timeout), = captured_worker["exchanges"]
    assert sent["review_kind"] == captured_worker["request"].review_kind
    assert timeout > 0
