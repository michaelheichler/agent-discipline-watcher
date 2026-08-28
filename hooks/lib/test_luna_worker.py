from __future__ import annotations

import json
import io
import subprocess
import sys
from pathlib import Path
from contextlib import redirect_stdout

import pytest

from lib import luna_worker
from lib.luna_provider import CONFIG_OVERRIDES


def _request_payload(tmp_path: Path) -> dict[str, object]:
    return {
        "review_kind": "pattern",
        "candidates": ["candidate"],
        "source_context": "",
        "rule_name": "named-pattern",
        "rule_action": "remove it",
        "violating_examples": [],
        "clean_examples": [],
        "rubric_version": "adw-rubric-v1",
        "codex_home": str(tmp_path / "home"),
        "cwd": str(tmp_path / "cwd"),
        "config_overrides": list(CONFIG_OVERRIDES),
    }


def _run_main(monkeypatch, payload: object, execute) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(luna_worker.sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(luna_worker, "execute", execute)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        status = luna_worker.main()
    return status, json.loads(stdout.getvalue())


def test_worker_rejects_an_invalid_protocol_request(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "lib.luna_worker"], input="not-json", text=True,
        capture_output=True, cwd=Path(__file__).parents[1], check=False,
    )

    body = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert body == {
        "ok": False,
        "error": {"category": "request", "message": "invalid Luna worker request"},
    }


@pytest.mark.parametrize(
    ("error_name", "category"),
    (
        ("ServerBusyError", "overload"),
        ("RetryLimitExceededError", "overload"),
        ("TransportClosedError", "transport"),
        ("JsonRpcError", "sdk"),
    ),
)
def test_worker_encodes_expected_sdk_failures_as_typed_bounded_errors(
    tmp_path: Path, monkeypatch, error_name: str, category: str,
) -> None:
    error_type = type(error_name, (RuntimeError,), {})

    def fail(_request, _launch):
        raise error_type("provider stderr detail\n" + "x" * 2000)

    status, body = _run_main(monkeypatch, _request_payload(tmp_path), fail)

    assert status != 0
    assert body["ok"] is False
    assert body["error"]["category"] == category
    assert "provider stderr detail" not in body["error"]["message"]
    assert len(body["error"]["message"]) <= 256


def test_worker_converts_unknown_base_exception_to_bounded_internal_error(
    tmp_path: Path, monkeypatch,
) -> None:
    def fail(_request, _launch):
        raise KeyboardInterrupt("sensitive unknown detail" + "x" * 2000)

    status, body = _run_main(monkeypatch, _request_payload(tmp_path), fail)

    assert status != 0
    assert body == {
        "ok": False,
        "error": {"category": "internal", "message": "Luna worker failed internally"},
    }
