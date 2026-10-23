"""Stay STATIC, because each rule here splits one long word into dictionary parts without a model call."""
from __future__ import annotations

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import placed
    from ..german_compounds import BLOCK_LETTERS, Compound, compounds
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import placed
    from german_compounds import BLOCK_LETTERS, Compound, compounds
    from prose_language import ParagraphLanguage

ACTION = "Rephrase it in shorter words, such as Einträge der Konfiguration, and hyphenate only where a reader needs it."
AKTION = "Formulier es in kürzeren Wörtern, etwa „Einträge der Konfiguration“, und setz einen Bindestrich nur, wo der Leser ihn braucht."

# Enforced because evals/german_compounds.json holds a Wilson lower bound of 0.95.
LONG_COMPOUND = Rule(
    "de_long_compound",
    Wording(
        "Long German compound",
        "Flags a German compound of 25 or more letters that splits into dictionary words and has no hyphen",
        ACTION,
    ),
    Wording(
        "Langes Kompositum",
        "Meldet ein Kompositum ab 25 Buchstaben ohne Bindestrich, das sich in Wörter aus dem Lexikon zerlegen lässt",
        AKTION,
    ),
    state="enforce",
)
# Observe by user decision, so a mid-length compound shows as a hint only.
COMPOUND_HINT = Rule(
    "de_compound_hint",
    Wording(
        "German compound hint",
        "Flags a German compound of 14 to 24 letters that splits into dictionary words and has no hyphen",
        ACTION,
    ),
    Wording(
        "Hinweis auf ein Kompositum",
        "Meldet ein Kompositum mit 14 bis 24 Buchstaben ohne Bindestrich, das sich in Wörter aus dem Lexikon zerlegen lässt",
        AKTION,
    ),
    state="observe",
)


def _rule_for(compound: Compound) -> Rule:
    return LONG_COMPOUND if len(compound.word) >= BLOCK_LETTERS else COMPOUND_HINT


def _paragraph_hits(paragraph: ParagraphLanguage) -> list[Hit]:
    """Quote the split as the snippet, because the reader rewrites or hyphenates where two parts meet."""
    return [
        placed(
            paragraph, (compound.start, compound.start + len(compound.word)),
            Hit(_rule_for(compound).name, paragraph.line, " | ".join(compound.parts), compound.word),
        )
        for compound in compounds(paragraph.text)
    ]


def _check(_path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [hit for paragraph in paragraphs for hit in _paragraph_hits(paragraph)]


RULE_SET = RuleSet(rules=(LONG_COMPOUND, COMPOUND_HINT), check=_check)
