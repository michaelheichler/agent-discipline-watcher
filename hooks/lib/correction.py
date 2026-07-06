from __future__ import annotations

import re


PATTERNS = [
    r"\bbut what about\b",
    r"\bwhat about\b",
    r"\bare you sure\b",
    r"\byou sure\b",
    r"\bthat'?s (?:not|wrong|incorrect)\b",
    r"\bthat is (?:not|wrong|incorrect)\b",
    r"\bthis is (?:not|wrong|incorrect)\b",
    r"\bi (?:don'?t|do not) think\b",
    r"\bi disagree\b",
    r"\bi doubt\b",
    r"\bisn'?t (?:it|that|this)\b",
    r"\bdoesn'?t (?:it|that|this)\b",
    r"\bwouldn'?t (?:it|that|this)\b",
    r"\bshouldn'?t (?:it|that|this)\b",
    r"\byou (?:said|claimed|wrote|told me)\b",
    r"\bwhy (?:did|would) you\b",
    r"\bactually\b",
    r"\breally\?",
    r"^\s*(?:no|nope|wrong)[,.! ]",
    r"^\s*(?:wait|hold on)\b",
    r"\baber was ist mit\b",
    r"\bbist du sicher\b",
    r"\bstimmt das\b",
    r"\bstimmt (?:nicht|doch nicht)\b",
    r"\bdas ist falsch\b",
    r"\bdas stimmt nicht\b",
    r"\bich glaube nicht\b",
    r"\bich denke nicht\b",
    r"\bich bezweifle\b",
    r"\bdu hast (?:gesagt|geschrieben)\b",
    r"\bwarum hast du\b",
    r"\beigentlich\b",
    r"\bwirklich\?",
    r"^\s*(?:nein|falsch)[,.! ]",
    r"^\s*(?:moment|warte)\b",
]

RX = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in PATTERNS]


def is_correction(text: object) -> bool:
    return isinstance(text, str) and bool(text.strip()) and any(rx.search(text) for rx in RX)
