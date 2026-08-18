from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import PurePath
from typing import NamedTuple

try:
    from . import scan_input
    from .comment_rules import (
        READABILITY_RULES,
        _clean_code_comment_findings,
        _comment_body_lines,
        _finding,
        _lexical_docstring_findings,
        _multiline_comment_findings,
        _normalize_block_comments,
        _scan_clean_code_blocks,
        _scan_docstrings,
        _weak_why_findings,
        _what_comment_findings,
        _what_docstring_findings,
    )
    from .config import GATE_FAMILIES, effective_config
    from .markup import (
        MIXED_LANGUAGE_EXTS,
        RegionKind,
        _blank_keep_newlines,
        _mask_markup,
        _sniff_prose,
        _strip_english_hidden,
        _strip_inline_code,
        comment_scan_source,
        extract_regions,
        render_regions,
    )
    from .prose_structure import _next_fence, _scan_prose_structure
except ImportError:
    import scan_input
    from comment_rules import (
        READABILITY_RULES,
        _clean_code_comment_findings,
        _comment_body_lines,
        _finding,
        _lexical_docstring_findings,
        _multiline_comment_findings,
        _normalize_block_comments,
        _scan_clean_code_blocks,
        _scan_docstrings,
        _weak_why_findings,
        _what_comment_findings,
        _what_docstring_findings,
    )
    from config import GATE_FAMILIES, effective_config
    from markup import (
        MIXED_LANGUAGE_EXTS,
        RegionKind,
        _blank_keep_newlines,
        _mask_markup,
        _sniff_prose,
        _strip_english_hidden,
        _strip_inline_code,
        comment_scan_source,
        extract_regions,
        render_regions,
    )
    from prose_structure import _next_fence, _scan_prose_structure

read_scannable = scan_input.read_scannable
scannable_text = scan_input.scannable_text
_int_setting = scan_input.int_setting


BAD_DASH_RE = re.compile("[" + "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)) + "]")
PROSE_EXTS = {".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg", ".tex", ".adoc", ".asciidoc", ".org", ".typ"}
CONFIG_EXTS = {".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env", ".properties"}
CONFIG_BASENAMES = frozenset({
    ".pylintrc", ".editorconfig", ".npmrc", ".yarnrc", ".gitignore", ".gitattributes",
    ".dockerignore", ".flake8", ".coveragerc", ".prettierrc", ".eslintrc", ".babelrc",
})
DASH_BREAK_RE = re.compile(r"\w-{2,} ?\w|\w -{2,} \w")
SPACED_HYPHEN_RE = re.compile(r"\w +- +\w")
PROSE_SEMICOLON_RE = re.compile(r";")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PRONOUN_APOS_RE = re.compile(r"\b(your|their|her|our|its)'s\b", re.IGNORECASE)
ITS_APOS_RE = re.compile(r"(?<![\w\"'])its" + chr(39) + r"(?!\w)", re.IGNORECASE)
DECADE_APOS_RE = re.compile(r"(?:\b\d{3}0|'\d0)'s\b")
HTML_CODE_RE = re.compile(r"<(code|pre)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
ENGLISH_RULES = (
    (re.compile(r"\bsmoking gun\b", re.IGNORECASE), "dead_metaphor", "Name the evidence and what it proves."),
    (re.compile(r"\bat the end of the day\b", re.IGNORECASE), "filler", "State the conclusion directly."),
    (re.compile(r"\b(it'?s worth noting|it'?s important to note|it should be noted)\b", re.IGNORECASE), "throat_clearing", "Start with the point."),
    (re.compile(r"\bneedless to say\b", re.IGNORECASE), "filler", "Delete it or say the point plainly."),
    (re.compile(r"\bin today'?s (fast-paced|digital|modern|ever-changing)\b", re.IGNORECASE), "filler_opener", "Start with the actual point."),
    (re.compile(r"\bdelve into\b", re.IGNORECASE), "ai_tell", "Use a plain verb."),
    (re.compile(r"\b(tapestry|rich tapestry)\b", re.IGNORECASE), "dead_metaphor", "Name the real parts."),
    (re.compile(r"\b(a )?testament to\b", re.IGNORECASE), "inflated_diction", "State what it shows."),
    (re.compile(r"\bnavigat(e|ing) the (complexities|landscape|challenges)\b", re.IGNORECASE), "dead_metaphor", "Say what is hard."),
    (re.compile(r"\butili[sz](?:e|es|ed|ing|ation|ations)\b", re.IGNORECASE), "utilize", "Use 'use'."),
    (re.compile(r"\bleverag(e|es|ed|ing)\b", re.IGNORECASE), "inflated_diction", "Use 'use' or name the action."),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "wordiness", "Use 'to'."),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "wordiness", "Use 'because'."),
    (re.compile(r"\b(a )?(wide )?(variety|plethora|myriad) of\b", re.IGNORECASE), "vague_quantity", "Give the number or name the items."),
    (re.compile(r"\bThere (is|are)\s+\w[\w\s,]{0,40}?\s+that\b", re.IGNORECASE), "expletive_there", "Lead with the subject and an active verb."),
    (re.compile(r"\b(very|really|quite|extremely)\s+\w+", re.IGNORECASE), "empty_intensifier", "Drop the modifier or choose a stronger word."),
    (re.compile(r"\bgame[- ]chang(er|ing)\b", re.IGNORECASE), "dead_metaphor", "State the concrete effect."),
) + READABILITY_RULES
ASSERT_RE = re.compile(r"\bassert\b|\.assert|expect\(|raises\(|warns\(|should\b|\.to\b|require\.|verify\(", re.IGNORECASE)
TEST_START_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+test\w*\s*\([^)]*\):|^(\s*)(?:it|test|describe)\s*\(", re.IGNORECASE)
PASS_WORD_RE = re.compile(r"\bpass\b", re.IGNORECASE)
SHELL_IN_CONFIG_RE = re.compile(
    r"""-c\s+["']|;\s*(?:do|then|fi|done)\b|&&|\|\||\$\{|\$\(|\bimport\s+\w+\s*;|\btrap\s"""
    r"""|^\s*[\w.\[\]"']+\s*=(?!=)\s*\S|\s--\s"""
)
SUPPRESSION_MARKER = "craftsman" + "-ignore"
SUPPRESSION_MARKER_RE = re.compile(r"\b" + re.escape(SUPPRESSION_MARKER) + r"\b", re.IGNORECASE)


def _is_exempt(path: str, cfg: dict) -> bool:
    """Exempt only against a real sequence of patterns, so a wrong type scans more rather than raising."""
    patterns = cfg.get("exempt_paths")
    if not isinstance(patterns, (list, tuple, set, frozenset)):
        return False
    return any(_path_matches(path, pat) for pat in patterns)


def _path_matches(path: str, pattern: object) -> bool:
    if not isinstance(pattern, str):
        return False
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, "*/" + pattern)


