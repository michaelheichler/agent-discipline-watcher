"""Deterministic unproved-done rule for turn-end assistant messages."""
from __future__ import annotations

import re

FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
BLOCKQUOTE_LINE_RE = re.compile(r"^[ \t]*>[^\n]*(?:\n|$)", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
DOUBLE_QUOTED_RE = re.compile(r'"[^"\n]*"')

SENTENCE_PUNCT = frozenset(".!?")

CLAIM_RES = (
    re.compile(r"\ball done\b", re.IGNORECASE),
    re.compile(r"\ball tests pass\b", re.IGNORECASE),
    re.compile(r"\btests? (?:are|now)\s+passing\b", re.IGNORECASE),
    re.compile(r"\bit'?s\s+(?:now\s+)?(?:done|fixed|complete)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:is|are)\s+(?:now\s+)?(?:done|fixed|complete|completed|passing)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?]\s+)(?:i(?:\s+have|'?ve)?\s+)?"
        r"(?:fixed|completed|finished|resolved|implemented)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|[.!?]\s+)(?:the\s+)?tests? pass\b", re.IGNORECASE),
    re.compile(r"(?:^|[.!?]\s+)(?:done|fixed|completed)\s*[.!]?(?=\s*$)"),
)

RESULT_EVIDENCE_RE = re.compile(
    r"\b\d+\s+passed\b|\b\d+\s+tests\b"
    r"|\bexit (?:code|status)[ :=]+0\b"
    r"|\ball green\b|\b0 (?:failures|failed)\b",
    re.IGNORECASE,
)

RULE = "unproved_done_claim"
ACTION = "Run the verification and paste its result, or drop the done claim."


def scan_done_claims(message: str, path: str) -> list[dict]:
    """Return one finding when the message claims done without verification evidence in it."""
    if not message.strip():
        return []
    claim = _first_claim(_claim_surface(message))
    if claim is None or _has_evidence(_evidence_surface(message)):
        return []
    line_number = claim
    lines = message.splitlines()
    snippet = lines[line_number - 1] if line_number <= len(lines) else ""
    return [{
        "family": "clean_code",
        "rule": RULE,
        "line": line_number,
        "detail": "Done claim without verification evidence in " + path,
        "force": True,
        "snippet": snippet.strip()[:180],
        "action": ACTION,
    }]


def _claim_surface(message: str) -> str:
    """Blank quoted, quoted-block, and code spans so only the assistant's own prose fires."""
    text = FENCED_CODE_RE.sub(_blank_keep_newlines, message)
    text = BLOCKQUOTE_LINE_RE.sub(_blank_keep_newlines, text)
    text = INLINE_CODE_RE.sub("  ", text)
    text = DOUBLE_QUOTED_RE.sub("  ", text)
    return "\n".join(_blank_single_quote_spans(line) for line in text.split("\n"))


def _evidence_surface(message: str) -> str:
    """Blank blockquoted user text because it cannot supply evidence; fenced runner output stays."""
    return BLOCKQUOTE_LINE_RE.sub(_blank_keep_newlines, message)


def _has_evidence(surface: str) -> bool:
    """Return True only on a shown run result; a bare runner mention proves nothing."""
    return RESULT_EVIDENCE_RE.search(surface) is not None


def _blank_keep_newlines(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _quote_candidate_positions(line: str) -> list[int]:
    """Return indexes of boundary-anchored single quotes. Word-internal apostrophes never count."""
    positions = []
    for index, char in enumerate(line):
        if char != "'":
            continue
        before = line[index - 1] if index else " "
        after = line[index + 1] if index + 1 < len(line) else " "
        is_opening = _is_word_char(after) and not _is_word_char(before)
        is_closing = not _is_word_char(after) and (
            _is_word_char(before) or before in SENTENCE_PUNCT
        )
        if is_opening or is_closing:
            positions.append(index)
    return positions


def _blank_single_quote_spans(line: str) -> str:
    """Blank single-quoted spans by pairing boundary quotes, odd count taking the outermost span."""
    # Odd counts blank the outermost span because the lone quote is malformed, hiding claims (D7).
    positions = _quote_candidate_positions(line)
    if len(positions) % 2:
        spans = [(positions[0], positions[-1])] if positions else []
    else:
        spans = list(zip(positions[::2], positions[1::2], strict=True))
    chars = list(line)
    for start, end in spans:
        chars[start:end + 1] = " " * (end - start + 1)
    return "".join(chars)


def _first_claim(surface: str) -> int | None:
    """Return the 1-based line number of the first claim on the stripped surface, or None."""
    for number, line in enumerate(surface.splitlines(), 1):
        if any(pattern.search(line) for pattern in CLAIM_RES):
            return number
    return None
