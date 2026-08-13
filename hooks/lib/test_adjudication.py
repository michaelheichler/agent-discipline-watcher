import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import adjudication


def _request():
    return adjudication.request_for(
        {"rule": "what_comment", "path": "a.py", "line": 2},
        "value = 1\n# Validate the cache\nvalidate()\n",
    )


def test_request_is_bounded_and_content_addressed() -> None:
    request = _request()

    assert request.rule == "what_comment"
    assert request.path == "a.py"
    assert request.line == 2
    assert len(request.source) <= adjudication.SOURCE_CAP
    assert len(json.dumps(request.to_dict())) < 2_000
    assert len(request.content_hash) == 64


def test_strict_result_accepts_matching_evidence() -> None:
    result = adjudication.adjudicate(
        _request(),
        lambda _request: {
            "verdict": "block",
            "evidence": "# Validate the cache",
            "reason": "The comment narrates the next call.",
        },
    )

    assert result["verdict"] == "block"


@pytest.mark.parametrize("result", [
    {"verdict": "block", "evidence": "missing", "reason": "x"},
    {"verdict": "maybe", "evidence": "# Validate the cache", "reason": "x"},
    {"verdict": "release", "evidence": "# Validate the cache", "reason": "x", "extra": "x"},
])
def test_strict_result_rejects_malformed_output(result) -> None:
    with pytest.raises(ValueError):
        adjudication.adjudicate(_request(), lambda _request: result)


def test_cache_identity_is_semantic_not_hook_or_tool_identity() -> None:
    request = _request()
    equivalent = adjudication.Request(
        rule=request.rule,
        path=request.path,
        line=request.line,
        source=request.source,
        context=request.context,
        rubric_version=request.rubric_version,
        scanner_version=request.scanner_version,
        content_hash=request.content_hash,
    )

    assert adjudication.cache_identity(request) == adjudication.cache_identity(equivalent)


def test_cache_identity_changes_for_content_rule_and_source_span() -> None:
    request = _request()
    changed_content = adjudication.request_for(
        {"rule": request.rule, "path": request.path, "line": request.line},
        "value = 1\n# Validate the changed cache\nvalidate()\n",
    )
    changed_rule = adjudication.Request(
        rule="weak_why_comment",
        path=request.path,
        line=request.line,
        source=request.source,
        context=request.context,
        rubric_version=request.rubric_version,
        scanner_version=request.scanner_version,
        content_hash=request.content_hash,
    )
    changed_span = adjudication.Request(
        rule=request.rule,
        path=request.path,
        line=request.line + 1,
        source=request.source,
        context="lines 2-4",
        rubric_version=request.rubric_version,
        scanner_version=request.scanner_version,
        content_hash=request.content_hash,
    )

    keys = {
        adjudication.cache_identity(request),
        adjudication.cache_identity(changed_content),
        adjudication.cache_identity(changed_rule),
        adjudication.cache_identity(changed_span),
    }
    assert len(keys) == 4


def test_cached_result_round_trips_in_session_state(tmp_path: Path) -> None:
    request = _request()
    result = {
        "verdict": "release",
        "evidence": "# Validate the cache",
        "reason": "The comment records a constraint.",
    }

    adjudication.store_result(request, result, "session-1", tmp_path)

    assert adjudication.cached_result(request, "session-1", tmp_path) == result


def test_adjudicator_timeout_keeps_margin_under_client_deadline(tmp_path: Path) -> None:
    request = _request()
    executable = tmp_path / "adjudicator"
    executable.write_text("", encoding="utf-8")

    seen: dict[str, object] = {}

    def timed_run(*args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    with mock.patch.object(adjudication.subprocess, "run", timed_run):
        with pytest.raises(RuntimeError, match="Haiku adjudicator failed"):
            adjudication._run_executable(executable, request)

    assert seen["timeout"] == adjudication.TIMEOUT_SECONDS
    assert adjudication.TIMEOUT_SECONDS + adjudication.TIMEOUT_MARGIN_SECONDS == adjudication.CLIENT_HOOK_DEADLINE_SECONDS
    assert adjudication.TIMEOUT_SECONDS <= 25
