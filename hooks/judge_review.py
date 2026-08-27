from __future__ import annotations

import sys
from pathlib import Path

from lib import payloads
from lib.hookio import PARSE_FAILURE, read_payload
from lib.judge import Verdict, judge
from lib.narration_candidates import candidates

JUDGED_SUFFIXES = (".py",)
WAKE_EXIT_CODE = 2
MAX_CANDIDATES = 40


def _target(payload: object) -> Path | None:
    raw = payloads.file_path(payload)
    if not raw:
        return None
    path = Path(raw)
    if path.suffix not in JUDGED_SUFFIXES or not path.is_file():
        return None
    return path


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


def run(payload: object) -> tuple[int, str]:
    if payload is PARSE_FAILURE:
        return 0, ""
    path = _target(payload)
    if path is None:
        return 0, ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0, ""
    found = candidates(str(path), text)[:MAX_CANDIDATES]
    verdicts = judge(found)
    if not verdicts:
        return 0, ""
    narrating = tuple(item for item in verdicts if item.narrates)
    if not narrating:
        return 0, ""
    return WAKE_EXIT_CODE, _message(narrating)


if __name__ == "__main__":
    code, message = run(read_payload())
    if message:
        print(message, file=sys.stderr)
    sys.exit(code)