def _exempt_families(path: str, cfg: dict) -> frozenset[str]:
    """Return the families this path drops, ignoring unknown names so that a typo scans more rather than less."""
    mapping = cfg.get("exempt_families")
    if not isinstance(mapping, dict):
        return frozenset()
    dropped = {
        name
        for pattern, families in mapping.items()
        if _path_matches(path, pattern) and isinstance(families, (list, tuple, set, frozenset))
        for name in families
    }
    return frozenset(dropped & set(GATE_FAMILIES))


def _active_families(path: str, cfg: dict) -> frozenset[str]:
    dropped = _exempt_families(path, cfg)
    return frozenset(
        name for name in GATE_FAMILIES if cfg.get(name, True) and name not in dropped
    )


def _python_tree(path: str, text: str):
    if not path.lower().endswith(".py"):
        return None
    try:
        return ast.parse(text)
    except SyntaxError:
        return None

def _unconditional_findings(
    path: str, text: str, config: dict, tree, code_file: bool,
    comment_text: str | None = None,
) -> list[dict]:
    lines = text.splitlines() or [""]
    findings = [
        _finding("clean_code", "suppression_escape_hatch", number,
                 "Craftsman suppression marker in " + path, line,
                 "Remove the marker and fix the reported issue.")
        for number, line in enumerate(lines, 1) if SUPPRESSION_MARKER_RE.search(line)
    ]
    comment_source = comment_text if comment_text is not None else text
    if not code_file:
        return findings
    findings.extend(_file_length_findings(path, len(lines)))
    findings.extend(_multiline_comment_findings(path, comment_source))
    comment_source = _normalize_block_comments(comment_source)
    comment_rows = _comment_body_lines(comment_source)
    findings.extend(_what_comment_findings(path, comment_rows))
    findings.extend(_what_docstring_findings(path, tree))
    findings.extend(_scan_clean_code_blocks(path, comment_source))
    findings.extend(_scan_docstrings(path, tree))
    if tree is None and path.lower().endswith(".py"):
        findings.extend(_lexical_docstring_findings(path, text))
    findings.extend(_weak_why_findings(path, comment_rows))
    return findings

class _ScanContext(NamedTuple):
    config: dict
    tree: object
    lines: list[str]
    prose: bool
    code_file: bool
    active_families: frozenset[str]


def _scan_context(path: str, text: str, config: dict | None) -> _ScanContext:
    """Share classification because every scan pass must use the same source view."""
    cfg = effective_config(config)
    tree, lines = _python_tree(path, text), text.splitlines() or [""]
    suffix = PurePath(path.lower()).suffix
    prose = _is_prose(path, text) or suffix in {".vue", ".svelte"}
    code_file = _code_file(path, text)
    return _ScanContext(cfg, tree, lines, prose, code_file, _active_families(path, cfg))


