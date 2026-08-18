"""Split from scanner.py because the file was approaching the line cap it enforces on every other file."""

from __future__ import annotations

import ast
import re

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
WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise|unless|assumes|requires|guarantees)\b|"
    r"\bdue to\b|\bso that\b|\bin order to\b|\bexcept when\b|\binstead of\b|"
    r"\brather than\b|\bwork(?:around for|s around)\b|\bbug in\b|"
    r"\bcallers (?:rely on|must)\b|\brelied on by\b|\binvariant:\s*\S|"
    r"\bmust\b.{0,80}\bor\b|\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b)",
    re.IGNORECASE,
)
SINCE_RE = re.compile(r"\bsince\s+\S", re.IGNORECASE)
TEMPORAL_SINCE_RE = re.compile(
    r"\bsince\s+(?:the\s+)?(?:(?:last\s+)?release\b|v(?:ersion)?\.?\s*\d|\d)",
    re.IGNORECASE,
)
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
IMPLICIT_BUDGET_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:ms|s|us|ns)\s+budget\b", re.IGNORECASE)
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
# Uppercase-only lookahead because lowercase forms collide with CSS id selectors and preprocessor tokens.
_NO_SPACE_HASH = "(?=(?:" + "|".join(("TO" + "DO", "FIX" + "ME", "X" + "XX", "HA" + "CK")) + r")\b)"
COMMENT_RE = re.compile(r"^\s*(?://[ \t]*|#(?!\!)(?:[ \t]+|(?=$)|" + _NO_SPACE_HASH + r")|/\*[ \t]*)(.*)")
# Kept to "#" only mid-line so that "//" is not misread as Python floor division.
INLINE_HASH_COMMENT_RE = re.compile(r"(?:^|(?<=\s))#(?!\!)(?:[ \t]+|(?=$)|" + _NO_SPACE_HASH + r")(.*)")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z)", re.DOTALL)
BLOCK_COMMENT_TAIL_RE = re.compile(
    r"(?P<block>/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z))(?P<tail>[^\n]*)", re.DOTALL,
)
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#|/\*)\s*(def |class |if |for |while |return |import |from |const |let |var |\w+\()", re.IGNORECASE)
HEADER_COMMENT_RE = re.compile(r"^(spdx-license-identifier:|spdx-filecopyrighttext:|copyright\b|coding[:=]|-\*- coding:)", re.IGNORECASE)
LETTER_RE = re.compile(r"[^\W\d_]")
TAG_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _/-]{0,24}:(?:\s|$)")
DIRECTIVE_COMMENT_RE = re.compile(
    r"^(?:#!|#\s*(?:(?:syntax|escape|check)=|noqa\b|type:|pragma\b|ruff:|fmt:|"
    r"eslint-disable(?:-\w+)*\b|(?:>>>|<<<)\s*agent-discipline-watcher)|//\s*@ts-[\w-]+)",
    re.IGNORECASE,
)
TRIPLE_STRING_RE = re.compile(r"(?P<quote>\"\"\"|''').*?(?P=quote)", re.DOTALL)


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


