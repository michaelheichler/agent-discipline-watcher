"""Split from scanner.py because the file was approaching the line cap it enforces on every other file."""

from __future__ import annotations

import ast
import re
from pathlib import PurePath

from .findings import Finding, spanning
from .slop_phrase import EnglishRule, PhraseFamily, _literal_office_idiom

WHY_RULE_IS_HEURISTIC = (
    "The WHY and WHAT split is a lexical heuristic, not semantic analysis. "
    "A WHAT comment with a marker can pass, and a genuine WHY comment without one can be blocked. "
    "Its deliberate bias toward over-blocking matches the hard-block policy with no exceptions."
)
# Require the comma because bare so also modifies adjectives.
CONSEQUENCE_SO = r",\s+so\s+(?!that\b)(?=\S)"
STRONG_WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise)\b|\bdue to\b|\bso that\b|\bin order to\b|"
    r"\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b|" + CONSEQUENCE_SO + ")",
    re.IGNORECASE,
)
CAUSAL_REASON_RE = re.compile(
    r"(?:^why:|\b(?:because|otherwise)\b|\bdue to\b|\bso that\b|\bin order to\b|"
    r"\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b|" + CONSEQUENCE_SO + r")\s*(?P<reason>.+)$",
    re.IGNORECASE,
)
VAGUE_REASON_RE = re.compile(r"^(?:yes|no|reason|reasons|needed|necessary|stuff|things|logic)[.!]?$", re.IGNORECASE)
GENERIC_REASON_WORDS = frozenset({"break", "breaks", "needed", "necessary", "reason", "reasons"})
WHY_COMMENT_RE = re.compile(
    r"(?:^why:\s*\S|\b(?:because|otherwise|unless)\b|"
    r"\bdue to\b|\bso that\b|\bin order to\b|\bexcept when\b|\binstead of\b|"
    r"\brather than\b|\bwork(?:around for|s around)\b|\bbug in\b|"
    r"\bcallers (?:rely on|must)\b|\brelied on by\b|\binvariant:\s*\S|"
    r"\bmust\b.{0,80}\bor\b|\bto (?:avoid|prevent|ensure|preserve|keep|allow|support)\b|" + CONSEQUENCE_SO + ")",
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
COMMENT_CHAR_CAP = 80
WHAT_COMMENT_ACTION = (
    "Only WHY comments are allowed. WHAT comments are never allowed. "
    "State the reason with because, otherwise, so that, or a `, so` clause, or delete the comment. "
    "Open with the reason, not with a subject and a verb that describe the code."
)
VC_COMMENT_RE = re.compile(
    r"^\s*(changed?|renamed?|moved?|removed?|added?|replaced?|refactored?|"
    r"fixed|reverted?|updated?|was)\b.{0,60}?\b("
    r"to|from|into|with|previously|used to|formerly|instead of)\b",
    re.IGNORECASE,
)
# Because lowercase collides with CSS and preprocessing, require uppercase tags.
_NO_SPACE_HASH = "(?=(?:" + "|".join(("TO" + "DO", "FIX" + "ME", "X" + "XX", "HA" + "CK")) + r")\b)"
COMMENT_RE = re.compile(r"^\s*(?:///?[ \t]*|#(?!\!)(?:[ \t]+|(?=$)|" + _NO_SPACE_HASH + r")|/\*[ \t]*)(.*)")
# Kept to "#" only mid-line so that "//" is not misread as Python floor division.
INLINE_HASH_COMMENT_RE = re.compile(r"(?:^|(?<=\s))#(?!\!)(?:[ \t]+|(?=$)|" + _NO_SPACE_HASH + r")(.*)")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z)", re.DOTALL)
BLOCK_COMMENT_TAIL_RE = re.compile(
    r"(?P<block>/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z))(?P<tail>[^\n]*)", re.DOTALL,
)
# Because shell globs lack closers, do not consume them as comment blocks.
SHELL_GLOB_COLLISION_EXTS = frozenset({".sh", ".bash", ".zsh", ".ksh"})
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#|/\*)\s*(def |class |if |for |while |return |import |from |const |let |var |\w+\()", re.IGNORECASE)
HEADER_COMMENT_RE = re.compile(r"^(spdx-license-identifier:|spdx-filecopyrighttext:|copyright\b|coding[:=]|-\*- coding:)", re.IGNORECASE)
LETTER_RE = re.compile(r"[^\W\d_]")
TAG_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _/-]{0,24}:(?:\s|$)")
STRUCTURED_TAG_RE = re.compile(r"^(?:why|invariant):\s*\S", re.IGNORECASE)
TOOL_CODE_PREFIX_RE = re.compile(r"^(?:[A-Za-z]{1,6}\d{1,4}(?:[\s,]+|$))+")
SECTION_LABEL_RE = re.compile(
    r"^(?:args|arguments|parameters|params|keyword args|returns?|yields?|raises?|attributes|examples?|see also):$",
    re.IGNORECASE,
)
TS_DIRECTIVE = r"@ts-(?:ignore|expect-error|nocheck|check)"
# Tight anchors, because prose could hide behind a prefix.
_TOOL_DIRECTIVE_PATTERNS = (
    r"//\s*swift-tools-version:[ \t]*\d+(?:\.\d+){0,2}(?:-[a-z0-9]+)?$",
    r"//\s*swiftlint:(?:disable|enable)(?::(?:next|this|previous))?(?:\s+[a-z][a-z0-9_]*){0,5}$",
    r"//\s*(?-i:MARK):[ \t]*(?:-[ \t]*)?(?:[^.]|\.(?=\S)){0,40}$",
    r"//go:(?:build|generate|embed|linkname|noinline|nosplit|noescape|norace|nocheckptr|nowritebarrier|"
    r"nowritebarrierrec|yeswritebarrierrec|uintptrescapes|systemstack|notinheap|debug|wasmimport|"
    r"wasmexport|fix|cgo_[a-z_]+)(?=\s|$)",
    r"//nolint(?::[\w-]+(?:,[\w-]+)*)?$",
    r"//\s*eslint-(?:disable(?:-(?:next-)?line)?|enable)(?:\s+[\w@/-]+(?:\s*,\s*[\w@/-]+)*)?$",
    r"//\s*prettier-ignore$",
    r"///\s*<reference(?:\s+[\w-]+=(?:\"[^\"]*\"|'[^']*'|(?=\s)|(?=/>))){1,3}\s*/>$",
    r"//\s*" + TS_DIRECTIVE + "$",
)
_HASH_TOOL_DIRECTIVE_PATTERNS = (
    r"#\s*noqa(?::\s*[a-z]+\d+(?:[\s,]+[a-z]+\d+)*)?$",
    r"#\s*type:\s*ignore(?:\[[\w\s,.-]+\])?$",
    r"#\s*pragma:\s*(?:no\s+(?:cover|branch)|allowlist\s+(?:nextline-)?secret)$",
    r"#\s*ruff:\s*noqa(?::\s*[a-z]+\d+(?:[\s,]+[a-z]+\d+)*)?$",
    r"#\s*fmt:\s*(?:off|on|skip)$",
    r"#\s*pylint:\s*(?:disable|enable)(?:-next)?=[\w-]+(?:\s*,\s*[\w-]+)*$",
    r"#\s*pyright:\s*(?:basic|standard|strict|ignore(?:\[[\w\s,.-]+\])?)$",
    r"#\s*mypy:\s*[\w-]+(?:=[\w\"',.-]+)?$",
    r"#\s*isort:\s*(?:skip(?:_file)?|off|on|split)$",
    r"#\s*syntax=\S+$",
    r"#\s*escape=[\\`]$",
    r"#\s*check=[\w=,;]+$",
    r"#\s*(?:>>>|<<<)\s*agent-discipline-watcher(?:\s*(?:>>>|<<<))?$",
)
DIRECTIVE_COMMENT_RE = re.compile(
    r"^(?:#!|" + "|".join(_HASH_TOOL_DIRECTIVE_PATTERNS + _TOOL_DIRECTIVE_PATTERNS) + ")",
    re.IGNORECASE,
)
TS_REASON_RE = re.compile(r"^" + TS_DIRECTIVE + r"\s+(?=\S)", re.IGNORECASE)
INLINE_DIRECTIVE_SPLIT_RE = re.compile(r"\s+#\s*")
TRIPLE_STRING_RE = re.compile(r"(?P<quote>\"\"\"|''').*?(?P=quote)", re.DOTALL)


