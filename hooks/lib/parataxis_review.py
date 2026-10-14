"""Hand each parataxis run to the Stop reviewer, because the static run alone held 7 of 40 English hits."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

from . import journal
from .config import JUDGED_STATE, gate_state, rule_state
from .document_hunks import changed_lines
from .markup import _strip_english_hidden
from .parataxis import Run, Sentence, runs_in, shown
from .parataxis_lexicon import RULES
from .pattern_language import line_languages
from .pattern_semantic import prose_source
from .scanner import _active_families, _is_exempt, _is_prose

NEIGHBOURS = 2
MAX_RUN_CHARS = 600
MAX_CONTEXT_CHARS = 900
CONTEXT_LABEL = "Paragraph: "


def _surroundings(run: Run) -> list[Sentence]:
    start = run.paragraph.index(run.sentences[0])
    end = start + len(run.sentences)
    return run.paragraph[max(0, start - NEIGHBOURS):end + NEIGHBOURS]


def candidate_text(run: Run) -> str:
    """Add the neighbouring sentences, because a run reads as emphasis or as a chop only beside them."""
    flagged = shown(run.sentences)[:MAX_RUN_CHARS]
    context = shown(_surroundings(run))
    if context == flagged:
        return flagged
    return f"{flagged}\n{CONTEXT_LABEL}{context[:MAX_CONTEXT_CHARS]}"


def _reviewable(path: str, text: str, config: dict) -> bool:
    if not _is_prose(path, text) or _is_exempt(path, config):
        return False
    return "english" in _active_families(path, config) and gate_state("english", config) != "off"


def _touched(run: Run, changed: frozenset[int] | None) -> bool:
    """False off the changed lines, because an agent must not answer for prose it never touched."""
    return changed is None or any(line in changed for line in run.lines())


def review_runs(path: str, text: str, config: dict) -> list[Run]:
    """Judged rules only, because off stays silent and observe or enforce already speak through the scanner."""
    rules = {rule for rule in RULES if rule_state(rule, config) == JUDGED_STATE}
    if not rules or not _reviewable(path, text, config):
        return []
    masked = _strip_english_hidden(prose_source(path, text))
    language_at = line_languages(masked, config)
    languages = [language_at(number) for number in range(1, masked.count("\n") + 2)]
    return [run for run in runs_in(path, masked, languages) if run.lexicon.rule in rules]


def _row(run: Run) -> dict:
    return {"rule": run.lexicon.rule, "line": run.sentences[0].line, "text": candidate_text(run)}


def review_rows(path: str, text: str, config: dict) -> list[dict]:
    return [_row(run) for run in review_runs(path, text, config)]


class EditTurn(NamedTuple):
    session_id: str
    turn_id: str
    config: dict
    state_root: str | Path | None


def record(turn: EditTurn, path: str | Path) -> list[dict]:
    """Swallowed on error, because a lost candidate costs one review while a raise would fail the edit."""
    try:
        source = journal.current_source(path)
        if source is None:
            return []
        digest, text = source
        before = journal.turn_before(turn.session_id, path, digest, turn.state_root)
        changed = None if before is None else changed_lines(before, text)
        rows = [_row(run) for run in review_runs(str(path), text, turn.config) if _touched(run, changed)]
        if not rows:
            return []
        return journal.record_patterns(
            turn.session_id, turn.turn_id, path, rows, content_hash=digest, state_root=turn.state_root,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        sys.stderr.write(f"agent-discipline-watcher: parataxis candidates skipped: {exc}\n")
        return []
