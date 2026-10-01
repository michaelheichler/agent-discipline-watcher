from __future__ import annotations

import json
import io
import subprocess
import sys
from pathlib import Path
from contextlib import redirect_stdout
from typing import NoReturn

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


def _run_main(payload: object, execute) -> tuple[int, dict[str, object]]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        status = luna_worker.main(stdin=io.StringIO(json.dumps(payload)), run=execute)
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
def test_worker_encodes_expected_sdk_failures_as_typed_bounded_errors(tmp_path: Path, error_name: str, category: str) -> None:
    error_type = type(error_name, (RuntimeError,), {})

    def fail(_request, _launch) -> NoReturn:
        raise error_type("provider stderr detail\n" + "x" * 2000)

    status, body = _run_main(_request_payload(tmp_path), fail)

    assert status != 0
    assert body["ok"] is False
    assert body["error"]["category"] == category
    assert "provider stderr detail" not in body["error"]["message"]
    assert len(body["error"]["message"]) <= 256


def test_worker_converts_unknown_base_exception_to_bounded_internal_error(tmp_path: Path) -> None:
    def fail(_request, _launch) -> NoReturn:
        raise KeyboardInterrupt("sensitive unknown detail" + "x" * 2000)

    status, body = _run_main(_request_payload(tmp_path), fail)

    assert status != 0
    assert body == {
        "ok": False,
        "error": {"category": "internal", "message": "Luna worker failed internally"},
    }


@pytest.mark.parametrize(("sent", "expected"), ((None, ""), ("Meldet ein Passiv.", "Meldet ein Passiv.")))
def test_worker_hands_the_rule_definition_to_the_judge(tmp_path: Path, sent: str | None, expected: str) -> None:
    payload = _request_payload(tmp_path)
    if sent is not None:
        payload["rule_definition"] = sent
    seen = []

    def capture(request, _launch) -> NoReturn:
        seen.append(request.rule_definition)
        raise KeyboardInterrupt

    _run_main(payload, capture)

    assert seen == [expected]
