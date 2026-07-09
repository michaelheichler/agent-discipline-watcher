from __future__ import annotations

import ast
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
COMMA_SPLICE_RE = re.compile(r"\b(?:I|we|you|he|she|it|they)\b[^,.;:]{0,40},\s+(?:I|we|you|he|she|it|they)\s+[a-z]+", re.IGNORECASE)
QUOTE_OUTSIDE_RE = re.compile(r"[a-z]\"\s*[.,]")
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
COMMENT_RE = re.compile(r"^\s*(?://|#(?!\!)|/\*)\s*(.*)")
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#|/\*)\s*(def |class |if |for |while |return |import |from |const |let |var |\w+\()", re.IGNORECASE)
HEADER_COMMENT_RE = re.compile(r"^(spdx-license-identifier:|spdx-filecopyrighttext:|copyright\b|coding[:=]|-\*- coding:)", re.IGNORECASE)
VC_COMMENT_RE = re.compile(
    r"^\s*(changed?|renamed?|moved?|removed?|added?|replaced?|refactored?|"
    r"fixed|reverted?|updated?|was)\b.{0,60}?\b("
    r"to|from|into|with|previously|used to|formerly|instead of)\b",
    re.IGNORECASE,
)
SKIP_TEST_RE = re.compile(r"\b(skip|skipif|xfail|disabled)\s*\(", re.IGNORECASE)
ASSERT_RE = re.compile(r"\bassert\b|\.assert|expect\(|raises\(|warns\(|should\b|\.to\b|require\.|verify\(", re.IGNORECASE)
TEST_START_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+test\w*\s*\([^)]*\):|^(\s*)(?:it|test|describe)\s*\(", re.IGNORECASE)


def scan_all(path: str, text: str, config: dict | None = None) -> list[dict]:
    cfg = effective_config(config)
    findings: list[dict] = []
    lines = text.splitlines() or [""]
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


def _finding(family: str, rule: str, line: int, detail: str, force: bool, snippet: str, action: str) -> dict:
    return {
        "family": family,
        "rule": rule,
        "line": line,
        "detail": detail,
        "force": force,
        "snippet": snippet.strip()[:180],
        "action": action,
    }


PUNCTUATION_RULES = (
    ("clean", (BAD_DASH_RE,), "banned_dash", True,
     "Banned dash character in ", "Use ASCII hyphen or rewrite the sentence."),
    ("prose", (DASH_BREAK_RE,), "dash_break", True,
     "Double hyphen clause break in ", "Use a comma, period, or parentheses."),
    ("prose", (SPACED_HYPHEN_RE,), "spaced_hyphen", True,
     "Spaced hyphen acts as a dash in ", "Use a comma, period, parentheses, or close up the hyphen."),
    ("prose", (SEMICOLON_SPLICE_RE,), "semicolon_splice", True,
     "Semicolon joins two clauses in ", "Use two sentences."),
    ("prose", (QUOTE_OUTSIDE_RE,), "quote_punctuation", False,
     "Comma or period sits outside a closing quote in ", "Put the comma or period inside the closing quote."),
    ("clean", (PRONOUN_APOS_RE, ITS_APOS_RE), "pronoun_apostrophe", True,
     "Possessive pronoun has an apostrophe in ", "Use the possessive pronoun without apostrophe."),
    ("clean", (DECADE_APOS_RE,), "decade_apostrophe", True,
     "Decade written as a possessive in ", "Write the decade as a plural."),
)


def _scan_punctuation(path: str, line_number: int, line: str, scan_line: str) -> list[dict]:
    clean = _strip_inline_code(scan_line)
    prose = _punctuation_prose_part(path, clean)
    texts = {"clean": clean, "prose": prose}
    rows = [
        _finding("punctuation", rule, line_number, detail + path, force, line, action)
        for target, regexes, rule, force, detail, action in PUNCTUATION_RULES
        if texts[target] and any(regex.search(texts[target]) for regex in regexes)
    ]
    if prose and COMMA_SPLICE_RE.search(prose) and not SEMICOLON_SPLICE_RE.search(prose):
        rows.append(_finding(
            "punctuation",
            "comma_splice",
            line_number,
            "Comma may splice two clauses in " + path,
            False,
            line,
            "Use a period or add a conjunction if both sides stand alone.",
        ))
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
                True,
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
    (SKIP_TEST_RE, "skipped_test",
     "Skipped test in ", "Enable the test or remove it."),
)