def scan_all(path: str, text: str, config: dict | None = None) -> list[dict]:
    context = _scan_context(path, text, config)
    regions = extract_regions(path, text)
    mixed = PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS
    comment_source = comment_scan_source(path, text, regions, mixed)
    findings = _unconditional_findings(
        path,
        text,
        context.config,
        context.tree,
        context.code_file,
        comment_source,
    )
    if _is_exempt(path, context.config):
        return findings
    masked = render_regions(text, regions, {RegionKind.VISIBLE_PROSE}) if mixed else _mask_markup(path, text)
    punct_lines = _strip_punctuation_blocks(path, masked, context.prose).splitlines() or [""]
    english_lines = _strip_english_hidden(masked).splitlines() or [""]
    comment_lines = comment_source.splitlines() or [""]
    if "clean_code" in context.active_families and context.code_file:
        findings.extend(
            _scan_clean_code_file(path, comment_source, context.config, context.tree)
        )
    for number, line in enumerate(context.lines, 1):
        if "punctuation" in context.active_families:
            scan_line = _line_or_blank(punct_lines, number)
            findings.extend(
                _scan_punctuation(path, number, line, scan_line, context.prose)
            )
        if "english" in context.active_families and context.prose:
            scan_line = _line_or_blank(english_lines, number)
            findings.extend(_scan_english(path, number, line, scan_line))
        if "clean_code" in context.active_families and context.code_file:
            scan_line = _line_or_blank(comment_lines, number)
            findings.extend(_clean_code_comment_findings(path, number, scan_line))
            findings.extend(_hollow_test_line_findings(path, number, scan_line))
    if "english" in context.active_families and context.prose:
        findings.extend(_scan_prose_structure(path, masked, context.config))
    return findings


def _line_or_blank(lines: list[str], number: int) -> str:
    return lines[number - 1] if number <= len(lines) else ""


def _is_prose(path: str, text: str | None = None) -> bool:
    lowered = path.lower()
    if any(lowered.endswith(ext) for ext in PROSE_EXTS):
        return True
    pure = PurePath(path)
    return text is not None and pure.suffix == "" and not pure.name.startswith(".") and pure.name not in CONFIG_BASENAMES and _sniff_prose(text)


def _is_config(path: str) -> bool:
    lowered = path.lower()
    if any(lowered.endswith(ext) for ext in CONFIG_EXTS):
        return True
    # Named one by one because an extensionless dotfile is as often a shell script, and .bashrc must keep being scanned as code.
    return PurePath(lowered).name in CONFIG_BASENAMES


def _code_file(path: str, text: str) -> bool:
    suffix = PurePath(path.lower()).suffix
    return (not _is_prose(path, text) and not _is_config(path)) or suffix in MIXED_LANGUAGE_EXTS


PUNCTUATION_RULES = (
    ("clean", (BAD_DASH_RE,), "banned_dash",
     "Banned dash character in ", "Use ASCII hyphen or rewrite the sentence."),
    ("prose", (DASH_BREAK_RE,), "dash_break",
     "Double hyphen clause break in ", "Use a comma, period, or parentheses."),
    ("prose", (SPACED_HYPHEN_RE,), "spaced_hyphen",
     "Spaced hyphen acts as a dash in ", "Use a comma, period, parentheses, or close up the hyphen."),
    ("semicolon", (PROSE_SEMICOLON_RE,), "prose_semicolon",
     "Semicolon appears in prose in ", "Use a comma, period, or parentheses."),
    ("clean", (PRONOUN_APOS_RE, ITS_APOS_RE), "pronoun_apostrophe",
     "Possessive pronoun has an apostrophe in ", "Use the possessive pronoun without apostrophe."),
    ("clean", (DECADE_APOS_RE,), "decade_apostrophe",
     "Decade written as a possessive in ", "Write the decade as a plural."),
)


def _scan_punctuation(path: str, line_number: int, line: str, scan_line: str, prose: bool) -> list[dict]:
    clean = _strip_inline_code(scan_line)
    prose_part = _punctuation_prose_part(path, clean, prose)
    semicolon = "" if _is_config(path) else URL_RE.sub("", prose_part)
    texts = {"clean": clean, "prose": prose_part, "semicolon": semicolon}
    rows = [
        _finding("punctuation", rule, line_number, detail + path, line, action)
        for target, regexes, rule, detail, action in PUNCTUATION_RULES
        if texts[target] and any(regex.search(texts[target]) for regex in regexes)
    ]
    return rows


