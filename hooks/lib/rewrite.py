"""Owns local cleanup because model hooks cannot return rewritten tool input."""
from __future__ import annotations

import ast
import copy
import re
from dataclasses import dataclass, field

try:
    # Relative first because every hook entry script imports this module as lib.rewrite, where a bare name cannot resolve.
    from . import scanner
    from .config import effective_config
except ImportError:
    import scanner
    from config import effective_config

COUNT_KEYS = ("dashes", "prose", "comments", "sentences", "lists", "weak_why", "apostrophes")
DELETE_COMMENT_RULES = frozenset({
    "deferred_work_comment", "bug_label_comment", "apology_comment", "commented_code",
    "version_control_comment", "narration_comment", "what_comment",
})
PROTECTED_PROSE_RE = re.compile(r"`[^`]*`|https?://\S+", re.IGNORECASE)
DOCSTRING_QUOTE_RE = re.compile(r"(?i)(?P<prefix>[rubf]*)(?P<quote>\"\"\"|'''|\"|')")
CLAUSE_BREAK_RE = re.compile(r"(?<=\w)\s*-{2,}\s*(?=\w)|(?<=\w)\s+-\s+(?=\w)")
HTML_CODE_LINE_RE = re.compile(r"<(?:code|pre|script|style)\b", re.IGNORECASE)
BOUNDARY_RE = re.compile(r",\s+|\s+(?:and|but|because|while|which|that)\s+", re.IGNORECASE)
PLAIN_REPLACEMENTS = (
    (re.compile(r"\b(?:it is|it's) (?:important|worth) to note that\b", re.IGNORECASE), "", "throat_clearing"),
    (re.compile(r"\bit should be noted that\b", re.IGNORECASE), "", "throat_clearing"),
    (re.compile(r"\bneedless to say\b", re.IGNORECASE), "", "filler"),
    (re.compile(r"\bat the end of the day\b", re.IGNORECASE), "", "filler"),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to", "wordiness"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because", "wordiness"),
    (re.compile(r"\butili[sz]e(?:s|d)?\b", re.IGNORECASE), "use", "utilize"),
    (re.compile(r"\butili[sz]ing\b", re.IGNORECASE), "using", "utilize"),
    (re.compile(r"\bleverag(?:e|es|ed)\b", re.IGNORECASE), "use", "inflated_diction"),
    (re.compile(r"\bleveraging\b", re.IGNORECASE), "using", "inflated_diction"),
    (re.compile(r"\b(?:very|really|quite|extremely)\s+(?=\w)", re.IGNORECASE), "", "empty_intensifier"),
    (re.compile(r"\bdelve into\b", re.IGNORECASE), "examine", "ai_tell"),
)


@dataclass(frozen=True)
class TextRewrite:
    """Keeps cleanup evidence together so callers cannot report changes they did not apply."""

    text: str
    counts: dict[str, int]
    unresolved: list[dict]
    ambiguous: list[dict]
    changes: list[dict]


@dataclass(frozen=True)
class ToolRewrite:
    """Keeps the complete tool input because Claude replaces rather than merges updatedInput."""

    tool_input: dict
    counts: dict[str, int]
    unresolved: list[dict]
    ambiguous: list[dict]
    changes: list[dict]
    changed: bool


@dataclass
class _RewriteState:
    path: str
    cfg: dict
    by_line: dict[int, set[str]]
    actions: dict[str, str]
    counts: dict[str, int]
    ambiguous: list[dict]
    prose: bool
    cap: int
    run_delete_lines: frozenset[int] = frozenset()
    changes: list[dict] = field(default_factory=list)
    in_fence: bool = False


@dataclass
class _DocstringEdit:
    start: int
    end: int
    replacement: list[str]
    changes: list[dict]


