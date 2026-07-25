from __future__ import annotations

import ast
import fnmatch
import os
import re

try:
    from .config import effective_config
except ImportError:
    from config import effective_config


BAD_DASH_RE = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
PROSE_EXTS = {".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg"}
CONFIG_EXTS = {".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env", ".properties"}
DASH_BREAK_RE = re.compile(r"\w-{2,} ?\w|\w -{2,} \w")
SPACED_HYPHEN_RE = re.compile(r"\w +- +\w")
SEMICOLON_SPLICE_RE = re.compile(r"[a-z]\s*;\s+[a-z]", re.IGNORECASE)
PRONOUN_APOS_RE = re.compile(r"\b(your|their|her|our|its)'s\b", re.IGNORECASE)
ITS_APOS_RE = re.compile(r"(?<![\w\"'])its" + chr(39) + r"(?!\w)", re.IGNORECASE)
DECADE_APOS_RE = re.compile(r"(?:\b\d{3}0|'\d0)'s\b")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HTML_HIDDEN_RE = re.compile(r"<!--.*?-->|<(script|style|code|pre)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_CODE_RE = re.compile(r"<(code|pre)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
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
)
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
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#|/\*)\s*(def |class |if |for |while |return |import |from |const |let |var |\w+\()", re.IGNORECASE)
HEADER_COMMENT_RE = re.compile(r"^(spdx-license-identifier:|spdx-filecopyrighttext:|copyright\b|coding[:=]|-\*- coding:)", re.IGNORECASE)
WHY_RULE_IS_HEURISTIC = (
    "The WHY and WHAT split is a lexical heuristic, not semantic analysis. "
    "A WHAT comment with a marker can pass, and a genuine WHY comment without one can be blocked. "
    "Its deliberate bias toward over-blocking matches the hard-block policy with no exceptions."
)
WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise)\b|\bdue to\b|\bso that\b|\bin order to\b|"
    r"\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b)",
    re.IGNORECASE,
)
SINCE_RE = re.compile(r"\bsince\s+\S", re.IGNORECASE)
TEMPORAL_SINCE_RE = re.compile(
    r"\bsince\s+(?:the\s+)?(?:(?:last\s+)?release\b|v(?:ersion)?\.?\s*\d|\d)",
    re.IGNORECASE,
)
WHAT_COMMENT_ACTION = (
    "Only WHY comments are allowed. WHAT comments are never allowed. "
    "State the reason the code is this way, or delete the comment."
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
    patterns = cfg.get("exempt_paths") or []
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, "*/" + pat) for pat in patterns)


def read_scannable(path, config: dict) -> str | None:
    cfg = effective_config(config)
    try:
        if path.stat().st_size > _max_scan_bytes(cfg):
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def scannable_text(text: str, config: dict) -> str | None:
    if len(text) > _max_scan_bytes(effective_config(config)):
        return None
    if "\0" in text[:8192]:
        return None
    return text


def _max_scan_bytes(config: dict) -> int:
    return _int_setting(config, "max_scan_bytes", "ADW_MAX_SCAN_BYTES", 1_000_000)


def _unconditional_findings(path: str, lines: list[str]) -> list[dict]:
    findings = [
        _finding("clean_code", "suppression_escape_hatch", number,
                 "Craftsman suppression marker in " + path, line,
                 "Remove the marker and fix the reported issue.")
        for number, line in enumerate(lines, 1) if SUPPRESSION_MARKER_RE.search(line)
    ]
    if _is_code(path):
        findings.extend(_what_comment_rows(path, lines))
    return findings


def scan_all(path: str, text: str, config: dict | None = None) -> list[dict]:
    cfg = effective_config(config)
    lines = text.splitlines() or [""]
    findings = _unconditional_findings(path, lines)
    if _is_exempt(path, cfg):
        return findings
    punct_lines = _strip_punctuation_blocks(text).splitlines() or [""]
    english_lines = _strip_english_hidden(text).splitlines() or [""]
    code_file = _is_code(path)
    if cfg["clean_code"] and code_file:
        findings.extend(_scan_clean_code_file(path, text, cfg))
    for number, line in enumerate(lines, 1):
        if cfg["punctuation"]:
            scan_line = punct_lines[number - 1] if number <= len(punct_lines) else ""
            findings.extend(_scan_punctuation(path, number, line, scan_line))
        if cfg["english"] and _is_prose(path):
            scan_line = english_lines[number - 1] if number <= len(english_lines) else ""
            findings.extend(_scan_english(path, number, line, scan_line))
        if cfg["clean_code"] and code_file:
            findings.extend(_scan_clean_code(path, number, line))
    return findings


def _is_prose(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in PROSE_EXTS)


def _is_config(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in CONFIG_EXTS)


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
    ("prose", (SEMICOLON_SPLICE_RE,), "semicolon_splice",
     "Semicolon joins two clauses in ", "Use two sentences."),
    ("clean", (PRONOUN_APOS_RE, ITS_APOS_RE), "pronoun_apostrophe",
     "Possessive pronoun has an apostrophe in ", "Use the possessive pronoun without apostrophe."),
    ("clean", (DECADE_APOS_RE,), "decade_apostrophe",
     "Decade written as a possessive in ", "Write the decade as a plural."),
)


def _scan_punctuation(path: str, line_number: int, line: str, scan_line: str) -> list[dict]:
    clean = _strip_inline_code(scan_line)
    prose = _punctuation_prose_part(path, clean)
    texts = {"clean": clean, "prose": prose}
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