def _scan_english(path: str, line_number: int, line: str, scan_line: str) -> list[dict]:
    rows = []
    if line.lstrip().startswith(">"):
        return rows
    scan_line = _strip_quoted(_strip_inline_code(scan_line))
    for pattern, rule, action in ENGLISH_RULES:
        if pattern.search(scan_line):
            rows.append(_finding(
                "english",
                rule,
                line_number,
                "Plain English rule in " + path,
                line,
                action,
            ))
    return rows


def _file_length_findings(path: str, count: int) -> list[dict]:
    policy = scan_input.file_length_policy(count)
    if policy is None:
        return []
    rule, action = policy
    return [_finding("clean_code", rule, 1, f"File has {count} lines in {path}", path, action)]


def file_length_findings(path: str, text: str) -> list[dict]:
    return _file_length_findings(path, len(text.splitlines()) or 1) if _code_file(path, text) else []
def _long_functions(tree, func_limit: int):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            if span > func_limit:
                yield node

def _function_length_findings(path: str, config: dict, tree) -> list[dict]:
    if tree is None:
        return []
    func_limit = _int_setting(config, "function_block_lines", "ADW_FUNC_BLOCK_LINES", 80)
    return [
        _finding(
            "clean_code", "function_too_long", node.lineno,
            "Function is over the length cap in " + path,
            node.name, "Extract helpers until each function does one thing.",
        )
        for node in _long_functions(tree, func_limit)
    ]


def _scan_clean_code_file(path: str, text: str, config: dict, tree) -> list[dict]:
    lines = text.splitlines()
    findings = _function_length_findings(path, config, tree)
    findings.extend(_scan_hollow_test_blocks(path, lines))
    return findings


def _hollow_test_line_findings(path: str, line_number: int, line: str) -> list[dict]:
    if not _looks_like_empty_test(line):
        return []
    return [_finding(
        "clean_code",
        "hollow_test",
        line_number,
        "Test body has no assertion in " + path,
        line,
        "Add an assertion or delete the hollow test.",
    )]


def _scan_hollow_test_blocks(path: str, lines: list[str]) -> list[dict]:
    findings: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        match = TEST_START_RE.match(line)
        if not match:
            index += 1
            continue
        if PASS_WORD_RE.search(stripped):
            index += 1
            continue
        block, next_index = _test_block(lines, index)
        if block and not any(ASSERT_RE.search(part) for part in block):
            findings.append(_finding(
                "clean_code",
                "hollow_test",
                index + 1,
                "Test body has no assertion in " + path,
                line,
                "Add an assertion or delete the hollow test.",
            ))
        index = max(next_index, index + 1)
    return findings


def _test_block(lines: list[str], start: int) -> tuple[list[str], int]:
    line = lines[start]
    if line.rstrip().endswith(":"):
        indent = len(line) - len(line.lstrip())
        body: list[str] = []
        index = start + 1
        while index < len(lines):
            current = lines[index]
            if current.strip() and len(current) - len(current.lstrip()) <= indent:
                break
            body.append(current)
            index += 1
        return body, index
    body = [line]
    depth = line.count("{") - line.count("}")
    if depth <= 0:
        return body, start + 1
    index = start + 1
    while index < len(lines):
        body.append(lines[index])
        depth += lines[index].count("{") - lines[index].count("}")
        if depth <= 0:
            return body, index + 1
        index += 1
    return body, index


def _looks_like_empty_test(line: str) -> bool:
    stripped = line.strip()
    if not re.match(r"(def|function|it|test)\b.*\btest", stripped, re.IGNORECASE):
        return False
    return bool(PASS_WORD_RE.search(stripped)) and not ASSERT_RE.search(stripped)


def _is_table_separator_row(line: str) -> bool:
    return bool(TABLE_SEPARATOR_RE.fullmatch(line.strip()))


def _strip_punctuation_blocks(path: str, text: str, prose: bool | None = None) -> str:
    text = HTML_CODE_RE.sub(_blank_keep_newlines, text)
    text = HTML_SCRIPT_STYLE_RE.sub(_blank_keep_newlines, text)
    if not (prose if prose is not None else _is_prose(path, text)):
        return text
    visible = []
    fence = None
    for line in text.splitlines():
        fence, marker = _next_fence(line, fence)
        hidden = marker or fence or _is_table_separator_row(line)
        visible.append("" if hidden else line)
    return "\n".join(visible)


def _strip_quoted(text: str) -> str:
    text = re.sub(r'"[^"]*"', "  ", text)
    return re.sub(r"'[^']*'", "  ", text)


def _punctuation_prose_part(path: str, line: str, prose: bool) -> str:
    if _is_config(path):
        return "" if SHELL_IN_CONFIG_RE.search(line) else line
    if prose:
        return line
    leading = re.match(r"^\s*(?://[ \t]*|#(?!\!)(?:[ \t]+|(?=$))|/\*[ \t]*)(.*)", line)
    return leading.group(1) if leading else ""
