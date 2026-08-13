"""Classify mixed-language source without changing host coordinates."""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath


class RegionKind(Enum):
    VISIBLE_PROSE = "visible_prose"
    COMMENT = "comment"
    CODE = "code"
    STYLE = "style"
    SCRIPT = "script"
    IGNORED = "ignored"


@dataclass(frozen=True)
class Region:
    kind: RegionKind
    start: int
    end: int
    start_line: int
    end_line: int


MIXED_LANGUAGE_EXTS = frozenset({".html", ".htm", ".xml", ".svg", ".vue", ".svelte"})
BLOCK_TAG_RE = re.compile(
    r"(?P<comment><!--.*?(?:-->|\Z))|"
    r"<(?P<tag>script|style|code|pre)\b[^>]*>.*?(?:</(?P=tag)\s*>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
TEMPLATE_EXPRESSION_RE = re.compile(r"{{.*?}}|{%.*?%}|{#.*?#}", re.DOTALL)
SCRIPT_STRING_RE = re.compile(r'''(?P<quote>["'`])(?:\\.|(?!\1).)*\1''', re.DOTALL)


def _blank_keep_newlines(match: re.Match) -> str:
    """Keep line positions stable because masked syntax becomes spaces."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _region(kind: RegionKind, text: str, start: int, end: int) -> Region:
    end_offset = start if end <= start else end - 1
    return Region(kind, start, end, _line_at(text, start), _line_at(text, end_offset))


def _append_markup_segment(regions: list[Region], text: str, start: int, end: int) -> None:
    cursor = start
    for match in TAG_RE.finditer(text, start, end):
        if cursor < match.start():
            _append_template_parts(regions, text, cursor, match.start())
        regions.append(_region(RegionKind.CODE, text, match.start(), match.end()))
        cursor = match.end()
    if cursor < end:
        _append_template_parts(regions, text, cursor, end)


def _append_template_parts(regions: list[Region], text: str, start: int, end: int) -> None:
    cursor = start
    for match in TEMPLATE_EXPRESSION_RE.finditer(text, start, end):
        if cursor < match.start():
            regions.append(_region(RegionKind.VISIBLE_PROSE, text, cursor, match.start()))
        regions.append(_region(RegionKind.CODE, text, match.start(), match.end()))
        cursor = match.end()
    if cursor < end:
        regions.append(_region(RegionKind.VISIBLE_PROSE, text, cursor, end))


def _block_kind(match: re.Match) -> RegionKind:
    if match.group("comment") is not None:
        return RegionKind.COMMENT
    tag = match.group("tag").lower()
    if tag == "script":
        return RegionKind.SCRIPT
    if tag == "style":
        return RegionKind.STYLE
    return RegionKind.IGNORED


def extract_regions(path: str, text: str) -> tuple[Region, ...]:
    suffix = PurePath(path.lower()).suffix
    if suffix not in MIXED_LANGUAGE_EXTS:
        kind = RegionKind.VISIBLE_PROSE if suffix in {".html", ".htm", ".xml", ".svg"} else RegionKind.CODE
        return (_region(kind, text, 0, len(text)),)
    if suffix in {".vue", ".svelte"} and "<" not in text:
        return (_region(RegionKind.SCRIPT, text, 0, len(text)),)
    regions: list[Region] = []
    cursor = 0
    for match in BLOCK_TAG_RE.finditer(text):
        if cursor < match.start():
            _append_markup_segment(regions, text, cursor, match.start())
        regions.append(_region(_block_kind(match), text, match.start(), match.end()))
        cursor = match.end()
    if cursor < len(text):
        _append_markup_segment(regions, text, cursor, len(text))
    return tuple(regions)


def render_regions(text: str, regions: tuple[Region, ...], accepted: set[RegionKind]) -> str:
    visible = list(text)
    for region in regions:
        if region.kind in accepted:
            continue
        visible[region.start:region.end] = [
            "\n" if char == "\n" else " " for char in text[region.start:region.end]
        ]
    return "".join(visible)


def mask_script_strings(text: str, regions: tuple[Region, ...]) -> str:
    visible = list(text)
    for region in regions:
        if region.kind is not RegionKind.SCRIPT:
            continue
        segment = text[region.start:region.end]
        masked = SCRIPT_STRING_RE.sub(_blank_keep_newlines, segment)
        visible[region.start:region.end] = masked
    return "".join(visible)


def _mask_markup(path: str, text: str) -> str:
    """Mask non-prose syntax because its tokens are not sentences."""
    suffix = PurePath(path.lower()).suffix
    if suffix == ".tex":
        text = re.sub(
            r"\\begin\{(verbatim|lstlisting|equation\*?|align\*)\}.*?\\end\{\1\}",
            _blank_keep_newlines,
            text,
            flags=re.DOTALL,
        )
        text = re.sub(r"\$\$.*?\$\$|\$.*?\$|\\\[.*?\\\]", _blank_keep_newlines, text, flags=re.DOTALL)
        text = re.sub(r"(?<!\\)%.*", _blank_keep_newlines, text)
        return re.sub(r"\\[A-Za-z@]+\*?(?:\[[^]]*\])?", _blank_keep_newlines, text)
    if suffix in {".adoc", ".asciidoc"}:
        text = re.sub(r"^(-{4,}|\.{4,})\s*$.*?^\1\s*$", _blank_keep_newlines, text, flags=re.MULTILINE | re.DOTALL)
        return re.sub(r"^//.*$|^:[^:]+:.*$", _blank_keep_newlines, text, flags=re.MULTILINE)
    if suffix == ".org":
        text = re.sub(r"^#\+begin_[^\n]*$.*?^#\+end_[^\n]*$", _blank_keep_newlines, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
        return re.sub(r"^\s*#.*$", _blank_keep_newlines, text, flags=re.MULTILINE)
    if suffix == ".typ":
        text = re.sub(r"`{3,}.*?`{3,}", _blank_keep_newlines, text, flags=re.DOTALL)
        return re.sub(r"^\s*#.*$", _blank_keep_newlines, text, flags=re.MULTILINE)
    return text


def _sniff_prose(text: str) -> bool:
    """Use a bounded character-ratio heuristic because extensionless files lack suffix metadata."""
    head = text[:1024]
    if head.startswith("#!"):
        return False
    letters = sum(char.isalpha() for char in head)
    spaces = sum(char.isspace() for char in head)
    return bool(re.search(r"[.!?](?:\s|$)", head) and letters + spaces and (letters + spaces) / len(head) > 0.7)