def _comment_body_rows(path: str, line_number: int, line: str) -> list[dict]:
    body = COMMENT_RE.match(line)
    if not body:
        return []
    text = body.group(1).strip()
    rows = []
    if VC_COMMENT_RE.match(text):
        rows.append(_finding(
            "clean_code",
            "version_control_comment",
            line_number,
            "Comment narrates change history in " + path,
            True,
            line,
            "Delete it. Put change history in the commit message.",
        ))
    if len(text) > 150:
        rows.append(_finding(
            "clean_code",
            "long_comment",
            line_number,
            "Long comment in " + path,
            True,
            line,
            "Keep only one terse reason or move prose to docs.",
        ))
    return rows


def _scan_clean_code(path: str, line_number: int, line: str) -> list[dict]:
    rows = [
        _finding("clean_code", rule, line_number, detail + path, True, line, action)
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
            True,
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
        if body and body.group(1).strip():
            run.append((number, line))
            continue
        _flush_comment_run(path, run, findings)
        run = []
    _flush_comment_run(path, run, findings)
    return findings


def _scan_docstrings(path: str, text: str) -> list[dict]:
    if not path.lower().endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    findings: list[dict] = []
    scopes = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for scope in scopes:
        if not scope.body:
            continue
        first = scope.body[0]
        value = getattr(first, "value", None)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if "\n" not in value.value.strip():
            continue
        line = getattr(first, "lineno", 1)
        findings.append(_finding(
            "clean_code",
            "docstring_narration",
            line,
            "Multi-line docstring narrates in " + path,
            True,
            value.value,
            "Move the explanation to a wiki page. Create one or update the existing page.",
        ))
    return findings


def _scan_lengths(path: str, text: str, lines: list[str], config: dict) -> list[dict]:
    findings: list[dict] = []
    warn = _int_setting(config, "file_warn_lines", "CLEANCODER_FILE_WARN_LINES", 500)
    hard = _int_setting(config, "file_block_lines", "CLEANCODER_FILE_BLOCK_LINES", 1000)
    func_limit = _int_setting(config, "function_block_lines", "CLEANCODER_FUNC_BLOCK_LINES", 80)
    count = len(lines)
    if count >= hard:
        findings.append(_finding(
            "clean_code",
            "file_too_long",
            1,
            "File is over the hard length cap in " + path,
            True,
            path,
            "Split this file into focused modules.",
        ))
    elif count >= warn:
        findings.append(_finding(
            "clean_code",
            "file_getting_long",
            1,
            "File is past the warning length in " + path,
            False,
            path,
            "Plan a split before this file reaches the hard cap.",
        ))
    if not path.lower().endswith(".py"):
        return findings
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            if span > func_limit:
                findings.append(_finding(
                    "clean_code",
                    "function_too_long",
                    node.lineno,
                    "Function is over the length cap in " + path,
                    True,
                    node.name,
                    "Extract helpers until each function does one thing.",
                ))
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
        if "pass" in stripped.lower():
            index += 1
            continue
        block, next_index = _test_block(lines, index)
        if block and not any(ASSERT_RE.search(part) for part in block):
            findings.append(_finding(
                "clean_code",
                "hollow_test",
                index + 1,
                "Test body has no assertion in " + path,
                True,
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
    index = start + 1
    while index < len(lines):
        body.append(lines[index])
        if lines[index].strip().startswith(("}", "});", "})")):
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
        True,
        line,
        "Move the explanation to a wiki page. Create one or update the existing page.",
    ))


def _looks_like_empty_test(line: str) -> bool:
    stripped = line.strip()
    if not re.match(r"(def|function|it|test)\b.*\btest", stripped, re.IGNORECASE):
        return False
    return "pass" in stripped.lower() and not ASSERT_RE.search(stripped)


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
    if _is_prose(path) or _is_config(path):
        return line
    leading = COMMENT_RE.match(line)
    if leading:
        return leading.group(1)
    positions = [pos for pos in (line.find("#"), line.find("//")) if pos >= 0]
    if not positions:
        return ""
    pos = min(positions)
    return line[pos + (2 if line.startswith("//", pos) else 1):]


def _int_setting(config: dict, key: str, env_name: str, default: int) -> int:
    raw = config.get(key, os.environ.get(env_name, default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
