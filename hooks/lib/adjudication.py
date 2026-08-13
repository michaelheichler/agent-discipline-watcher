"""Bounded semantic adjudication for scanner findings that rules cannot decide safely."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, TypedDict

try:
    from . import session_state
except ImportError:
    import session_state

AMBIGUOUS_RULES = frozenset({"what_comment", "what_docstring", "weak_why_comment"})
ENV_VAR = "ADW_HAIKU_ADJUDICATOR"
RUBRIC_VERSION = "1"
SCANNER_VERSION = "1"
SOURCE_CAP = 1200
OUTPUT_CAP = 2000
CLIENT_HOOK_DEADLINE_SECONDS = 30
TIMEOUT_MARGIN_SECONDS = 5
TIMEOUT_SECONDS = CLIENT_HOOK_DEADLINE_SECONDS - TIMEOUT_MARGIN_SECONDS
CACHE_FIELD = "adjudication_cache"


class Request(NamedTuple):
    rule: str
    path: str
    line: int
    source: str
    context: str
    rubric_version: str
    scanner_version: str
    content_hash: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "source": self.source,
            "context": self.context,
            "rubric_version": self.rubric_version,
            "scanner_version": self.scanner_version,
            "content_hash": self.content_hash,
        }


class Result(TypedDict):
    verdict: str
    evidence: str
    reason: str


Adjudicator = Callable[[Request], object]


def request_for(finding: dict, text: str, source_line: int | None = None) -> Request:
    line = finding.get("line") if isinstance(finding.get("line"), int) else 0
    anchor = source_line if isinstance(source_line, int) and source_line > 0 else line
    lines = text.splitlines()
    start = max(anchor - 3, 0)
    end = min(anchor + 2, len(lines))
    source = "\n".join(lines[start:end])[:SOURCE_CAP]
    return Request(
        rule=str(finding.get("rule") or ""),
        path=str(finding.get("path") or "<pending>"),
        line=line,
        source=source,
        context=f"lines {start + 1}-{end}",
        rubric_version=RUBRIC_VERSION,
        scanner_version=SCANNER_VERSION,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def configured_adjudicator(config: dict) -> Adjudicator:
    supplied = config.get("adjudicator")
    if callable(supplied):
        return supplied
    executable = os.environ.get(ENV_VAR, "")
    path = Path(executable)
    if not executable or not path.is_absolute() or not path.is_file():
        raise RuntimeError("Haiku adjudicator is not configured")
    return lambda request: _run_executable(path, request)


def adjudicate(request: Request, runner: Adjudicator) -> Result:
    return _validate(runner(request), request)


def cache_identity(request: Request) -> str:
    return json.dumps(
        {
            "scanner_version": request.scanner_version,
            "rubric_version": request.rubric_version,
            "content_hash": request.content_hash,
            "rule": request.rule,
            "line": request.line,
            "source_span": request.context,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def cached_result(
    request: Request,
    session_id: str,
    state_root: str | os.PathLike[str] | None,
) -> Result | None:
    if not session_id:
        return None
    state = session_state.read_state(session_id, state_root)
    cache = state.get(CACHE_FIELD)
    if not isinstance(cache, dict):
        return None
    value = cache.get(cache_identity(request))
    if value is None:
        return None
    return _validate(value, request)


def store_result(
    request: Request,
    result: Result,
    session_id: str,
    state_root: str | os.PathLike[str] | None,
) -> None:
    if not session_id:
        return
    key = cache_identity(request)

    def update(state: dict) -> dict:
        current = state.get(CACHE_FIELD)
        cache = dict(current) if isinstance(current, dict) else {}
        cache[key] = dict(result)
        return {**state, CACHE_FIELD: cache}

    session_state.update_state(session_id, update, state_root)


def adjudicate_with_cache(
    request: Request,
    runner: Adjudicator,
    session_id: str,
    state_root: str | os.PathLike[str] | None,
) -> Result:
    existing = cached_result(request, session_id, state_root)
    if existing is not None:
        return existing
    result = adjudicate(request, runner)
    store_result(request, result, session_id, state_root)
    return result


def filter_cached_releases(
    findings: list[dict],
    text: str,
    session_id: str,
    state_root: str | os.PathLike[str] | None,
) -> list[dict]:
    if not session_id:
        return list(findings)
    retained: list[dict] = []
    for finding in findings:
        if finding.get("rule") not in AMBIGUOUS_RULES:
            retained.append(finding)
            continue
        request = request_for(finding, text)
        try:
            result = cached_result(request, session_id, state_root)
        except Exception:
            retained.append(finding)
            continue
        if result is None or result["verdict"] == "block":
            retained.append(finding)
    return retained


def _run_executable(path: Path, request: Request) -> object:
    raw = json.dumps(request.to_dict(), ensure_ascii=True, separators=(",", ":"))
    try:
        completed = subprocess.run(
            [str(path)], input=raw, text=True, capture_output=True, check=True,
            timeout=TIMEOUT_SECONDS, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Haiku adjudicator failed: {exc}") from exc
    if len(completed.stdout.encode("utf-8")) > OUTPUT_CAP:
        raise ValueError("Haiku adjudicator output exceeded the size limit")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Haiku adjudicator returned invalid JSON") from exc


def _validate(value: object, request: Request) -> Result:
    if not isinstance(value, dict) or set(value) != {"verdict", "evidence", "reason"}:
        raise ValueError("Haiku adjudicator returned an invalid response shape")
    verdict = value.get("verdict")
    evidence = value.get("evidence")
    reason = value.get("reason")
    if verdict not in {"block", "release"}:
        raise ValueError("Haiku adjudicator returned an invalid verdict")
    if not isinstance(evidence, str) or not evidence or evidence not in request.source:
        raise ValueError("Haiku adjudicator evidence does not match the bounded source")
    if not isinstance(reason, str) or not reason or len(reason) > 300:
        raise ValueError("Haiku adjudicator returned an invalid reason")
    return {"verdict": verdict, "evidence": evidence, "reason": reason}
