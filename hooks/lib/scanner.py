from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import PurePath
from typing import NamedTuple

try:
    from . import scan_input
    from .config import GATE_FAMILIES, effective_config
    from .markup import RegionKind, _blank_keep_newlines, _mask_markup, _sniff_prose, extract_regions, mask_script_strings, mask_source_strings, render_regions
except ImportError:
    import scan_input
    from config import GATE_FAMILIES, effective_config
    from markup import RegionKind, _blank_keep_newlines, _mask_markup, _sniff_prose, extract_regions, mask_script_strings, mask_source_strings, render_regions

read_scannable = scan_input.read_scannable
scannable_text = scan_input.scannable_text
_int_setting = scan_input.int_setting


BAD_DASH_RE = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
PROSE_EXTS = {".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg", ".tex", ".adoc", ".asciidoc", ".org", ".typ"}
MIXED_LANGUAGE_EXTS = {".html", ".htm", ".xml", ".svg", ".vue", ".svelte"}
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
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HTML_HIDDEN_RE = re.compile(r"<!--.*?-->|<(script|style|code|pre)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_CODE_RE = re.compile(r"<(code|pre)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
READABILITY_RULES = (
    (re.compile(
        r"\b(?:hope this helps|let me know if you (?:need anything else|have any questions)|"
        r"feel free to (?:ask|reach out)|happy to (?:help|clarify|assist))\b",
        re.IGNORECASE,
    ), "ai_closer", "End when the answer is done."),
    (re.compile(
        r"^\s*(?:(?:great question|to answer your question|looking at your)\b|sure!)",
        re.IGNORECASE,
    ), "greeting_opener", "Start with the answer."),
    (re.compile(
        r"\b(?:could|may|might|should|would)\s+(?:perhaps|possibly|potentially|probably)\b",
        re.IGNORECASE,
    ), "hedge_stack", "Keep one hedge or state the fact."),
    (re.compile(
        r"\b(?:circle back|touch base|get the ball rolling|on the same page|"
        r"low-hanging fruit|move the needle|boil the ocean)\b",
        re.IGNORECASE,
    ), "corporate_idiom", "Name the literal action."),
)
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
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_REFERENCE_RE = re.compile(r"^\s*\[[^]]+\]:\s+\S")
TABLE_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b")
TRACKED_LATER = "TO" + "DO"
BROKEN_LATER = "FIX" + "ME"
NOISY_LATER = "X" + "XX"
ROUGH_LATER = "HA" + "CK"
CLEAN_MARKER_RE = re.compile(
    r"(?://|#|/\*)\s*(?:"
    + TRACKED_LATER + "|" + BROKEN_LATER + "|" + NOISY_LATER + "|" + ROUGH_LATER
    + r")\b",
    re.IGNORECASE,
)
BUG_LABEL_RE = re.compile(r"(?://|#|/\*)\s*(bug|case|fix|issue|step|note)\s+[A-Z0-9]\s*[:.\-]", re.IGNORECASE)
APOLOGY_WORDS = "|".join(("ha" + "cky", "not sure why", "work" + "around", "ug" + "ly"))
APOLOGY_RE = re.compile(r"(?://|#|/\*)\s*.*\b(?:" + APOLOGY_WORDS + r")\b", re.IGNORECASE)
COMMENT_RE = re.compile(r"^\s*(?://[ \t]*|#(?!\!)(?:[ \t]+|(?=$))|/\*[ \t]*)(.*)")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z)", re.DOTALL)
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#|/\*)\s*(def |class |if |for |while |return |import |from |const |let |var |\w+\()", re.IGNORECASE)
HEADER_COMMENT_RE = re.compile(r"^(spdx-license-identifier:|spdx-filecopyrighttext:|copyright\b|coding[:=]|-\*- coding:)", re.IGNORECASE)
LETTER_RE = re.compile(r"[^\W\d_]")
# Matched so that a structured block such as Args or TRIGGERS is read as interface documentation, not as narration.
TAG_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _/-]{0,24}:(?:\s|$)")
WHY_RULE_IS_HEURISTIC = (
    "The WHY and WHAT split is a lexical heuristic, not semantic analysis. "
    "A WHAT comment with a marker can pass, and a genuine WHY comment without one can be blocked. "
    "Its deliberate bias toward over-blocking matches the hard-block policy with no exceptions."
)
STRONG_WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise)\b|\bdue to\b|\bso that\b|\bin order to\b|"
    r"\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b)",
    re.IGNORECASE,
)
CAUSAL_REASON_RE = re.compile(
    r"(?:^why:|\b(?:because|otherwise)\b|\bdue to\b|\bso that\b|\bin order to\b|"
    r"\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b)\s*(?P<reason>.+)$",
    re.IGNORECASE,
)
VAGUE_REASON_RE = re.compile(r"^(?:yes|no|reason|reasons|needed|necessary|stuff|things|logic)[.!]?$", re.IGNORECASE)
GENERIC_REASON_WORDS = frozenset({"break", "breaks", "needed", "necessary", "reason", "reasons"})
TRIPLE_STRING_RE = re.compile(r"(?P<quote>\"\"\"|''').*?(?P=quote)", re.DOTALL)
WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise|unless|assumes|requires|guarantees)\b|"
    r"\bdue to\b|\bso that\b|\bin order to\b|\bexcept when\b|\binstead of\b|"
    r"\brather than\b|\bwork(?:around for|s around)\b|\bbug in\b|"
    r"\bcallers (?:rely on|must)\b|\brelied on by\b|\binvariant:\s*\S|"
    r"\bmust\b.{0,80}\bor\b|\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b)",
    re.IGNORECASE,
)
SINCE_RE = re.compile(r"\bsince\s+\S", re.IGNORECASE)
WHAT_OPENER_RE = re.compile(
    r"^(?:Returns?|Returning|Scans?|Scanning|Checks?|Checking|Validates?|Validating|"
    r"Handles?|Handling|Processes?|Processing|Gets?|Getting|Sets?|Setting|Creates?|Creating|"
    r"Initializes?|Initializing|Iterates?|Iterating|Loops? through|Looping through|"
    r"Copy|Copies|Copying|Reports?|Reporting|Increments?|Incrementing|Decrements?|Decrementing|"
    r"Resets?|Resetting|Stores?|Storing)\b",
    re.IGNORECASE,
)
IDENTIFIER_PART_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+")
CONTENT_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "the", "this", "to", "with",
})
IDENTIFIER_ECHO_THRESHOLD = 0.75
MIN_IDENTIFIER_CONTENT_TOKENS = 3
IMPLICIT_BUDGET_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:ms|s|us|ns)\s+budget\b", re.IGNORECASE)
TEMPORAL_SINCE_RE = re.compile(
    r"\bsince\s+(?:the\s+)?(?:(?:last\s+)?release\b|v(?:ersion)?\.?\s*\d|\d)",
    re.IGNORECASE,
)
WHAT_COMMENT_ACTION = (
    "Only WHY comments are allowed. WHAT comments are never allowed. "
    "State the reason the code is this way, or delete the comment."
)
WHAT_DOCSTRING_ACTION = (
    WHAT_COMMENT_ACTION
    + " A public scope may keep one genuine first-line summary that does not echo its identifier."
)
VC_COMMENT_RE = re.compile(
    r"^\s*(changed?|renamed?|moved?|removed?|added?|replaced?|refactored?|"
    r"fixed|reverted?|updated?|was)\b.{0,60}?\b("
    r"to|from|into|with|previously|used to|formerly|instead of)\b",
    re.IGNORECASE,
)
ASSERT_RE = re.compile(r"\bassert\b|\.assert|expect\(|raises\(|warns\(|should\b|\.to\b|require\.|verify\(", re.IGNORECASE)
TEST_START_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+test\w*\s*\([^)]*\):|^(\s*)(?:it|test|describe)\s*\(", re.IGNORECASE)
PASS_WORD_RE = re.compile(r"\bpass\b", re.IGNORECASE)
SHELL_IN_CONFIG_RE = re.compile(
    r"""-c\s+["']|;\s*(?:do|then|fi|done)\b|&&|\|\||\$\{|\$\(|\bimport\s+\w+\s*;|\btrap\s"""
    r"""|^\s*[\w.\[\]"']+\s*=(?!=)\s*\S|\s--\s"""
)
DIRECTIVE_COMMENT_RE = re.compile(
    r"^(?:#!|#\s*(?:(?:syntax|escape|check)=|noqa\b|type:|pragma\b|ruff:|fmt:|"
    r"eslint-disable(?:-\w+)*\b|(?:>>>|<<<)\s*agent-discipline-watcher)|//\s*@ts-[\w-]+)",
    re.IGNORECASE,
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
    findings.extend(_what_comment_rows(path, comment_source, config, tree))
    findings.extend(_what_docstring_findings(path, tree, config))
    findings.extend(_scan_clean_code_blocks(path, comment_source))
    findings.extend(_scan_docstrings(path, tree))
    if tree is None and path.lower().endswith(".py"):
        findings.extend(_lexical_docstring_findings(path, text))
    findings.extend(_weak_why_findings(path, comment_source.splitlines() or [""]))
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
    code_file = (not prose and not _is_config(path)) or suffix in MIXED_LANGUAGE_EXTS
    return _ScanContext(cfg, tree, lines, prose, code_file, _active_families(path, cfg))


def scan_all(path: str, text: str, config: dict | None = None) -> list[dict]:
    context = _scan_context(path, text, config)
    regions = extract_regions(path, text)
    mixed = PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS
    comment_source = render_regions(text, regions, {RegionKind.COMMENT, RegionKind.SCRIPT}) if mixed else text
    if mixed:
        comment_source = mask_script_strings(comment_source, regions)
    elif PurePath(path.lower()).suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        comment_source = mask_source_strings(comment_source)
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
            scan_line = punct_lines[number - 1] if number <= len(punct_lines) else ""
            findings.extend(
                _scan_punctuation(path, number, line, scan_line, context.prose)
            )
        if "english" in context.active_families and context.prose:
            scan_line = english_lines[number - 1] if number <= len(english_lines) else ""
            findings.extend(_scan_english(path, number, line, scan_line))
        if "clean_code" in context.active_families and context.code_file:
            scan_line = comment_lines[number - 1] if number <= len(comment_lines) else ""
            findings.extend(_scan_clean_code(path, number, scan_line))
    if "english" in context.active_families and context.prose:
        findings.extend(_scan_prose_structure(path, masked, context.config))
    return findings


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


def _is_code(path: str) -> bool:
    return not _is_prose(path) and not _is_config(path)


def _finding(family: str, rule: str, line: int, detail: str, snippet: str, action: str) -> dict:
    return {
        "family": family,
        "rule": rule,
        "line": line,
        "detail": detail,
        "force": True,
        "snippet": snippet.strip()[:180],
        "action": action,
    }


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


CLEAN_CODE_LINE_RULES = (
    (CLEAN_MARKER_RE, "deferred_work_comment",
     "Deferred work marker in ", "Remove the marker or create tracked work."),
    (BUG_LABEL_RE, "bug_label_comment",
     "Comment labels a case by letter or number in ", "Encode the case as a named test."),
    (APOLOGY_RE, "apology_comment",
     "Comment apologizes for code in ", "Fix the code or state the reason plainly."),
    (COMMENTED_CODE_RE, "commented_code",
     "Commented code remains in ", "Delete the commented code."),
)


COMMENT_BODY_RULES = (
    (lambda text: bool(VC_COMMENT_RE.match(text)), "version_control_comment",
     "Comment narrates change history in ", "Delete it. Put change history in the commit message."),
    (lambda text: len(text) > 150, "long_comment",
     "Long comment in ", "Keep only one terse reason or move prose to docs."),
    (lambda text: bool(re.match(r"^(?:now(?:\s+we)?|this\s+(?:function|method|class))\b", text, re.IGNORECASE)),
     "narration_comment", "Comment narrates code in ", "Delete it and let names and structure carry the intent."),
)


def _comment_text(line: str) -> str | None:
    body = COMMENT_RE.match(line)
    if not body:
        return None
    text = body.group(1).strip()
    if DIRECTIVE_COMMENT_RE.match(line.strip()) or HEADER_COMMENT_RE.search(text):
        return None
    return text


def _normalize_block_comments(text: str) -> str:
    def replace(match: re.Match) -> str:
        output = []
        for line in match.group(0).splitlines(keepends=True):
            ending = line[len(line.rstrip("\r\n")):]
            body = line.rstrip("\r\n").strip()
            if body not in {"/*", "/**", "*/", "<!--", "-->"}:
                body = re.sub(r"^(?:/\*+|<!--|\*)\s*", "", body)
                body = re.sub(r"\s*(?:\*/|-->)$", "", body)
            else:
                body = ""
            output.append(("// " + body if body else "//") + ending)
        return "".join(output)
    return BLOCK_COMMENT_RE.sub(replace, text)


def _multiline_comment_findings(path: str, text: str) -> list[dict]:
    return [
        _finding("clean_code", "prose_comment_block", text.count("\n", 0, match.start()) + 1,
                 "Comment block narrates in " + path, match.group(0).splitlines()[0],
                 "Keep one strict WHY line or delete the comment.")
        for match in BLOCK_COMMENT_RE.finditer(text)
        if "\n" in match.group(0) and LETTER_RE.search(match.group(0))
        and not _structured_block_comment(match.group(0))
    ]


def _structured_block_comment(text: str) -> bool:
    normalized = _normalize_block_comments(text)
    rows = [row[3:].strip() for row in normalized.splitlines() if row[3:].strip()]
    return bool(rows) and all(HEADER_COMMENT_RE.search(row) for row in rows)

def _has_why_marker(text: str) -> bool:
    if WHY_COMMENT_RE.search(text):
        return True
    return bool(SINCE_RE.search(text) and not TEMPORAL_SINCE_RE.search(text))


def _has_strong_why_marker(text: str) -> bool:
    if STRONG_WHY_COMMENT_RE.search(text):
        match = CAUSAL_REASON_RE.search(text)
        if match and not VAGUE_REASON_RE.fullmatch(match.group("reason").strip()):
            words = _identifier_tokens(match.group("reason")) - GENERIC_REASON_WORDS
            return len(words) >= 2
    return bool(SINCE_RE.search(text) and not TEMPORAL_SINCE_RE.search(text))

def _narrates_code(text: str) -> bool:
    if not text or not LETTER_RE.search(text):
        return False
    return not TAG_LINE_RE.match(text)


def _identifier_tokens(parts) -> frozenset[str]:
    if isinstance(parts, str):
        parts = (parts,)
    return frozenset(
        token.lower()
        for part in parts
        for token in IDENTIFIER_PART_RE.findall(str(part).replace("_", " "))
        if token.lower() not in CONTENT_STOPWORDS
    )


def _identifier_overlap(name_tokens, param_tokens, text: str) -> float:
    identifiers = _identifier_tokens(name_tokens) | _identifier_tokens(param_tokens)
    content = _identifier_tokens(text)
    if not identifiers or not content:
        return 0.0
    return len(identifiers & content) / len(identifiers | content)


def _identifier_echo(name_tokens, param_tokens, text: str) -> bool:
    content_tokens = _identifier_tokens(text)
    ratio = _identifier_overlap(name_tokens, param_tokens, text)
    if len(content_tokens) < MIN_IDENTIFIER_CONTENT_TOKENS and ratio < 1.0:
        return False
    return ratio >= IDENTIFIER_ECHO_THRESHOLD


def _comment_is_what(text: str, names, params, _config: dict) -> bool:
    del names, params
    if WHAT_OPENER_RE.match(text):
        return not _has_strong_why_marker(text)
    return not _has_why_marker(text)


def _what_comment_rows(path: str, text: str, config: dict, tree) -> list[dict]:
    del config, tree
    lines = text.splitlines() or [""]
    rows = []
    for line_number, line in enumerate(lines, 1):
        comment = _comment_text(line)
        if comment is None or not _narrates_code(comment) or IMPLICIT_BUDGET_RE.match(comment):
            continue
        if not _comment_is_what(comment, (), (), {}):
            continue
        rows.append(_finding(
            "clean_code", "what_comment", line_number,
            "Comment states what the code does in " + path,
            line, WHAT_COMMENT_ACTION,
        ))
    return rows


def _comment_body_rows(path: str, line_number: int, line: str) -> list[dict]:
    text = _comment_text(line)
    if text is None:
        return []
    rows = [
        _finding("clean_code", rule, line_number, detail + path, line, action)
        for matches, rule, detail, action in COMMENT_BODY_RULES
        if matches(text)
    ]
    rows.extend(
        _finding(
            "clean_code", rule, line_number,
            "Readable comment rule in " + path, line, action,
        )
        for pattern, rule, action in READABILITY_RULES
        if pattern.search(text)
    )
    return rows


def _weak_why_findings(path: str, lines: list[str]) -> list[dict]:
    findings = []
    for line_number, line in enumerate(lines, 1):
        text = _comment_text(line)
        if text is None or not _has_why_marker(text) or _has_strong_why_marker(text):
            continue
        findings.append(_finding(
            "clean_code", "weak_why_comment", line_number,
            "Causal wording lacks a concrete reason in " + path, line,
            "Name the constraint, invariant, or consequence, or delete the comment.",
        ))
    return findings


def _scan_clean_code(path: str, line_number: int, line: str) -> list[dict]:
    comment = _comment_text(line)
    rows = [
        _finding("clean_code", rule, line_number, detail + path, line, action)
        for regex, rule, detail, action in CLEAN_CODE_LINE_RULES
        if comment is not None and regex.search(line)
    ]
    rows.extend(_comment_body_rows(path, line_number, line) if comment is not None else [])
    if _looks_like_empty_test(line):
        rows.append(_finding(
            "clean_code",
            "hollow_test",
            line_number,
            "Test body has no assertion in " + path,
            line,
            "Add an assertion or delete the hollow test.",
        ))
    return rows


def _scan_clean_code_file(path: str, text: str, config: dict, tree) -> list[dict]:
    lines = text.splitlines()
    findings = _scan_lengths(path, lines, config, tree)
    findings.extend(_scan_hollow_test_blocks(path, lines))
    return findings


def comment_runs(path: str, text: str) -> list[list[tuple[int, str]]]:
    """Group consecutive comment lines into runs, the same grouping _flush_comment_run judges."""
    lines = text.splitlines()
    runs: list[list[tuple[int, str]]] = []
    run: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        body = COMMENT_RE.match(line)
        if body and body.group(1).strip() and not DIRECTIVE_COMMENT_RE.match(line.strip()):
            run.append((number, line))
            continue
        if run:
            runs.append(run)
        run = []
    if run:
        runs.append(run)
    return runs


def _scan_clean_code_blocks(path: str, text: str) -> list[dict]:
    findings: list[dict] = []
    for run in comment_runs(path, text):
        _flush_comment_run(path, run, findings)
    return findings


def _scope_docstring(scope) -> tuple[int, str] | None:
    body = getattr(scope, "body", [])
    first = body[0] if body else None
    if not isinstance(first, ast.Expr):
        return None
    value = first.value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    return getattr(first, "lineno", 1), value.value


def _narrating_docstring(scope) -> tuple[int, str] | None:
    hit = _scope_docstring(scope)
    if not hit or "\n" not in hit[1].strip():
        return None
    return hit


def _docstring_line_is_what(scope, path: str, line: str, first_line: bool, _config: dict) -> bool:
    del scope, path, first_line
    return not _has_strong_why_marker(line)


def _what_docstring_rows(path: str, scope, hit: tuple[int, str], config: dict) -> list[dict]:
    start, value = hit
    rows = []
    content_index = 0
    structured = False
    for offset, raw_line in enumerate(value.splitlines()):
        line = raw_line.strip()
        if not _narrates_code(line):
            structured = structured or bool(TAG_LINE_RE.match(line))
            continue
        if structured:
            continue
        first_line = content_index == 0
        content_index += 1
        if not _docstring_line_is_what(scope, path, line, first_line, config):
            continue
        rows.append(_finding(
            "clean_code", "what_docstring", start + offset,
            "Docstring states what the code does in " + path,
            line, WHAT_DOCSTRING_ACTION,
        ))
    return rows


def _docstring_scopes(tree) -> list:
    if tree is None:
        return []
    return [tree, *(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))]


def _what_docstring_findings(path: str, tree, config: dict) -> list[dict]:
    findings = []
    for scope in _docstring_scopes(tree):
        hit = _scope_docstring(scope)
        if hit:
            findings.extend(_what_docstring_rows(path, scope, hit, config))
    return findings


def _scan_docstrings(path: str, tree) -> list[dict]:
    findings: list[dict] = []
    for scope in _docstring_scopes(tree):
        narration = _narrating_docstring(scope)
        if narration:
            findings.append(_finding("clean_code", "docstring_narration", narration[0],
                                     "Multi-line docstring narrates in " + path, narration[1],
                                     "Keep one strict WHY line or delete the docstring."))
    return findings


def _lexical_docstring_findings(path: str, text: str) -> list[dict]:
    findings = []
    for match in TRIPLE_STRING_RE.finditer(text):
        value = match.group(0)[3:-3]
        if "\n" not in value.strip():
            continue
        line = text.count("\n", 0, match.start()) + 1
        before = [row.strip() for row in text[:match.start()].splitlines() if row.strip()]
        if before and not _lexical_scope_header(before):
            continue
        findings.append(_finding("clean_code", "docstring_narration", line,
                                 "Multi-line docstring narrates in " + path, value,
                                 "Keep one strict WHY line or delete the docstring."))
    return findings


def _lexical_scope_header(lines: list[str]) -> bool:
    for line in reversed(lines):
        if re.match(r"(?:async\s+)?def\b|class\b", line):
            return True
        if line.endswith(":") and line not in {"):", "]:", "}:"}:
            return False
        if re.match(r"(?:return|raise|yield|import|from|[A-Za-z_]\w*\s*=)\b", line):
            return False
    return False

def _file_length_findings(path: str, count: int) -> list[dict]:
    policy = scan_input.file_length_policy(count)
    if policy is None:
        return []
    rule, action = policy
    return [_finding("clean_code", rule, 1, f"File has {count} lines in {path}", path, action)]


def file_length_findings(path: str, text: str) -> list[dict]:
    return _file_length_findings(path, len(text.splitlines()) or 1) if _is_code(path) else []
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


def _next_fence(line: str, fence: str | None) -> tuple[str | None, bool]:
    marker = FENCE_RE.match(line)
    if not marker:
        return fence, False
    marker_kind = marker.group(1)[0]
    if fence is None:
        return marker_kind, True
    return (None if marker_kind == fence else fence), True


def _markdown_prose_lines(text: str):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        fence, is_marker = _next_fence(line, fence)
        if (
            is_marker or fence or line.lstrip().startswith((">", "|"))
            or TABLE_DELIMITER_RE.match(line)
            or LINK_REFERENCE_RE.match(line)
        ):
            yield number, ""
            continue
        yield number, line


def _paragraphs(lines):
    paragraph = []
    for number, line in lines:
        if line.strip() and not LIST_ITEM_RE.match(line):
            paragraph.append((number, line.strip()))
            continue
        if paragraph:
            yield paragraph
            paragraph = []
    if paragraph:
        yield paragraph


def _sentences(paragraph):
    offsets = []
    chunks = []
    size = 0
    for number, line in paragraph:
        offsets.append((size, number))
        chunks.append(line)
        size += len(line) + 1
    prose = " ".join(chunks)
    start = 0
    for boundary in SENTENCE_BREAK_RE.finditer(prose):
        yield _source_line(offsets, start), prose[start:boundary.start()]
        start = boundary.end()
    if prose[start:].strip():
        yield _source_line(offsets, start), prose[start:]


def _source_line(offsets, start: int) -> int:
    line_number = offsets[0][1]
    for offset, number in offsets:
        if offset > start:
            break
        line_number = number
    return line_number


def _long_sentences_in_paragraph(path: str, paragraph, cap: int) -> list[dict]:
    rows = []
    for number, sentence in _sentences(paragraph):
        visible = _strip_inline_code(_strip_english_hidden(sentence))
        if len(WORD_RE.findall(visible)) > cap:
            rows.append(_finding(
                "english", "long_sentence", number,
                "Sentence exceeds the word cap in " + path,
                sentence, "Split it into shorter sentences.",
            ))
    return rows


def _long_sentence_rows(path: str, lines, cap: int) -> list[dict]:
    rows = []
    for paragraph in _paragraphs(lines):
        rows.extend(_long_sentences_in_paragraph(path, paragraph, cap))
    return rows


def _oversized_list_rows(path: str, lines, cap: int) -> list[dict]:
    rows = []
    count = 0
    start = 0
    first_line = ""
    for number, line in lines:
        if not LIST_ITEM_RE.match(line):
            count = 0
            continue
        if count == 0:
            start = number
            first_line = line
        count += 1
        if count == cap + 1:
            rows.append(_finding(
                "english", "oversized_list", start,
                "List exceeds the item cap in " + path,
                first_line, "Split the list into smaller ranked groups.",
            ))
    return rows


def _scan_prose_structure(path: str, text: str, config: dict) -> list[dict]:
    lines = list(_markdown_prose_lines(text))
    sentence_cap = _int_setting(config, "sentence_word_cap", "ADW_SENTENCE_WORD_CAP", 40)
    list_cap = _int_setting(config, "list_item_cap", "ADW_LIST_ITEM_CAP", 8)
    findings = _long_sentence_rows(path, lines, sentence_cap)
    findings.extend(_oversized_list_rows(path, lines, list_cap))
    return findings


def _scan_lengths(path: str, lines: list[str], config: dict, tree) -> list[dict]:
    del lines
    return _function_length_findings(path, config, tree)


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


def _flush_comment_run(
    path: str, run: list[tuple[int, str]], findings: list[dict]
) -> None:
    if len(run) < 2:
        return
    if _is_header_run(run):
        return
    line_number, line = run[0]
    findings.append(_finding(
        "clean_code",
        "prose_comment_block",
        line_number,
        "Comment block narrates in " + path,
        line,
        "Move the explanation to a wiki page. Create one or update the existing page.",
    ))


def _looks_like_empty_test(line: str) -> bool:
    stripped = line.strip()
    if not re.match(r"(def|function|it|test)\b.*\btest", stripped, re.IGNORECASE):
        return False
    # Use a word boundary because names such as "bypass" and "passes" contain "pass".
    return bool(PASS_WORD_RE.search(stripped)) and not ASSERT_RE.search(stripped)


def _is_header_run(run: list[tuple[int, str]]) -> bool:
    for _line_number, line in run:
        body = COMMENT_RE.match(line)
        if not body:
            return False
        text = body.group(1).strip()
        if not HEADER_COMMENT_RE.search(text):
            return False
    return True


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


def _strip_english_hidden(text: str) -> str:
    text = HTML_HIDDEN_RE.sub(_blank_keep_newlines, text)
    return HTML_TAG_RE.sub(_blank_keep_newlines, text)


def _strip_inline_code(text: str) -> str:
    text = HTML_ENTITY_RE.sub("  ", text)
    return INLINE_CODE_RE.sub("  ", text)


def _strip_quoted(text: str) -> str:
    text = re.sub(r'"[^"]*"', "  ", text)
    return re.sub(r"'[^']*'", "  ", text)


def _punctuation_prose_part(path: str, line: str, prose: bool) -> str:
    if _is_config(path):
        return "" if SHELL_IN_CONFIG_RE.search(line) else line
    if prose:
        return line
    # Ignore trailing comments because quote-unaware hash detection misreads CSS colors and JS private fields.
    leading = COMMENT_RE.match(line)
    return leading.group(1) if leading else ""