DEFERRED_WORK_TAGS = "|".join(("TO" + "DO", "FIX" + "ME", "X" + "XX", "HA" + "CK"))
# Tag lines skip two rules because one finding is enough.
DEFERRED_TAG_RE = re.compile(r"^(?:" + DEFERRED_WORK_TAGS + r")\b:?[ \t]*", re.IGNORECASE)
CLEAN_CODE_LINE_RULES = (
    (re.compile(r"(?://|#|/\*)\s*(?:" + DEFERRED_WORK_TAGS + r")\b", re.IGNORECASE),
     "deferred_work_comment", "Deferred work marker in ", "Remove the marker or create tracked work.", "comment"),
    (re.compile(r"(?://|#|/\*)\s*(bug|case|fix|issue|step|note)\s+[A-Z0-9]\s*[:.\-]", re.IGNORECASE),
     "bug_label_comment", "Comment labels a case by letter or number in ", "Encode the case as a named test.", "comment"),
    (re.compile(r"(?://|#|/\*)\s*.*\b(?:" + "|".join(("ha" + "cky", "not sure why", "work" + "around", "ug" + "ly")) + r")\b", re.IGNORECASE),
     "apology_comment", "Comment apologizes for code in ", "Fix the code or state the reason plainly.", "comment"),
    (COMMENTED_CODE_RE, "commented_code",
     "Commented code remains in ", "Delete the commented code.", "code"),
)


