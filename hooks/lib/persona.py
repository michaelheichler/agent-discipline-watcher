from __future__ import annotations

from pathlib import Path


PERSONA = Path(__file__).resolve().parents[1] / "persona.md"


def section(name: str) -> str:
    start = f"<!-- {name} START -->"
    end = f"<!-- {name} END -->"
    body = PERSONA.read_text(encoding="utf-8")
    head = body.find(start)
    tail = body.find(end)
    if head < 0 or tail < 0 or tail < head:
        return ""
    return body[head + len(start):tail].strip()