def _has_why_marker(text: str) -> bool:
    if WHY_COMMENT_RE.search(text):
        return True
    return bool(SINCE_RE.search(text) and not TEMPORAL_SINCE_RE.search(text))


def _what_comment_rows(path: str, lines: list[str]) -> list[dict]:
    rows = []
    for line_number, line in enumerate(lines, 1):
        text = _comment_text(line)
        if text is None or _has_why_marker(text):
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
    return [
        _finding("clean_code", rule, line_number, detail + path, line, action)
        for matches, rule, detail, action in COMMENT_BODY_RULES
        if matches(text)
    ]


def _scan_clean_code(path: str, line_number: int, line: str) -> list[dict]:
    rows = [
        _finding("clean_code", rule, line_number, detail + path, line, action)
        for regex, rule, detail, action in CLEAN_CODE_LINE_RULES
        if regex.search(line)
    ]
    rows.extend(_comment_body_rows(path, line_number, line))
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


def _scan_clean_code_file(path: str, text: str, config: dict) -> list[dict]:
    lines = text.splitlines()
    findings = _scan_clean_code_blocks(path, text)
    findings.extend(_scan_docstrings(path, text))
    findings.extend(_scan_lengths(path, text, lines, config))
    findings.extend(_scan_hollow_test_blocks(path, lines))
    return findings


def _scan_clean_code_blocks(path: str, text: str) -> list[dict]:
    findings: list[dict] = []
    run: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        body = COMMENT_RE.match(line)
        if body and body.group(1).strip() and not DIRECTIVE_COMMENT_RE.match(line.strip()):
            run.append((number, line))
            continue
        _flush_comment_run(path, run, findings)
        run = []
    _flush_comment_run(path, run, findings)
    return findings


def _narrating_docstring(scope) -> tuple[int, str] | None:
    """Return (line, text) of a scope's multi-line docstring, or None."""
    body = getattr(scope, "body", [])
    first = body[0] if body else None
    if not isinstance(first, ast.Expr):
        return None
    value = first.value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    if "\n" not in value.value.strip():
        return None
    return getattr(first, "lineno", 1), value.value


def _scan_docstrings(path: str, text: str) -> list[dict]:
    if not path.lower().endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    scopes = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    findings: list[dict] = []
    for scope in scopes:
        hit = _narrating_docstring(scope)
        if hit:
            findings.append(_finding(
                "clean_code",
                "docstring_narration",
                hit[0],
                "Multi-line docstring narrates in " + path,
                hit[1],
                "Move the explanation to a wiki page. Create one or update the existing page.",
            ))
    return findings


def _file_length_findings(path: str, count: int, config: dict) -> list[dict]:
    hard = _int_setting(config, "file_block_lines", "CLEANCODER_FILE_BLOCK_LINES", 1000)
    if count >= hard:
        return [_finding(
            "clean_code", "file_too_long", 1,
            "File is over the hard length cap in " + path,
            path, "Split this file into focused modules.",
        )]
    return []


def _long_functions(tree, func_limit: int):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            if span > func_limit:
                yield node


def _function_length_findings(path: str, text: str, config: dict) -> list[dict]:
    if not path.lower().endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    func_limit = _int_setting(config, "function_block_lines", "CLEANCODER_FUNC_BLOCK_LINES", 80)
    return [
        _finding(
            "clean_code", "function_too_long", node.lineno,
            "Function is over the length cap in " + path,
            node.name, "Extract helpers until each function does one thing.",
        )
        for node in _long_functions(tree, func_limit)
    ]


def _scan_lengths(path: str, text: str, lines: list[str], config: dict) -> list[dict]:
    findings = _file_length_findings(path, len(lines), config)
    findings.extend(_function_length_findings(path, text, config))
    return findings


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


def _flush_comment_run(path: str, run: list[tuple[int, str]], findings: list[dict]) -> None:
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


def _strip_punctuation_blocks(text: str) -> str:
    text = HTML_CODE_RE.sub(_blank_keep_newlines, text)
    return HTML_SCRIPT_STYLE_RE.sub(_blank_keep_newlines, text)


def _strip_english_hidden(text: str) -> str:
    text = HTML_HIDDEN_RE.sub(_blank_keep_newlines, text)
    return HTML_TAG_RE.sub(_blank_keep_newlines, text)


def _blank_keep_newlines(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_inline_code(text: str) -> str:
    text = HTML_ENTITY_RE.sub("  ", text)
    return INLINE_CODE_RE.sub("  ", text)


def _strip_quoted(text: str) -> str:
    text = re.sub(r'"[^"]*"', "  ", text)
    return re.sub(r"'[^']*'", "  ", text)


def _punctuation_prose_part(path: str, line: str) -> str:
    if _is_config(path) and SHELL_IN_CONFIG_RE.search(line):
        return ""
    if _is_prose(path) or _is_config(path):
        return line
    leading = COMMENT_RE.match(line)
    if leading:
        return leading.group(1)
    positions = [pos for pos in (line.find("#"), _line_comment_slashes(line)) if pos >= 0]
    if not positions:
        return ""
    pos = min(positions)
    return line[pos + (2 if line.startswith("//", pos) else 1):]


def _line_comment_slashes(line: str) -> int:
    # Ignore URL schemes because their :// token is not a comment marker.
    for match in re.finditer(r"//", line):
        if match.start() == 0 or line[match.start() - 1] != ":":
            return match.start()
    return -1


def _int_setting(config: dict, key: str, env_name: str, default: int) -> int:
    raw = config.get(key, os.environ.get(env_name, default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