COMMENT_BODY_RULES = (
    (lambda text: bool(VC_COMMENT_RE.match(text)), "version_control_comment",
     "Comment narrates change history in ", "Delete it. Put change history in the commit message."),
    (lambda text: len(text) > COMMENT_CHAR_CAP, "long_comment",
     "Long comment in ", f"Cut it to one terse reason of at most {COMMENT_CHAR_CAP} characters, or move it to the wiki."),
    (lambda text: bool(re.match(r"^(?:now(?:\s+we)?|this\s+(?:function|method|class))\b", text, re.IGNORECASE)),
     "narration_comment", "Comment narrates code in ", "Delete it and let names and structure carry the intent."),
)


READABILITY_RULES = (
    EnglishRule(PhraseFamily.compile(
        r"\b(?:hope this helps|let me know if you (?:need anything else|have any questions)|"
        r"feel free to (?:ask|reach out)|happy to (?:help|clarify|assist)|"
        r"in short,? (?:that|this) (?:is|was)|to (?:wrap|sum) (?:things |it |this )?up|"
        r"and there you have it)\b",
    ), "ai_closer", "End when the answer is done."),
    EnglishRule(PhraseFamily.compile(
        r"^\s*(?:(?:great question|to answer your question|looking at your)\b|sure!|"
        r"(?:hello|hi|hey|welcome)(?: there| again| back)?(?=[,!:]|$)|thanks? (?:you )?for (?:asking|the question)\b)",
    ), "greeting_opener", "Start with the answer."),
    EnglishRule(PhraseFamily.compile(
        r"\b(?:could|may|might|should|would)\s+(?:perhaps|possibly|potentially|probably)\b|"
        r"\b(?:perhaps|possibly|potentially|probably)\b[^.!?;,\n]{0,100}?"
        r"\b(?:could|may|might|should|would|perhaps|possibly|potentially|probably)\b",
    ), "hedge_stack", "Keep one hedge or state the fact."),
    EnglishRule(PhraseFamily.compile(
        r"\b(?:circl(?:e|es|ed|ing) back|touch(?:es|ed|ing)? base|get(?:s|ting)? the ball rolling|"
        r"on the same page|low-hanging fruit|mov(?:e|es|ed|ing) the needle|boil(?:s|ed|ing)? the ocean|"
        r"get(?:s|ting)? (?:everyone|the team|us) aligned|reconnect(?:s|ed|ing)? on|"
        r"gain(?:s|ed|ing)? traction)\b",
        literal=_literal_office_idiom,
    ), "corporate_idiom", "Name the literal action."),
)


