"""Masks source in place here because every downstream scan and hook needs the original path:line coordinates to stay intact."""

import io
import json
import re
import tokenize
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import PurePath


class RegionKind(Enum):
    VISIBLE_PROSE = "visible_prose"
    COMMENT = "comment"
    CODE = "code"
    STYLE = "style"
    SCRIPT = "script"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class Region:
    kind: RegionKind
    start: int
    end: int
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class TextSpan:
    text: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not 0 <= self.start <= self.end <= len(self.text):
            raise ValueError("text span must fall within its text")


@dataclass(frozen=True, slots=True)
class TokenSpan:
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    def __post_init__(self) -> None:
        if self.start_row < 1 or self.end_row < self.start_row:
            raise ValueError("token span rows are invalid")
        if self.start_col < 0 or self.end_col < 0:
            raise ValueError("token span columns must be non-negative")
        if self.start_row == self.end_row and self.end_col < self.start_col:
            raise ValueError("single-line token span ends before it starts")


@dataclass(frozen=True, slots=True)
class CommentSource:
    path: str
    text: str
    regions: tuple[Region, ...]
    mixed: bool


MIXED_LANGUAGE_EXTS = frozenset({".html", ".htm", ".xml", ".svg", ".vue", ".svelte"})
BLOCK_TAG_RE = re.compile(
    r"(?P<comment><!--.*?(?:-->|\Z))|"
    r"<(?P<tag>script|style|code|pre)\b[^>]*>.*?(?:</(?P=tag)\s*>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
TEMPLATE_EXPRESSION_RE = re.compile(r"{{.*?}}|{%.*?%}|{#.*?#}", re.DOTALL)
SCRIPT_STRING_RE = re.compile(r'''(?P<quote>["'`])(?:\\.|(?!\1)[^\\])*\1''', re.DOTALL)


LOG_EXTS = frozenset({".log"})
PLAIN_TEXT_EXTS = frozenset({".txt", ".text", ".out", ""})
_BLANK_ALL_RE = re.compile(r"[^\n]")
_MATCH_LINE = r"^[^\s:]+[:-]\d+[:-].*$"
_LOG_LINE = r"^[ \t]*\[?(?:\d{4}-\d{2}-\d{2}[T ])?\d{2}:\d{2}:\d{2}.*$"
_DIFF_LINE = r"^(?:diff --git |index |--- |\+\+\+ |@@ |[ +-]).*$"
TOOL_LINE_RE = re.compile(f"{_MATCH_LINE}|{_LOG_LINE}", re.MULTILINE)
TOOL_LINE_WITH_DIFF_RE = re.compile(f"{_MATCH_LINE}|{_LOG_LINE}|{_DIFF_LINE}", re.MULTILINE)
DIFF_HEADER_RES = tuple(re.compile(marker, re.MULTILINE) for marker in (r"^--- ", r"^\+\+\+ ", r"^@@ "))


def _blank_keep_newlines(match: re.Match) -> str:
    """Keep line positions stable because masked syntax becomes spaces."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _region(kind: RegionKind, span: TextSpan) -> Region:
    end_offset = span.start if span.end <= span.start else span.end - 1
    return Region(
        kind,
        span.start,
        span.end,
        _line_at(span.text, span.start),
        _line_at(span.text, end_offset),
    )


def _append_markup_segment(regions: list[Region], span: TextSpan) -> None:
    cursor = span.start
    for match in TAG_RE.finditer(span.text, span.start, span.end):
        if cursor < match.start():
            _append_template_parts(regions, TextSpan(span.text, cursor, match.start()))
        regions.append(_region(RegionKind.CODE, TextSpan(span.text, match.start(), match.end())))
        cursor = match.end()
    if cursor < span.end:
        _append_template_parts(regions, TextSpan(span.text, cursor, span.end))


def _append_template_parts(regions: list[Region], span: TextSpan) -> None:
    cursor = span.start
    for match in TEMPLATE_EXPRESSION_RE.finditer(span.text, span.start, span.end):
        if cursor < match.start():
            regions.append(_region(RegionKind.VISIBLE_PROSE, TextSpan(span.text, cursor, match.start())))
        regions.append(_region(RegionKind.CODE, TextSpan(span.text, match.start(), match.end())))
        cursor = match.end()
    if cursor < span.end:
        regions.append(_region(RegionKind.VISIBLE_PROSE, TextSpan(span.text, cursor, span.end)))


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
        return (_region(RegionKind.CODE, TextSpan(text, 0, len(text))),)
    if suffix in {".vue", ".svelte"} and "<" not in text:
        return (_region(RegionKind.SCRIPT, TextSpan(text, 0, len(text))),)
    regions: list[Region] = []
    cursor = 0
    for match in BLOCK_TAG_RE.finditer(text):
        if cursor < match.start():
            _append_markup_segment(regions, TextSpan(text, cursor, match.start()))
        regions.append(_region(_block_kind(match), TextSpan(text, match.start(), match.end())))
        cursor = match.end()
    if cursor < len(text):
        _append_markup_segment(regions, TextSpan(text, cursor, len(text)))
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


def comment_scan_source(source: CommentSource) -> str:
    """Kept in one place because every caller must mask strings the same way per language, not re-derive its own order."""
    if source.mixed:
        visible = render_regions(
            source.text,
            source.regions,
            {RegionKind.COMMENT, RegionKind.SCRIPT},
        )
        return mask_script_strings(visible, source.regions)
    suffix = PurePath(source.path.lower()).suffix
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return mask_source_strings(source.text)
    if suffix == ".py":
        return mask_python_strings(source.text)
    return source.text


STRING_TOKEN_TYPES = frozenset(
    tok_type for tok_type in (
        tokenize.STRING,
        getattr(tokenize, "FSTRING_START", None),
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "FSTRING_END", None),
    )
    if tok_type is not None
)


def _token_span(token: tokenize.TokenInfo) -> tuple[TokenSpan, ...]:
    if token.type not in STRING_TOKEN_TYPES:
        return ()
    return (TokenSpan(token.start[0], token.start[1], token.end[0], token.end[1]),)


def _python_string_spans(text: str) -> tuple[list[TokenSpan], tuple[int, int] | None]:
    spans: list[TokenSpan] = []
    last_end = (1, 0)
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            spans.extend(_token_span(token))
            last_end = token.end
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError) as exc:
        return spans, _token_error_offset(exc) or last_end
    return spans, None


def mask_python_strings(text: str) -> str:
    """Blanked with the tokenizer, not a regex, because Python string bodies can span lines and nest quotes in ways a regex cannot track reliably."""
    spans, failure_start = _python_string_spans(text)
    if not spans and failure_start is None:
        return text
    lines = text.splitlines(keepends=True)
    for span in spans:
        _blank_token_span(lines, span)
    if failure_start is not None:
        _blank_from(lines, failure_start)
    return "".join(lines)


def _token_error_offset(exc: Exception) -> tuple[int, int] | None:
    if len(exc.args) >= 2 and isinstance(exc.args[1], tuple) and len(exc.args[1]) == 2:
        return exc.args[1]
    lineno = getattr(exc, "lineno", None)
    offset = getattr(exc, "offset", None)
    if lineno is not None and offset is not None:
        return (lineno, max(offset - 1, 0))
    return None


def _blank_from(lines: list[str], start: tuple[int, int]) -> None:
    """Blank onward from a tokenize failure because a marker past a broken literal must stay hidden, not just the part the tokenizer reached."""
    if not lines:
        return
    row = max(1, min(start[0], len(lines)))
    index = row - 1
    line = lines[index]
    ending = "\n" if line.endswith("\n") else ""
    col = max(0, min(start[1], len(line) - len(ending)))
    lines[index] = line[:col] + " " * (len(line) - col - len(ending)) + ending
    for later in range(index + 1, len(lines)):
        ending = "\n" if lines[later].endswith("\n") else ""
        lines[later] = " " * (len(lines[later]) - len(ending)) + ending


def _blank_token_span(lines: list[str], span: TokenSpan) -> None:
    if span.start_row == span.end_row:
        line = lines[span.start_row - 1]
        lines[span.start_row - 1] = (
            line[:span.start_col]
            + " " * (span.end_col - span.start_col)
            + line[span.end_col:]
        )
        return
    first = lines[span.start_row - 1]
    ending = "\n" if first.endswith("\n") else ""
    lines[span.start_row - 1] = (
        first[:span.start_col]
        + " " * (len(first) - span.start_col - len(ending))
        + ending
    )
    for row in range(span.start_row, span.end_row - 1):
        middle = lines[row]
        ending = "\n" if middle.endswith("\n") else ""
        lines[row] = " " * (len(middle) - len(ending)) + ending
    last = lines[span.end_row - 1]
    lines[span.end_row - 1] = " " * span.end_col + last[span.end_col:]


MARKDOWN_EXTS = frozenset({".md", ".markdown", ".mdx", ".mdc"})
PROSE_EXTS = MARKDOWN_EXTS | {".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg", ".tex", ".adoc", ".asciidoc", ".org", ".typ"}
CONFIG_EXTS = frozenset({".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env", ".properties"})
DATA_TEXT_EXTS = frozenset({".json", ".jsonl", ".csv", ".tsv", ".lock", ".map", ".svg", ".xml", ".sql"})
COMMENTABLE_EXTS = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".cs", ".go", ".h", ".hpp", ".java", ".js",
    ".jsx", ".kt", ".kts", ".mjs", ".php", ".rb", ".rs", ".sh", ".swift", ".ts",
    ".tsx", ".vue", ".svelte",
})
# Because a host runs these as source, a stray byte must not make them skippable.
SCRIPT_EXTS = frozenset({".py", ".pyi", ".bash", ".zsh", ".ksh", ".fish", ".pl", ".pm", ".lua", ".ps1", ".css", ".scss"})
FRONTMATTER_RE = re.compile(r"\A-{3}[ \t]*\n.*?^(?:-{3}|\.{3})[ \t]*$", re.DOTALL | re.MULTILINE)


def _mask_frontmatter(suffix: str, text: str) -> str:
    """Frontmatter is YAML metadata, so its key colons are not sentence punctuation. Only a closed leading block counts, because a lone opening delimiter is a horizontal rule or a setext underline."""
    if suffix not in MARKDOWN_EXTS:
        return text
    return FRONTMATTER_RE.sub(_blank_keep_newlines, text, count=1)


def _mask_tool_output(suffix: str, text: str) -> str:
    """Because saved command output repeats what a tool printed, its log, diff, match and JSON lines are no sentences the agent wrote."""
    if suffix in LOG_EXTS or (suffix in PLAIN_TEXT_EXTS and _json_document(text)):
        return _BLANK_ALL_RE.sub(" ", text)
    if suffix not in PLAIN_TEXT_EXTS:
        return text
    pattern = TOOL_LINE_WITH_DIFF_RE if _unified_diff(text) else TOOL_LINE_RE
    return pattern.sub(_blank_keep_newlines, text)


def _json_document(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return False
    return True


def _unified_diff(text: str) -> bool:
    return all(marker.search(text) for marker in DIFF_HEADER_RES)


QUOTED_PROSE_RE = re.compile(
    "\"[^\"\n]*\"|“[^”\n]*”|(?<!\\w)'[^'\n]*'(?!\\w)|(?<!\\w)‘[^’\n]*’(?!\\w)"
)


def _blank_quoted_inside(found: re.Match[str]) -> str:
    text = found.group(0)
    return text[0] + " " * (len(text) - 2) + text[-1]


QUOTE_MENTION_CONTEXT_RE = re.compile(
    r"\b(?:called|named|says?|said|wrote|reads?|phrase|term|words?|expression|label)[ \t]*$",
    re.IGNORECASE,
)


def _blank_quoted_mention(found: re.Match[str]) -> str:
    inner = found[0][1:-1]
    line_start = found.string.rfind("\n", 0, found.start()) + 1
    context = found.string[line_start:found.start()]
    if re.search(r"[.!?]", inner) or len(inner.split()) > 8:
        return found[0]
    if QUOTE_MENTION_CONTEXT_RE.search(context) is None:
        return found[0]
    return _blank_quoted_inside(found)


def mask_phrase_mentions(text: str) -> str:
    """Keep quoted sentences scannable because only short named or spoken fragments are mentions."""
    return QUOTED_PROSE_RE.sub(_blank_quoted_mention, text)


def mask_quoted(text: str) -> str:
    """Blank quoted words but keep delimiters and length, because quoted text is cited, not written, and a contraction must not open a quote."""
    return QUOTED_PROSE_RE.sub(_blank_quoted_inside, text)


class FencePolicy(Enum):
    """Keep host grammars explicit because their existing masks differ."""

    # Because document fences require matching widths and clean closing tails.
    MARKDOWN = "markdown"
    # Because prompt examples accept backticks only and blank carriage returns too.
    PROMPT = "prompt"
    # Because language routing historically toggles on every indented fence marker.
    LANGUAGE = "language"
    # Because punctuation closes on matching kinds, regardless of width.
    PUNCTUATION = "punctuation"


MARKDOWN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)")
LOOSE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
# humanizer-de Muster 57 cases A to C, because Q13 credits it.
THEMATIC_BREAK = r"(?:-{3,}|\*{3,}|_{3,})"
BREAK_THEN_HEADING_RE = re.compile(r"^" + THEMATIC_BREAK + r"\s+#{1,6}\s")
BREAK_ONLY_RE = re.compile(r"^" + THEMATIC_BREAK + r"$")
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
TABLE_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")
SEPARATOR_ROW_RE = re.compile(r"\|(?:\s*:?-{3,}:?\s*\|)+")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
PIPE_RE = re.compile(r"(?<!\\)\|")
LINK_REFERENCE_RE = re.compile(r"^\s*\[[^]]+\]:\s+\S")
# Because COMPREHENSIVE TECHNICAL STANDARDS drew findings, mask title labels.
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
SETEXT_RE = re.compile(r"^\s{0,3}(?:={2,}|-{2,})\s*$")
# Because a prose sentence may carry a colon, mask labels only in lists.
LABEL_LINE_RE = re.compile(r"^\s*[-+*]\s+(?:\[[ xX]\]\s*)?(?:\*{2}[^*]{1,40}\*{2}|`[^`]{1,40}`)\s*:")


@dataclass(frozen=True, slots=True)
class MarkdownLine:
    """Keep physical lines because consumers report original source coordinates."""

    number: int
    text: str
    hidden: bool

    @property
    def content(self) -> str:
        return self.text.rstrip("\r\n")

    @property
    def prose_boundary(self) -> bool:
        line = self.content
        if line.lstrip().startswith((">", "|")):
            return True
        return any(pattern.match(line) for pattern in (
            TABLE_DELIMITER_RE, LINK_REFERENCE_RE, HEADING_RE, SETEXT_RE, LABEL_LINE_RE,
        ))

    @property
    def punctuation_separator(self) -> bool:
        return is_table_separator_row(self.content)


def _fence_step(line: str, fence: str, policy: FencePolicy) -> tuple[str, bool]:
    if policy in (FencePolicy.LANGUAGE, FencePolicy.PUNCTUATION):
        marker = LOOSE_FENCE_RE.match(line)
        if marker is None:
            return fence, bool(fence)
        kind = marker[1][0]
        closing = bool(fence) and (policy is FencePolicy.LANGUAGE or kind == fence)
        return ("" if closing else fence or kind), True
    marker = MARKDOWN_FENCE_RE.match(line)
    if policy is FencePolicy.PROMPT and marker and marker[1][0] != "`":
        marker = None
    if marker is None:
        return fence, bool(fence)
    tail = line[len(line) - len(line.lstrip(" ")) + len(marker[1]):]
    closing_tail = tail.strip(" \t\r\n") if policy is FencePolicy.PROMPT else marker[2].strip()
    closing = bool(fence and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not closing_tail)
    opening = not fence and (marker[1][0] != "`" or "`" not in tail)
    return (marker[1] if opening else "" if closing else fence), bool(fence) or opening


@lru_cache(maxsize=2)
def markdown_lines(text: str, policy: FencePolicy = FencePolicy.MARKDOWN) -> tuple[MarkdownLine, ...]:
    """Keep each delimiter line hidden because it belongs to the fenced block."""
    fence = ""
    result = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        fence, hidden = _fence_step(line, fence, policy)
        result.append(MarkdownLine(number, line, hidden))
    return tuple(result)


def is_table_separator_row(line: str) -> bool:
    """Keep punctuation out because delimiter dashes belong to Markdown syntax."""
    return bool(TABLE_SEPARATOR_RE.fullmatch(line.strip()))


def markdown_heading(text: str) -> re.Match[str] | None:
    """Keep the heading capture because German findings name its original marker."""
    return MARKDOWN_HEADING_RE.match(text)


def one_row_table_separator(text: str) -> re.Match[str] | None:
    """Count joined rows because language paragraphs replace line breaks with spaces."""
    separator = SEPARATOR_ROW_RE.search(text)
    if not text.startswith("|") or separator is None:
        return None
    width = len(SEPARATOR_CELL_RE.findall(separator[0])) + 1
    return separator if len(PIPE_RE.findall(text)) == width * 3 else None


def mask_markdown_fences(text: str, policy: FencePolicy = FencePolicy.MARKDOWN) -> str:
    """Keep source coordinates because every prose pass reports the original line."""
    blank = r"[^\n]" if policy is FencePolicy.PROMPT else r"[^\r\n]"
    return "".join(re.sub(blank, " ", line.text) if line.hidden else line.text for line in markdown_lines(text, policy))


def _mask_markup(path: str, text: str) -> str:
    """Mask non-prose syntax because its tokens are not sentences."""
    suffix = PurePath(path.lower()).suffix
    text = _mask_tool_output(suffix, text)
    text = _mask_frontmatter(suffix, text)
    if suffix in MARKDOWN_EXTS | PLAIN_TEXT_EXTS:
        text = mask_markdown_fences(text)
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


HTML_HIDDEN_RE = re.compile(r"<!--.*?-->|<(script|style|code|pre)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
HTML_ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#(?:\d+|[xX][0-9A-Fa-f]+));")
INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _strip_english_hidden(text: str) -> str:
    text = HTML_HIDDEN_RE.sub(_blank_keep_newlines, text)
    return TAG_RE.sub(_blank_keep_newlines, text)


def _strip_inline_code(text: str) -> str:
    text = HTML_ENTITY_RE.sub("  ", text)
    return INLINE_CODE_RE.sub("  ", text)
