from __future__ import annotations

import sys
from pathlib import Path

from lib import payloads
from lib.hookio import PARSE_FAILURE, read_payload
from lib.judge import Verdict, judge
from lib.narration_candidates import candidates
from lib.pattern_semantic import Finding
from lib.pattern_semantic import scan as scan_patterns

JUDGED_SUFFIXES = (".py",)
PROSE_SUFFIXES = (".md",)
WAKE_EXIT_CODE = 2
MAX_CANDIDATES = 40


def _target(payload: object, suffixes: tuple[str, ...]) -> Path | None:
    raw = payloads.file_path(payload)
    if not raw:
        return None
    path = Path(raw)
    if path.suffix not in suffixes or not path.is_file():
        return None
    return path


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _pattern_message(findings: tuple[Finding, ...]) -> str:
    blocking = [item for item in findings if item.blocking]
    lead = (
        "agent-discipline-watcher blocked findings:" if blocking
        else "agent-discipline-watcher is observing these, not blocking."
    )
    lines = [lead]
    lines.extend(
        f"{item.rule}:{item.line}: {item.text[:120]}" + ("" if item.blocking else " (observed)")
        for item in findings
    )
    return "\n".join(lines)


def _pattern_findings(payload: object) -> tuple[Finding, ...]:
    """Swallows every failure because an absent model server must cost the write nothing at all."""
    path = _target(payload, PROSE_SUFFIXES)
    if path is None:
        return ()
    text = _read(path)
    if text is None:
        return ()
    try:
        return scan_patterns(str(path), text)
    except Exception:
        return ()


def _message(verdicts: tuple[Verdict, ...]) -> str:
    lines = [
        "agent-discipline-watcher: these comments describe the code instead of stating why.",
        "Rewrite each as one short WHY line, or delete it.",
    ]
    lines.extend(
        f"{item.candidate.path}:{item.candidate.line}: {item.candidate.text[:120]} ({item.reason})"
        for item in verdicts
    )
    return "\n".join(lines)


def _comment_message(payload: object) -> str:
    path = _target(payload, JUDGED_SUFFIXES)
    if path is None:
        return ""
    text = _read(path)
    if text is None:
        return ""
    verdicts = judge(candidates(str(path), text)[:MAX_CANDIDATES])
    narrating = tuple(item for item in verdicts if item.narrates) if verdicts else ()
    return _message(narrating) if narrating else ""


def run(payload: object) -> tuple[int, str]:
    if payload is PARSE_FAILURE:
        return 0, ""
    findings = _pattern_findings(payload)
    messages = [message for message in (_comment_message(payload),) if message]
    if findings:
        messages.append(_pattern_message(findings))
    if not messages:
        return 0, ""
    return WAKE_EXIT_CODE, "\n".join(messages)


if __name__ == "__main__":
    code, message = run(read_payload())
    if message:
        print(message, file=sys.stderr)
    sys.exit(code)