def _inline_directive(text: str) -> bool:
    return all(DIRECTIVE_COMMENT_RE.match("# " + part) for part in INLINE_DIRECTIVE_SPLIT_RE.split(text))


def _comment_text(line: str) -> str | None:
    leading = COMMENT_RE.match(line)
    body = leading or INLINE_HASH_COMMENT_RE.search(line)
    if not body:
        return None
    text = body.group(1).strip()
    if DIRECTIVE_COMMENT_RE.match(line.strip()) or HEADER_COMMENT_RE.search(text):
        return None
    if not leading and _inline_directive(text):
        return None
    return TS_REASON_RE.sub("", text, count=1)


def _comment_body_lines(text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines() or [""]
    result = []
    for number, line in enumerate(lines, 1):
        comment = _comment_text(line)
        if comment is not None:
            result.append((number, line, comment))
    return result


def _normalize_block_comments(text: str, path: str = "") -> str:
    if path and PurePath(path.lower()).suffix in SHELL_GLOB_COLLISION_EXTS:
        return text
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
    if PurePath(path.lower()).suffix in SHELL_GLOB_COLLISION_EXTS:
        return []
    return [
        spanning(Finding(family="comment", rule="prose_comment_block", line=text.count("\n", 0, match.start()) + 1, detail="Comment block narrates in " + path, force=True, snippet=(match.group(0).splitlines()[0]).strip()[:180], action="Keep one strict WHY line or delete the comment.", path=None, severity=None, tool_use_id=None).to_dict(), text.count("\n", 0, match.end() - 1) + 1)
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


def _tag_body(text: str) -> str:
    match = TAG_LINE_RE.match(text)
    return TOOL_CODE_PREFIX_RE.sub("", text[match.end():].strip()) if match else text


def _narrates_code(text: str) -> bool:
    if not text or not LETTER_RE.search(text):
        return False
    if DEFERRED_TAG_RE.match(text) or STRUCTURED_TAG_RE.match(text):
        return False
    return bool(LETTER_RE.search(_tag_body(text)))


def _identifier_tokens(parts) -> frozenset[str]:
    if isinstance(parts, str):
        parts = (parts,)
    return frozenset(
        token.lower()
        for part in parts
        for token in IDENTIFIER_PART_RE.findall(str(part).replace("_", " "))
        if token.lower() not in CONTENT_STOPWORDS
    )


# Because bare participles state decisions, flag third person and gerunds.
NARRATION_OPENER_RE = re.compile(
    r"^(?:[A-Za-z]+(?:s|ing))\s+"
    r"(?:the|a|an|it|this|to|into|out|off|from|by|on|as|every|each|one|two|all)\b",
)
# Because adding a subject hides the same narration, check subject openers too.
SUBJECT_OPENER_RE = re.compile(
    r"^(?:The|A|An|This|That|Each|Every|One|Its)\s+"
    r"(?:[a-z][a-z-]*\s+){0,2}"
    r"(?:is|are|was|were|[a-z]+(?:s|ed|ing))\b",
)


_FUNCTION_WORD = (
    r"(?!(?i:instead|of|to|for|in|on|at|by|with|from|into|as|and|or|but|not|so|if|when|then|than|that|which|"
    r"because|otherwise|unless|since|until|after|before|while|only|also|never|always|just)\b)"
)
_IMPERATIVE_WORD = (
    r"(?!(?i:keep|skip|use|pass|drop|add|make|take|put|give|treat|avoid|prefer|wait|retry|leave|reject|allow|"
    r"ignore|strip|fail|stop|start|force|pin|clamp|ensure|prevent|preserve|reuse|bypass|defer|count|send|read|"
    r"write|set|hold|return|call|run|check|load|open|close|match|trim|sort|join|split|wrap|copy|build|let)\b)"
)
# Because an article drop hid the narration, a bare subject needs its own test.
BARE_SUBJECT_OPENER_RE = re.compile(
    r"^" + _FUNCTION_WORD + _IMPERATIVE_WORD + r"[A-Za-z][A-Za-z-]*(?:\s+" + _FUNCTION_WORD + r"[a-z][a-z-]*){0,2}"
    r"\s+[a-z]{2,}[a-rt-z]s\s+(?:the|an?|it|its|each|every|all|any|one|two|three|no|both|"
    r"their|his|her|\d+)\b",
)


def opens_with_narration(text: str) -> bool:
    stripped = text.strip()
    return bool(
        NARRATION_OPENER_RE.match(stripped) or SUBJECT_OPENER_RE.match(stripped) or BARE_SUBJECT_OPENER_RE.match(stripped)
    )


def states_why(text: str) -> bool:
    return _has_strong_why_marker(text) and not opens_with_narration(text)


def _comment_is_what(text: str) -> bool:
    body = _tag_body(text)
    if WHAT_OPENER_RE.match(body) or opens_with_narration(body):
        return not states_why(body)
    return not _has_why_marker(body)


def _what_comment_findings(path: str, comment_rows: list[tuple[int, str, str]]) -> list[dict]:
    rows = []
    for line_number, line, comment in comment_rows:
        if not _narrates_code(comment) or IMPLICIT_BUDGET_RE.match(comment):
            continue
        if not _comment_is_what(comment):
            continue
        rows.append(Finding(family="comment", rule="what_comment", line=line_number, detail="Comment states what the code does in " + path, force=True, snippet=(line).strip()[:180], action=WHAT_COMMENT_ACTION, path=None, severity=None, tool_use_id=None).to_dict())
    return rows


def _comment_body_rows(path: str, line_number: int, line: str) -> list[dict]:
    text = _comment_text(line)
    if text is None:
        return []
    rows = [
        Finding(family="comment", rule=rule, line=line_number, detail=detail + path, force=True, snippet=(line).strip()[:180], action=action, path=None, severity=None, tool_use_id=None).to_dict()
        for matches, rule, detail, action in COMMENT_BODY_RULES
        if matches(text)
    ]
    rows.extend(
        Finding(family="comment", rule=rule, line=line_number, detail="Readable comment rule in " + path, force=True, snippet=(line).strip()[:180], action=action, path=None, severity=None, tool_use_id=None).to_dict()
        for family, rule, action in READABILITY_RULES
        if any(pattern.search(text) for pattern in family.patterns)
    )
    return rows


def _weak_why_findings(path: str, comment_rows: list[tuple[int, str, str]]) -> list[dict]:
    findings = []
    for line_number, line, comment in comment_rows:
        label = bool(re.match(r"^(?:[A-Z](?:\d+)?\s*:|just in case[.!]?$)", comment, re.I))
        if not label and (not _has_why_marker(comment) or _has_strong_why_marker(comment)):
            continue
        findings.append(Finding(family="comment", rule="weak_why_comment", line=line_number, detail="Causal wording lacks a concrete reason in " + path, force=True, snippet=(line).strip()[:180], action="Name the constraint, invariant, or consequence, or delete the comment.", path=None, severity=None, tool_use_id=None).to_dict())
    return findings


def scan_comment_line(path: str, line_number: int, line: str, active: frozenset[str]) -> list[dict]:
    if _comment_text(line) is None:
        return []
    rows = [
        Finding(family=family, rule=rule, line=line_number, detail=detail + path, force=True, snippet=(line).strip()[:180], action=action, path=None, severity=None, tool_use_id=None).to_dict()
        for regex, rule, detail, action, family in CLEAN_CODE_LINE_RULES
        if family in active and regex.search(line)
    ]
    rows.extend(_comment_body_rows(path, line_number, line) if "comment" in active else [])
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
    return [spanning(Finding(family="comment", rule="prose_comment_block", line=line_number, detail="Comment block narrates in " + path, force=True, snippet=(line).strip()[:180], action="Move the explanation to a wiki page. Create one or update the existing page.", path=None, severity=None, tool_use_id=None).to_dict(), run[-1][0])]


def _scan_comment_blocks(path: str, text: str) -> list[dict]:
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


def _structured_api_docstring(value: str) -> bool:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or not states_why(lines[0]):
        return False
    section = False
    for line in lines[1:]:
        if SECTION_LABEL_RE.match(line) or re.match(r"^(?:Raises?|Returns?|Yields?)\s+\S", line):
            section = True
        elif not section:
            return False
    return section


def _narrating_docstring(scope) -> tuple[int, str] | None:
    hit = _scope_docstring(scope)
    if not hit or "\n" not in hit[1].strip() or _structured_api_docstring(hit[1]):
        return None
    return hit


def _what_docstring_rows(path: str, hit: tuple[int, str]) -> list[dict]:
    start, value = hit
    rows = []
    structured = False
    for offset, raw_line in enumerate(value.splitlines()):
        line = raw_line.strip()
        if offset > 0 and (SECTION_LABEL_RE.match(line) or re.match(r"^(?:Raises?|Returns?|Yields?)\s+\S", line)):
            structured = True
        if not _narrates_code(line):
            structured = structured or bool(SECTION_LABEL_RE.match(line))
            continue
        if structured:
            continue
        if states_why(_tag_body(line)):
            continue
        rows.append(Finding(family="comment", rule="what_docstring", line=start + offset, detail="Docstring states what the code does in " + path, force=True, snippet=(line).strip()[:180], action=WHAT_COMMENT_ACTION, path=None, severity=None, tool_use_id=None).to_dict())
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
            findings.append(spanning(Finding(family="comment", rule="docstring_narration", line=narration[0], detail="Multi-line docstring narrates in " + path, force=True, snippet=(narration[1]).strip()[:180], action="Keep one strict WHY line or delete the docstring.", path=None, severity=None, tool_use_id=None).to_dict(), getattr(scope.body[0], "end_lineno", None)))
    return findings


def _lexical_docstring_findings(path: str, text: str) -> list[dict]:
    findings = []
    for match in TRIPLE_STRING_RE.finditer(text):
        value = match.group(0)[3:-3]
        if "\n" not in value.strip() or _structured_api_docstring(value):
            continue
        line = text.count("\n", 0, match.start()) + 1
        before = [row.strip() for row in text[:match.start()].splitlines() if row.strip()]
        if before and not _lexical_scope_header(before):
            continue
        findings.append(spanning(Finding(family="comment", rule="docstring_narration", line=line, detail="Multi-line docstring narrates in " + path, force=True, snippet=(value).strip()[:180], action="Keep one strict WHY line or delete the docstring.", path=None, severity=None, tool_use_id=None).to_dict(), text.count("\n", 0, match.end() - 1) + 1))
    return findings


def scan_comment_contract(path: str, source: str, tree: ast.Module | None, original: str) -> list[dict]:
    """Keep contract passes together because source masking must not change comment ownership."""
    findings = _multiline_comment_findings(path, source)
    normalized = _normalize_block_comments(source, path)
    comments = _comment_body_lines(normalized)
    findings.extend(_what_comment_findings(path, comments))
    findings.extend(_what_docstring_findings(path, tree))
    findings.extend(_scan_comment_blocks(path, normalized))
    findings.extend(_scan_docstrings(path, tree))
    if tree is None and path.lower().endswith(".py"):
        findings.extend(_lexical_docstring_findings(path, original))
    findings.extend(_weak_why_findings(path, comments))
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
