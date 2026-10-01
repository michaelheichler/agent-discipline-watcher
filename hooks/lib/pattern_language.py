"""Route each sentence to the rules of its own language, because a German sentence voted against English exemplars measures nothing."""
from __future__ import annotations

import bisect
import re
from collections.abc import Callable
from pathlib import Path

try:
    from . import german_rules, language_verdict
    from .prose_language import ENGLISH, GERMAN, allowed_languages, paragraph_languages
except ImportError:
    import german_rules
    import language_verdict
    from prose_language import ENGLISH, GERMAN, allowed_languages, paragraph_languages

GERMAN_EXEMPLAR_PATH = Path(__file__).with_name("pattern_exemplars_de.jsonl")
GERMAN_MANIFEST_PATH = Path(__file__).with_name("pattern_exemplars_de.json")


def rule_language(manifest: dict, rule: str) -> str:
    """English unless marked, because every rule in the English manifest predates German."""
    return str(manifest["rules"][rule].get("language") or ENGLISH)


def _precision(recorded: dict, rule: str) -> object:
    row = recorded.get(rule)
    return row.get("judge_precision") if isinstance(row, dict) else None


def german_manifest_rules(measured: dict, rules: tuple[german_rules.Rule, ...] | None = None) -> dict[str, dict]:
    """Taken at load time, because a file written once would drift from the fix the writer reads."""
    chosen = german_rules.voted() if rules is None else rules
    recorded = measured.get("rules") if isinstance(measured.get("rules"), dict) else {}
    return {
        rule.name: {
            "action": rule.german.action, "language": GERMAN, "judge_precision": _precision(recorded, rule.name),
            "definition": " ".join(filter(None, (rule.german.description + ".", rule.boundary))), "trigger": rule.trigger,
        }
        for rule in chosen
    }


def rule_trigger(manifest: dict, rule: str) -> re.Pattern[str] | None:
    """German only, because the German vote admitted half of all human sentences and the trigger under 1 percent (T-009)."""
    row = manifest["rules"][rule]
    if row.get("language") != GERMAN or not row.get("trigger"):
        return None
    return re.compile(str(row["trigger"]), re.IGNORECASE)


def line_languages(source: str, config: dict | None) -> Callable[[int], str]:
    """Same detection as the scanner, because a paragraph must not count as German in one path and English in the other."""
    settings = config or {}
    paragraphs = language_verdict.apply_cached(
        paragraph_languages(source, allowed_languages(settings)), settings.get("state_root"),
    )
    starts = [paragraph.line for paragraph in paragraphs]
    languages = [paragraph.language for paragraph in paragraphs]

    def language_at(line: int) -> str:
        index = bisect.bisect_right(starts, line) - 1
        return languages[index] if index >= 0 else ENGLISH

    return language_at
