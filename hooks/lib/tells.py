from __future__ import annotations

import re


OPENER = "opener"
ANYWHERE = "anywhere"

TELLS = [
    (r"you(?:'re| are) (?:absolutely|totally|completely|so|100%) right", ANYWHERE, "reflexive flattery"),
    (r"you(?:'re| are) not wrong", ANYWHERE, "reflexive concession"),
    (r"i stand corrected", ANYWHERE, "reflexive concession"),
    (r"you(?:'re| are) right", OPENER, "empty validator"),
    (r"(?:great|good|excellent) question", OPENER, "warm-up filler"),
    (r"(?:good|great|valid|fair) point", OPENER, "concession filler"),
    (r"good catch", OPENER, "concession filler"),
    (r"fair (?:enough|call)", OPENER, "patronizing concession"),
    (r"absolutely[!.]", OPENER, "reflexive agreement"),
    (r"(?:i apologi[sz]e|i'm sorry|my apologies) for the confusion", ANYWHERE, "apology hedge"),
    (r"(?:i )?hope (?:this|that) helps", ANYWHERE, "closing filler"),
]

LEAD = re.compile(r"^[\s>#*_`\"'(-]+")


def _strip_lead(line: str) -> str:
    return LEAD.sub("", line)


def _first_answer_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(">") or stripped.startswith("```"):
            continue
        return line
    return ""


def scan_tells(text: object) -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        return []
    lines = text.splitlines()
    findings = []
    seen = set()
    for pattern, scope, rule in TELLS:
        if rule in seen:
            continue
        regex = re.compile(pattern, re.IGNORECASE)
        match = None
        if scope == ANYWHERE:
            match = regex.search(text)
        else:
            match = regex.match(_strip_lead(_first_answer_line(lines)))
        if match:
            seen.add(rule)
            findings.append({"rule": rule, "snippet": match.group(0)})
    return findings