def _counts() -> dict[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


def _add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key in COUNT_KEYS:
        target[key] += source.get(key, 0)


def _protect(text: str) -> tuple[str, dict[str, str]]:
    saved: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        key = f"{len(saved)}"
        saved[key] = match.group(0)
        return key

    return PROTECTED_PROSE_RE.sub(replace, text), saved


def _restore(text: str, saved: dict[str, str]) -> str:
    for key, value in saved.items():
        text = text.replace(key, value)
    return text


def _replace_dashes(text: str) -> tuple[str, int, list[str]]:
    result: list[str] = []
    changed = 0
    rules: list[str] = []
    for index, char in enumerate(text):
        if not scanner.BAD_DASH_RE.fullmatch(char):
            result.append(char)
            continue
        previous = text[index - 1] if index else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        result.append("-" if previous.isalnum() and following.isalnum() else ", ")
        changed += 1
        rules.append("banned_dash")
    return "".join(result), changed, rules


def _apply_apostrophe_substitutions(text: str) -> tuple[str, list[str]]:
    rules: list[str] = []

    def replace_pronoun(match: re.Match[str]) -> str:
        rules.append("pronoun_apostrophe")
        return match.group(1) + "s"

    text = scanner.PRONOUN_APOS_RE.sub(replace_pronoun, text)

    def replace_its(match: re.Match[str]) -> str:
        rules.append("pronoun_apostrophe")
        return "its"

    text = scanner.ITS_APOS_RE.sub(replace_its, text)

    def replace_decade(match: re.Match[str]) -> str:
        rules.append("decade_apostrophe")
        return match.group(0).replace("'s", "s")

    return scanner.DECADE_APOS_RE.sub(replace_decade, text), rules


def _normalize_visible(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r",\s*,+", ", ", text)
    return re.sub(r"\.\s*\.+", ". ", text)


def _clean_visible(text: str) -> tuple[str, int, int, list[str]]:
    protected, saved = _protect(text)
    protected, dash_count, rules = _replace_dashes(protected)
    protected, clause_count = CLAUSE_BREAK_RE.subn(", ", protected)
    rules.extend(["dash_break"] * clause_count)
    protected, semicolon_count = re.subn(r";\s*", ". ", protected)
    rules.extend(["prose_semicolon"] * semicolon_count)
    prose_count = clause_count + semicolon_count
    for pattern, replacement, rule in PLAIN_REPLACEMENTS:
        protected, count = pattern.subn(replacement, protected)
        prose_count += count
        rules.extend([rule] * count)
    protected, apostrophe_rules = _apply_apostrophe_substitutions(protected)
    rules.extend(apostrophe_rules)
    return _restore(_normalize_visible(protected).strip(), saved), dash_count, prose_count, rules


def _line_parts(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def _cut_once(text: str, cap: int, *, preserve_punctuation: bool = False) -> tuple[str, str]:
    words = list(scanner.WORD_RE.finditer(text))
    if not words:
        return text, ""
    fallback = words[cap - 1].end()
    boundaries = list(BOUNDARY_RE.finditer(text[:fallback]))
    boundary = boundaries[-1] if boundaries and boundaries[-1].start() > fallback // 2 else None
    if boundary is None:
        cut, tail = fallback, text[fallback:].lstrip()
    elif boundary.group(0).lstrip().startswith(","):
        cut = boundary.end() if preserve_punctuation else boundary.start()
        tail = text[boundary.end():].lstrip()
    else:
        cut, tail = boundary.start(), text[boundary.start():].lstrip()
    head = text[:cut].rstrip() if preserve_punctuation else text[:cut].rstrip(" ,.!?")
    return head, tail


def _split_limit(remaining: str, cap: int, char_cap: int | None) -> tuple[bool, int]:
    if char_cap is None:
        return len(scanner.WORD_RE.findall(remaining)) > cap, cap
    fitting = [word for word in scanner.WORD_RE.finditer(remaining) if word.end() <= char_cap]
    return len(remaining) > char_cap, max(1, len(fitting))


def _split_long_line(
    body: str,
    cap: int,
    *,
    char_cap: int | None = None,
    append_period: bool = True,
    preserve_punctuation: bool = False,
) -> tuple[list[str], int]:
    """Split at an existing word boundary, using either a word or character cap."""
    indent = body[: len(body) - len(body.lstrip())]
    remaining = body.strip()
    parts: list[str] = []
    while remaining:
        over_cap, word_cap = _split_limit(remaining, cap, char_cap)
        if not over_cap:
            break
        head, remaining = _cut_once(remaining, word_cap, preserve_punctuation=preserve_punctuation)
        parts.append(indent + head + ("." if append_period else ""))
    if remaining:
        parts.append(indent + remaining)
    return parts, max(0, len(parts) - 1)


def _group_lists(lines: list[str], cap: int, newline: str) -> tuple[list[str], int]:
    grouped: list[str] = []
    run = 0
    groups = 0
    for line in lines:
        body, _ = _line_parts(line)
        if not scanner.LIST_ITEM_RE.match(body):
            run = 0
            grouped.append(line)
            continue
        run += 1
        if run > cap:
            grouped.append(newline)
            run = 1
            groups += 1
        grouped.append(line)
    return grouped, groups


def _findings_by_line(findings: list[dict]) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for finding in findings:
        line, rule = finding.get("line"), finding.get("rule")
        if isinstance(line, int) and isinstance(rule, str):
            result.setdefault(line, set()).add(rule)
    return result


_ENGLISH_ACTIONS = {rule: action for _pattern, rule, action in scanner.ENGLISH_RULES}
_GENERIC_REWRITE_ACTION = "Cleaned up prose phrasing."


def _finding_actions(findings: list[dict]) -> dict[str, str]:
    return {
        finding["rule"]: finding["action"]
        for finding in findings
        if isinstance(finding.get("rule"), str) and isinstance(finding.get("action"), str)
    }


def _change(line: int, rule: str, status: str, actions: dict[str, str]) -> dict:
    action = actions.get(rule) or _ENGLISH_ACTIONS.get(rule) or _GENERIC_REWRITE_ACTION
    return {"line": line, "rule": rule, "status": status, "action": action}


def _record_rules(state: _RewriteState, line: int, rules: list[str] | set[str], status: str) -> None:
    ordered = rules if isinstance(rules, list) else sorted(rules)
    state.changes.extend(_change(line, rule, status, state.actions) for rule in ordered)


def _comment_candidate(path: str, number: int, body: str) -> dict:
    return {"path": path, "line": number, "rule": "ambiguous_comment", "snippet": body.strip()[:180]}


def _prose_comment_block_lines(path: str, text: str, cfg: dict) -> frozenset[int]:
    """Return every line in a flagged prose-comment run, not just its first finding line."""
    if scanner._is_exempt(path, cfg) or "clean_code" not in scanner._active_families(path, cfg):
        return frozenset()
    lines = text.splitlines()
    header_end = scanner._header_block_end(lines)
    flagged: set[int] = set()
    for run in scanner.comment_runs(path, text):
        if len(run) < 2 or run[-1][0] <= header_end:
            continue
        if any(scanner._has_why_marker(scanner._comment_text(line) or "") for _number, line in run):
            continue
        flagged.update(number for number, _line in run)
    return frozenset(flagged)


def _docstring_expr(scope):
    body = getattr(scope, "body", [])
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first
    return None


def _docstring_source(scope, lines: list[str]):
    expr = _docstring_expr(scope)
    if expr is None:
        return None
    start = getattr(expr, "lineno", 1)
    line = lines[start - 1] if 0 < start <= len(lines) else ""
    col_offset = getattr(expr, "col_offset", 0)
    if line[:col_offset].strip():
        return None
    end = getattr(expr, "end_lineno", start)
    source = "".join(lines[start - 1:end])
    opening = DOCSTRING_QUOTE_RE.search(source)
    if opening is None:
        return None
    quote = opening.group("quote")
    close = source.rfind(quote)
    if close <= opening.end():
        return None
    raw = source[opening.end():close]
    return expr, start, end, source, opening, quote, raw, close


def _docstring_info(scope, lines: list[str]) -> dict | None:
    data = _docstring_source(scope, lines)
    if data is None:
        return None
    expr, start, end, source, opening, quote, raw, close = data
    value = getattr(getattr(expr, "value", None), "value", None)
    if not isinstance(value, str):
        return None
    return {
        "scope": scope, "expr": expr, "start": start, "end": end, "source": source,
        "opening": source[:opening.end()], "quote": quote, "raw": raw, "value": value,
        "suffix": source[close + len(quote):], "value_lines": value.splitlines(),
        "newline": "\r\n" if "\r\n" in source else "\n",
    }


def _docstring_delete_replacement(info: dict) -> list[str]:
    base = info["source"][: len(info["source"]) - len(info["source"].lstrip())]
    scope = info["scope"]
    if isinstance(scope, ast.Module):
        return []
    if len(getattr(scope, "body", [])) != 1:
        return []
    return (base + "pass" + info["suffix"]).splitlines(keepends=True)


def _docstring_replacement(info: dict, survivors: list[str]) -> list[str]:
    rebuilt = info["newline"].join(survivors)
    if info["value"].endswith(("\n", "\r")):
        rebuilt += info["newline"]
    text = info["opening"] + rebuilt + info["quote"] + info["suffix"]
    return text.splitlines(keepends=True)


def _docstring_survivors(value_lines: list[str], dropped: set[int]) -> tuple[list[str], list[int]]:
    survivors: list[str] = []
    removed: list[int] = []
    for offset, value_line in enumerate(value_lines):
        preserve = scanner._has_why_marker(value_line.strip()) or scanner.TAG_LINE_RE.match(value_line.strip())
        if offset in dropped and not preserve:
            removed.append(offset)
        else:
            survivors.append(value_line)
    return survivors, removed


def _docstring_what_edit(
    path: str, scope, hit: tuple[int, str], info: dict, cfg: dict, actions: dict[str, str]
) -> _DocstringEdit | None:
    value_lines = info["value_lines"]
    rows = scanner._what_docstring_rows(path, scope, hit, cfg)
    if not rows:
        return None
    dropped = {
        row["line"] - hit[0]
        for row in rows
        if isinstance(row.get("line"), int) and 0 <= row["line"] - hit[0] < len(value_lines)
    }
    survivors, removed = _docstring_survivors(value_lines, dropped)
    all_removed = not any(line.strip() for line in survivors)
    replacement = _docstring_delete_replacement(info) if all_removed else _docstring_replacement(info, survivors)
    offsets = range(len(value_lines)) if all_removed else removed
    changes = [_change(info["start"] + offset, "what_docstring", "removed", actions) for offset in offsets]
    return _DocstringEdit(info["start"], info["end"], replacement, changes)


def _docstring_change(
    path: str, scope, lines: list[str], cfg: dict, actions: dict[str, str]
) -> _DocstringEdit | None:
    hit, info = scanner._scope_docstring(scope), _docstring_info(scope, lines)
    if not hit or info is None:
        return None
    if scanner._narrating_docstring(scope):
        changes = [_change(line, "docstring_narration", "removed", actions) for line in range(info["start"], info["end"] + 1)]
        return _DocstringEdit(info["start"], info["end"], _docstring_delete_replacement(info), changes)
    return _docstring_what_edit(path, scope, hit, info, cfg, actions)


def _collect_docstring_edits(path: str, text: str, cfg: dict, tree, lines: list[str]) -> list[_DocstringEdit]:
    actions = _finding_actions(scanner.scan_all(path, text, cfg))
    return [
        change
        for scope in scanner._docstring_scopes(tree)
        if (change := _docstring_change(path, scope, lines, cfg, actions)) is not None
    ]


def _apply_docstring_edits(lines: list[str], edits: list[_DocstringEdit]) -> str:
    output = list(lines)
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        output[edit.start - 1:edit.end] = edit.replacement
    return "".join(output)


def _rewrite_docstrings(path: str, text: str, cfg: dict) -> tuple[str, list[dict]]:
    """Remove narration and WHAT-only Python docstring lines, reverting on syntax risk."""
    if not path.lower().endswith(".py") or scanner._is_exempt(path, cfg):
        return text, []
    if "clean_code" not in scanner._active_families(path, cfg):
        return text, []
    tree = scanner._python_tree(path, text)
    if tree is None:
        return text, []
    lines = text.splitlines(keepends=True)
    edits = _collect_docstring_edits(path, text, cfg, tree, lines)
    if not edits:
        return text, []
    rewritten = _apply_docstring_edits(lines, edits)
    try:
        ast.parse(rewritten)
    except SyntaxError:
        return text, []
    changes = [change for edit in edits for change in edit.changes]
    return rewritten, changes


def _rewrite_prose_line(state: _RewriteState, number: int, body: str, ending: str) -> list[str]:
    if state.in_fence or body.lstrip().startswith(">") or "|" in body or HTML_CODE_LINE_RE.search(body):
        return [body + ending]
    cleaned, dashes, prose_changes, rules = _clean_visible(body)
    state.counts["dashes"] += dashes
    state.counts["prose"] += prose_changes
    state.counts["apostrophes"] += sum(rule in {"pronoun_apostrophe", "decade_apostrophe"} for rule in rules)
    _record_rules(state, number, rules, "rewritten")
    pieces, split_count = _split_long_line(cleaned, state.cap)
    state.counts["sentences"] += split_count
    if split_count:
        _record_rules(state, number, ["long_sentence"], "rewritten")
    return [piece + ending for piece in pieces]


def _clean_comment(state: _RewriteState, number: int, body: str, match) -> tuple[str, list[str]]:
    cleaned, dashes, prose_changes, rules = _clean_visible(match.group(1))
    state.counts["dashes"] += dashes
    state.counts["prose"] += prose_changes
    state.counts["apostrophes"] += sum(rule in {"pronoun_apostrophe", "decade_apostrophe"} for rule in rules)
    _record_rules(state, number, rules, "rewritten")
    return cleaned, rules


def _long_comment_parts(state: _RewriteState, number: int, cleaned: str) -> list[str] | None:
    pieces, _ = _split_long_line(cleaned, 1, char_cap=150, append_period=False, preserve_punctuation=True)
    if len(pieces) <= 1:
        return None
    _record_rules(state, number, ["long_comment"], "rewritten")
    return pieces


def _delete_comment_line(state: _RewriteState, number: int) -> list[str]:
    state.counts["comments"] += 1
    state.changes.append(_change(number, "prose_comment_block", "removed", state.actions))
    return []


def _comment_parts(body: str):
    match = scanner.COMMENT_RE.match(body)
    if not match or scanner.DIRECTIVE_COMMENT_RE.match(body.strip()):
        return None
    comment = scanner._comment_text(body)
    return (match, comment) if comment is not None else None


def _rewrite_comment_body(
    state: _RewriteState, number: int, body: str, ending: str, match, comment: str, rules: set[str]
) -> list[str]:
    if scanner._has_why_marker(comment) and not scanner._has_strong_why_marker(comment):
        state.counts["weak_why"] += 1
    elif scanner._narrates_code(comment) and not rules:
        state.ambiguous.append(_comment_candidate(state.path, number, comment))
    cleaned, visible_rules = _clean_comment(state, number, body, match)
    if not cleaned:
        state.counts["comments"] += 1
        _record_rules(state, number, visible_rules, "removed")
        return []
    pieces = _long_comment_parts(state, number, cleaned) if "long_comment" in rules or len(comment) > 150 else None
    prefix = body[:match.start(1)]
    if pieces is not None:
        return [prefix + piece + ending for piece in pieces]
    return [prefix + cleaned + ending]


def _rewrite_comment_line(state: _RewriteState, line: tuple[int, str, str]) -> list[str]:
    number, body, ending = line
    parts = _comment_parts(body)
    if parts is None:
        return [body + ending]
    match, comment = parts
    if number in state.run_delete_lines:
        return _delete_comment_line(state, number)
    rules = state.by_line.get(number, set())
    deletions = rules & DELETE_COMMENT_RULES
    if deletions and not scanner._has_why_marker(comment):
        state.counts["comments"] += 1
        _record_rules(state, number, deletions, "removed")
        return []
    return _rewrite_comment_body(state, number, body, ending, match, comment, rules)


def _rewrite_line(state: _RewriteState, number: int, line: str) -> list[str]:
    body, ending = _line_parts(line)
    if state.prose and scanner.FENCE_RE.match(body):
        state.in_fence = not state.in_fence
        return [line]
    if state.prose:
        return _rewrite_prose_line(state, number, body, ending)
    return _rewrite_comment_line(state, (number, body, ending))


def _rewrite_lines(state: _RewriteState, text: str) -> list[str]:
    output: list[str] = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        output.extend(_rewrite_line(state, number, line))
    return output


def _new_state(path: str, text: str, cfg: dict, changes: list[dict]) -> _RewriteState:
    findings = scanner.scan_all(path, text, cfg)
    return _RewriteState(
        path=path, cfg=cfg, by_line=_findings_by_line(findings), actions=_finding_actions(findings),
        counts=_counts(), ambiguous=[], prose=scanner._is_prose(path, text),
        cap=max(5, int(cfg.get("sentence_word_cap", 40))),
        run_delete_lines=_prose_comment_block_lines(path, text, cfg), changes=changes,
    )


def rewrite_text(path: str, text: str, config: dict | None = None) -> TextRewrite:
    """Rewrite visible prose and safe code comments, preserving hidden code and strings."""
    cfg = effective_config(config)
    docstring_text, docstring_changes = _rewrite_docstrings(path, text, cfg)
    state = _new_state(path, docstring_text, cfg, docstring_changes)
    output = _rewrite_lines(state, docstring_text)
    newline = "\r\n" if "\r\n" in docstring_text else "\n"
    grouped, groups = _group_lists(output, max(1, int(cfg.get("list_item_cap", 8))), newline)
    state.counts["lists"] += groups
    rewritten = "".join(grouped)
    return TextRewrite(rewritten, state.counts, scanner.scan_all(path, rewritten, cfg), state.ambiguous, state.changes)


def _rewrite_field(path: str, value: object, config: dict | None) -> TextRewrite | None:
    return rewrite_text(path, value, config) if isinstance(value, str) else None


def _tool_results(tool_name: str, updated: dict, context: tuple[str, dict | None]) -> list[TextRewrite]:
    path, config = context
    fields = {"Write": "content", "Edit": "new_string", "NotebookEdit": "new_source"}
    field = fields.get(tool_name)
    if field:
        result = _rewrite_field(path, updated.get(field), config)
        if result is not None:
            updated[field] = result.text
            return [result]
        return []
    if tool_name != "MultiEdit" or not isinstance(updated.get("edits"), list):
        return []
    results: list[TextRewrite] = []
    for edit in updated["edits"]:
        if isinstance(edit, dict) and (result := _rewrite_field(path, edit.get("new_string"), config)):
            edit["new_string"] = result.text
            results.append(result)
    return results


def rewrite_tool_input(tool_name: str, tool_input: dict, config: dict | None = None) -> ToolRewrite:
    """Copy the whole input because Claude does not merge partial updatedInput objects."""
    updated = copy.deepcopy(tool_input)
    path = str(updated.get("file_path") or updated.get("path") or updated.get("notebook_path") or "<pending>")
    results = _tool_results(tool_name, updated, (path, config))
    counts = _counts()
    for result in results:
        _add_counts(counts, result.counts)
    unresolved = [row for result in results for row in result.unresolved]
    ambiguous = [row for result in results for row in result.ambiguous]
    changes = [row for result in results for row in result.changes]
    return ToolRewrite(updated, counts, unresolved, ambiguous, changes, updated != tool_input)


def summary(counts: dict[str, int]) -> str:
    """Keep the report compact because every returned word enters the next model request."""
    labels = (
        ("dashes", "banned dashes replaced"), ("prose", "prose cuts"),
        ("comments", "comments removed"), ("sentences", "sentences split"),
        ("lists", "lists regrouped"), ("apostrophes", "apostrophes corrected"),
    )
    rows = [f"{counts.get(key, 0)} {label}" for key, label in labels if counts.get(key, 0)]
    if counts.get("weak_why", 0):
        rows.append(f"{counts['weak_why']} WHY comments need a concrete constraint or consequence")
    return "Watcher cleaned this write: " + ", ".join(rows) + "." if rows else ""
