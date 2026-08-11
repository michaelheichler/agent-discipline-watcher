"""Owns local cleanup because model hooks cannot return rewritten tool input."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

try:
    # Relative first because every hook entry script imports this module as lib.rewrite, where a bare name cannot resolve.
    from . import scanner
    from .config import effective_config
except ImportError:
    import scanner
    from config import effective_config

COUNT_KEYS = ("dashes", "prose", "comments", "sentences", "lists", "weak_why")
DELETE_COMMENT_RULES = frozenset({
    "deferred_work_comment", "bug_label_comment", "apology_comment", "commented_code",
    "version_control_comment", "narration_comment", "what_comment",
})
PROTECTED_PROSE_RE = re.compile(r"`[^`]*`|https?://\S+", re.IGNORECASE)
CLAUSE_BREAK_RE = re.compile(r"(?<=\w)\s*-{2,}\s*(?=\w)|(?<=\w)\s+-\s+(?=\w)")
HTML_CODE_LINE_RE = re.compile(r"<(?:code|pre|script|style)\b", re.IGNORECASE)
BOUNDARY_RE = re.compile(r",\s+|\s+(?:and|but|because|while|which|that)\s+", re.IGNORECASE)
PLAIN_REPLACEMENTS = (
    (re.compile(r"\b(?:it is|it's) (?:important|worth) to note that\b", re.IGNORECASE), ""),
    (re.compile(r"\bit should be noted that\b", re.IGNORECASE), ""),
    (re.compile(r"\bneedless to say\b", re.IGNORECASE), ""),
    (re.compile(r"\bat the end of the day\b", re.IGNORECASE), ""),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because"),
    (re.compile(r"\butili[sz]e(?:s|d)?\b", re.IGNORECASE), "use"),
    (re.compile(r"\butili[sz]ing\b", re.IGNORECASE), "using"),
    (re.compile(r"\bleverag(?:e|es|ed)\b", re.IGNORECASE), "use"),
    (re.compile(r"\bleveraging\b", re.IGNORECASE), "using"),
    (re.compile(r"\b(?:very|really|quite|extremely)\s+(?=\w)", re.IGNORECASE), ""),
    (re.compile(r"\bdelve into\b", re.IGNORECASE), "examine"),
)


@dataclass(frozen=True)
class TextRewrite:
    """Keeps cleanup evidence together so callers cannot report changes they did not apply."""

    text: str
    counts: dict[str, int]
    unresolved: list[dict]
    ambiguous: list[dict]


@dataclass(frozen=True)
class ToolRewrite:
    """Keeps the complete tool input because Claude replaces rather than merges updatedInput."""

    tool_input: dict
    counts: dict[str, int]
    unresolved: list[dict]
    ambiguous: list[dict]
    changed: bool


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


def _replace_dashes(text: str) -> tuple[str, int]:
    result: list[str] = []
    changed = 0
    for index, char in enumerate(text):
        if not scanner.BAD_DASH_RE.fullmatch(char):
            result.append(char)
            continue
        previous = text[index - 1] if index else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        result.append("-" if previous.isalnum() and following.isalnum() else ", ")
        changed += 1
    return "".join(result), changed


def _clean_visible(text: str) -> tuple[str, int, int]:
    protected, saved = _protect(text)
    protected, dash_count = _replace_dashes(protected)
    protected, clause_count = CLAUSE_BREAK_RE.subn(", ", protected)
    protected, semicolon_count = re.subn(r";\s*", ". ", protected)
    prose_count = clause_count + semicolon_count
    for pattern, replacement in PLAIN_REPLACEMENTS:
        protected, count = pattern.subn(replacement, protected)
        prose_count += count
    protected = re.sub(r"[ \t]+", " ", protected)
    protected = re.sub(r"\s+([,.])", r"\1", protected)
    protected = re.sub(r",\s*,+", ", ", protected)
    protected = re.sub(r"\.\s*\.+", ". ", protected)
    return _restore(protected.strip(), saved), dash_count, prose_count


def _line_parts(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def _cut_once(text: str, cap: int) -> tuple[str, str]:
    words = list(scanner.WORD_RE.finditer(text))
    fallback = words[cap - 1].end()
    boundaries = list(BOUNDARY_RE.finditer(text[:fallback]))
    boundary = boundaries[-1] if boundaries and boundaries[-1].start() > fallback // 2 else None
    if boundary is None:
        cut, tail = fallback, text[fallback:].lstrip()
    elif boundary.group(0).lstrip().startswith(","):
        cut, tail = boundary.start(), text[boundary.end():].lstrip()
    else:
        cut, tail = boundary.start(), text[boundary.start():].lstrip()
    return text[:cut].rstrip(" ,.!?"), tail


def _split_long_line(body: str, cap: int) -> tuple[list[str], int]:
    indent = body[: len(body) - len(body.lstrip())]
    remaining = body.strip()
    parts: list[str] = []
    while remaining and len(scanner.WORD_RE.findall(remaining)) > cap:
        head, remaining = _cut_once(remaining, cap)
        parts.append(indent + head + ".")
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
        line = finding.get("line")
        rule = finding.get("rule")
        if isinstance(line, int) and isinstance(rule, str):
            result.setdefault(line, set()).add(rule)
    return result


def _comment_candidate(path: str, number: int, body: str) -> dict:
    return {
        "path": path,
        "line": number,
        "rule": "ambiguous_comment",
        "snippet": body.strip()[:180],
    }


@dataclass
class _RewriteState:
    path: str
    cfg: dict
    by_line: dict[int, set[str]]
    counts: dict[str, int]
    ambiguous: list[dict]
    prose: bool
    cap: int
    in_fence: bool = False


def _rewrite_prose_line(state: _RewriteState, body: str, ending: str) -> list[str]:
    if state.in_fence or body.lstrip().startswith(">") or "|" in body:
        return [body + ending]
    if HTML_CODE_LINE_RE.search(body):
        return [body + ending]
    cleaned, dashes, prose_changes = _clean_visible(body)
    state.counts["dashes"] += dashes
    state.counts["prose"] += prose_changes
    pieces, split_count = _split_long_line(cleaned, state.cap)
    state.counts["sentences"] += split_count
    return [piece + ending for piece in pieces]


def _rewrite_comment_line(state: _RewriteState, line: tuple[int, str, str]) -> list[str]:
    number, body, ending = line
    match = scanner.COMMENT_RE.match(body)
    if not match or scanner.DIRECTIVE_COMMENT_RE.match(body.strip()):
        return [body + ending]
    comment = scanner._comment_text(body)
    if comment is None:
        return [body + ending]
    rules = state.by_line.get(number, set())
    if rules & DELETE_COMMENT_RULES and not scanner._has_why_marker(comment):
        state.counts["comments"] += 1
        return []
    if scanner._has_why_marker(comment) and not scanner._has_strong_why_marker(comment):
        state.counts["weak_why"] += 1
    elif scanner._narrates_code(comment) and not rules:
        state.ambiguous.append(_comment_candidate(state.path, number, comment))
    cleaned, dashes, prose_changes = _clean_visible(match.group(1))
    state.counts["dashes"] += dashes
    state.counts["prose"] += prose_changes
    if not cleaned:
        state.counts["comments"] += 1
        return []
    return [body[:match.start(1)] + cleaned + ending]


def _rewrite_line(state: _RewriteState, number: int, line: str) -> list[str]:
    body, ending = _line_parts(line)
    if state.prose and scanner.FENCE_RE.match(body):
        state.in_fence = not state.in_fence
        return [line]
    if state.prose:
        return _rewrite_prose_line(state, body, ending)
    return _rewrite_comment_line(state, (number, body, ending))


def _rewrite_lines(state: _RewriteState, text: str) -> list[str]:
    output: list[str] = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        output.extend(_rewrite_line(state, number, line))
    return output


def rewrite_text(path: str, text: str, config: dict | None = None) -> TextRewrite:
    """Rewrite only visible prose because hidden code and strings must retain exact bytes."""
    cfg = effective_config(config)
    state = _RewriteState(
        path=path,
        cfg=cfg,
        by_line=_findings_by_line(scanner.scan_all(path, text, cfg)),
        counts=_counts(),
        ambiguous=[],
        prose=scanner._is_prose(path, text),
        cap=max(5, int(cfg.get("sentence_word_cap", 40))),
    )
    output = _rewrite_lines(state, text)
    newline = "\r\n" if "\r\n" in text else "\n"
    grouped, groups = _group_lists(output, max(1, int(cfg.get("list_item_cap", 8))), newline)
    state.counts["lists"] += groups
    rewritten = "".join(grouped)
    return TextRewrite(rewritten, state.counts, scanner.scan_all(path, rewritten, cfg), state.ambiguous)


def _rewrite_field(path: str, value: object, config: dict | None) -> TextRewrite | None:
    return rewrite_text(path, value, config) if isinstance(value, str) else None


def _tool_results(
    tool_name: str, updated: dict, context: tuple[str, dict | None]
) -> list[TextRewrite]:
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
    return ToolRewrite(updated, counts, unresolved, ambiguous, updated != tool_input)


def summary(counts: dict[str, int]) -> str:
    """Keep the report compact because every returned word enters the next model request."""
    labels = (
        ("dashes", "banned dashes replaced"),
        ("prose", "prose cuts"),
        ("comments", "comments removed"),
        ("sentences", "sentences split"),
        ("lists", "lists regrouped"),
    )
    rows = [f"{counts.get(key, 0)} {label}" for key, label in labels if counts.get(key, 0)]
    if counts.get("weak_why", 0):
        rows.append(f"{counts['weak_why']} WHY comments need a concrete constraint or consequence")
    return "Watcher cleaned this write: " + ", ".join(rows) + "." if rows else ""
