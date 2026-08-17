"""Masks source in place here because every downstream scan and hook needs the original path:line coordinates to stay intact."""

import io
import re
import tokenize
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


def mask_source_strings(text: str) -> str:
    return SCRIPT_STRING_RE.sub(_blank_keep_newlines, text)


def comment_scan_source(path: str, text: str, regions: tuple[Region, ...], mixed: bool) -> str:
    """Kept in one place because every caller must mask strings the same way per language, not re-derive its own order."""
    if mixed:
        return mask_script_strings(render_regions(text, regions, {RegionKind.COMMENT, RegionKind.SCRIPT}), regions)
    suffix = PurePath(path.lower()).suffix
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return mask_source_strings(text)
    if suffix == ".py":
        return mask_python_strings(text)
    return text


def mask_python_strings(text: str) -> str:
    """Blanked with the tokenizer, not a regex, because Python string bodies can span lines and nest quotes in ways a regex cannot track reliably."""
    try:
        spans = [
            (tok.start[0], tok.start[1], tok.end[0], tok.end[1])
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
            if tok.type == tokenize.STRING
        ]
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError):
        return text
    if not spans:
        return text
    lines = text.splitlines(keepends=True)
    for start_row, start_col, end_row, end_col in spans:
        _blank_token_span(lines, start_row, start_col, end_row, end_col)
    return "".join(lines)


def _blank_token_span(lines: list[str], start_row: int, start_col: int, end_row: int, end_col: int) -> None:
    if start_row == end_row:
        line = lines[start_row - 1]
        lines[start_row - 1] = line[:start_col] + " " * (end_col - start_col) + line[end_col:]
        return
    first = lines[start_row - 1]
    ending = "\n" if first.endswith("\n") else ""
    lines[start_row - 1] = first[:start_col] + " " * (len(first) - start_col - len(ending)) + ending
    for row in range(start_row, end_row - 1):
        middle = lines[row]
        ending = "\n" if middle.endswith("\n") else ""
        lines[row] = " " * (len(middle) - len(ending)) + ending
    last = lines[end_row - 1]
    lines[end_row - 1] = " " * end_col + last[end_col:]


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
