"""Stop words decide the language, because a model call on every write would spend tokens the gate cannot afford."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

ENGLISH = "en"
GERMAN = "de"
LANGUAGES = (ENGLISH, GERMAN)
DEFAULT_LANGUAGE = ENGLISH
# Kept at 8 because T-010 has not measured it yet.
MIN_STRONG_WORDS = 8

# Shared words left out, because they vote for neither.
ENGLISH_STOP_WORDS = frozenset("""
a about after all and any are as at be because been before but by can could did do does
each for from had has have he her his how i if into is it its just me might more must my
no not of on one only or other our out over she should some such than that the their them
then there these they this those to up us very we were what when where which while who why
with would you your
""".split())
GERMAN_STOP_WORDS = frozenset("""
aber alle als auch auf aus bei beim bereits dass dem der des dich diese diesem diesen dieser
dieses doch du durch ein eine einem einen einer eines etwa für gegen gibt habe haben hatte
hier ich ihr im immer ist jedoch jetzt kann kein keine können mehr mich mit muss nach nicht
noch nur ob oder ohne sehr sich sie sind sowie über und uns unter vom von weil wenn werden
wie wir wird wurde wurden zum zur zwischen
""".split())

FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
PATH_RE = re.compile(r"\S*[/\\]\S*|\b[\w-]+\.[a-z0-9]{1,5}\b")
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
GERMAN_LETTER_RE = re.compile(r"[äöüß]", re.IGNORECASE)


class Signal(NamedTuple):
    language: str | None
    words: int


@dataclass(frozen=True, slots=True)
class ParagraphLanguage:
    """Weak is kept apart from the language, because T-006 sends only weak paragraphs to a model."""

    line: int
    text: str
    language: str
    weak: bool


def countable_text(text: str) -> str:
    """Code, URLs, and paths are dropped because their words are English in every language."""
    for pattern in (INLINE_CODE_RE, URL_RE, PATH_RE):
        text = pattern.sub(" ", text)
    return text


def paragraph_signal(text: str) -> Signal:
    """Umlauts break only a tie, because an English paragraph may still name a German place or person."""
    countable = countable_text(text)
    words = [word.lower() for word in WORD_RE.findall(countable)]
    english = sum(word in ENGLISH_STOP_WORDS for word in words)
    german = sum(word in GERMAN_STOP_WORDS for word in words)
    if english != german:
        return Signal(ENGLISH if english > german else GERMAN, len(words))
    if GERMAN_LETTER_RE.search(countable):
        return Signal(GERMAN, len(words))
    return Signal(None, len(words))


def allowed_languages(cfg: dict) -> tuple[str, ...]:
    """Fall back to both, because a malformed policy must not switch German off unseen."""
    listed = cfg.get("prose_languages")
    if type(listed) is not list:
        return LANGUAGES
    chosen = tuple(language for language in LANGUAGES if language in listed)
    return chosen or LANGUAGES


def _prose_lines(text: str) -> list[str]:
    lines = []
    fenced = False
    for line in text.splitlines():
        is_fence = FENCE_RE.match(line) is not None
        fenced = fenced != is_fence
        lines.append("" if is_fence or fenced else line.strip())
    return lines


def _paragraph_blocks(text: str) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    for number, line in enumerate([*_prose_lines(text), ""], 1):
        if line:
            current.append(line)
            continue
        if current:
            blocks.append((number - len(current), " ".join(current)))
        current = []
    return blocks


def _is_strong(signal: Signal) -> bool:
    return signal.language is not None and signal.words >= MIN_STRONG_WORDS


def _document_language(signals: list[Signal]) -> str:
    strong = [signal.language for signal in signals if _is_strong(signal)]
    return GERMAN if strong.count(GERMAN) > strong.count(ENGLISH) else DEFAULT_LANGUAGE


def paragraph_languages(text: str, allowed: tuple[str, ...] = LANGUAGES) -> list[ParagraphLanguage]:
    blocks = _paragraph_blocks(text)
    if len(allowed) == 1:
        return [ParagraphLanguage(line, block, allowed[0], False) for line, block in blocks]
    signals = [paragraph_signal(block) for _, block in blocks]
    fallback = _document_language(signals)
    return [
        ParagraphLanguage(line, block, signal.language, False)
        if _is_strong(signal)
        else ParagraphLanguage(line, block, fallback, True)
        for (line, block), signal in zip(blocks, signals, strict=True)
    ]