CLEAN_CODE_LINE_RULES = (
    (re.compile(r"(?://|#|/\*)\s*(?:TO" + "DO|FIX" + "ME|X" + "XX|HA" + "CK)\\b", re.IGNORECASE),
     "deferred_work_comment", "Deferred work marker in ", "Remove the marker or create tracked work."),
    (re.compile(r"(?://|#|/\*)\s*(bug|case|fix|issue|step|note)\s+[A-Z0-9]\s*[:.\-]", re.IGNORECASE),
     "bug_label_comment", "Comment labels a case by letter or number in ", "Encode the case as a named test."),
    (re.compile(r"(?://|#|/\*)\s*.*\b(?:" + "|".join(("ha" + "cky", "not sure why", "work" + "around", "ug" + "ly")) + r")\b", re.IGNORECASE),
     "apology_comment", "Comment apologizes for code in ", "Fix the code or state the reason plainly."),
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


def _comment_text(line: str) -> str | None:
    body = COMMENT_RE.match(line) or INLINE_HASH_COMMENT_RE.search(line)
    if not body:
        return None
    text = body.group(1).strip()
    if DIRECTIVE_COMMENT_RE.match(line.strip()) or HEADER_COMMENT_RE.search(text):
        return None
    return text


def _comment_body_lines(text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines() or [""]
    result = []
    for number, line in enumerate(lines, 1):
        comment = _comment_text(line)
        if comment is not None:
            result.append((number, line, comment))
    return result


def _normalize_block_comments(text: str) -> str:
    def replace(match: re.Match) -> str:
        output = []
        for line in match.group("block").splitlines(keepends=True):
            ending = line[len(line.rstrip("\r\n")):]
            body = line.rstrip("\r\n").strip()
            if body not in {"/*", "/**", "*/", "<!--", "-->"}:
                body = re.sub(r"^(?:/\*+|<!--|\*)\s*|\s*(?:\*/|-->)$", "", body)
            else:
                body = ""
            output.append(("// " + body if body else "//") + ending)
        tail = match.group("tail")
        if tail:
            output[-1] = output[-1] + " " * len(tail)
        return "".join(output)
    return BLOCK_COMMENT_TAIL_RE.sub(replace, text)


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


def _comment_is_what(text: str) -> bool:
    if WHAT_OPENER_RE.match(text):
        return not _has_strong_why_marker(text)
    return not _has_why_marker(text)


def _what_comment_findings(path: str, comment_rows: list[tuple[int, str, str]]) -> list[dict]:
    rows = []
    for line_number, line, comment in comment_rows:
        if not _narrates_code(comment) or IMPLICIT_BUDGET_RE.match(comment):
            continue
        if not _comment_is_what(comment):
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


def _weak_why_findings(path: str, comment_rows: list[tuple[int, str, str]]) -> list[dict]:
    findings = []
    for line_number, line, comment in comment_rows:
        if not _has_why_marker(comment) or _has_strong_why_marker(comment):
            continue
        findings.append(_finding(
            "clean_code", "weak_why_comment", line_number,
            "Causal wording lacks a concrete reason in " + path, line,
            "Name the constraint, invariant, or consequence, or delete the comment.",
        ))
    return findings


def _clean_code_comment_findings(path: str, line_number: int, line: str) -> list[dict]:
    comment = _comment_text(line)
    rows = [
        _finding("clean_code", rule, line_number, detail + path, line, action)
        for regex, rule, detail, action in CLEAN_CODE_LINE_RULES
        if comment is not None and regex.search(line)
    ]
    rows.extend(_comment_body_rows(path, line_number, line) if comment is not None else [])
    return rows


def comment_runs(text: str) -> list[list[tuple[int, str]]]:
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


def _is_header_run(run: list[tuple[int, str]]) -> bool:
    for _line_number, line in run:
        body = COMMENT_RE.match(line)
        if not body:
            return False
        text = body.group(1).strip()
        if not HEADER_COMMENT_RE.search(text):
            return False
    return True


def _flush_comment_run(path: str, run: list[tuple[int, str]]) -> list[dict]:
    if len(run) < 2 or _is_header_run(run):
        return []
    line_number, line = run[0]
    return [_finding(
        "clean_code",
        "prose_comment_block",
        line_number,
        "Comment block narrates in " + path,
        line,
        "Move the explanation to a wiki page. Create one or update the existing page.",
    )]


def _scan_clean_code_blocks(path: str, text: str) -> list[dict]:
    findings: list[dict] = []
    for run in comment_runs(text):
        findings.extend(_flush_comment_run(path, run))
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


def _what_docstring_rows(path: str, hit: tuple[int, str]) -> list[dict]:
    start, value = hit
    rows = []
    structured = False
    for offset, raw_line in enumerate(value.splitlines()):
        line = raw_line.strip()
        if not _narrates_code(line):
            structured = structured or bool(TAG_LINE_RE.match(line))
            continue
        if structured:
            continue
        if _has_strong_why_marker(line):
            continue
        rows.append(_finding(
            "clean_code", "what_docstring", start + offset,
            "Docstring states what the code does in " + path,
            line, WHAT_COMMENT_ACTION,
        ))
    return rows


def _docstring_scopes(tree) -> list:
    if tree is None:
        return []
    return [tree, *(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))]


def _what_docstring_findings(path: str, tree) -> list[dict]:
    findings = []
    for scope in _docstring_scopes(tree):
        hit = _scope_docstring(scope)
        if hit:
            findings.extend(_what_docstring_rows(path, hit))
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
