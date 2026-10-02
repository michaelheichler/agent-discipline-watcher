# SPDX-FileCopyrightText: Martin Moeller, humanizer-de trigger lists (see NOTICE)
# SPDX-License-Identifier: MIT AND CC-BY-SA-4.0
"""Stay STATIC, because each rule here matches a chatbot turn phrase from humanizer-de references/patterns.md (decision Q13)."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import phrase_hits, sentence_hits
    from .phrases import opening
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import phrase_hits, sentence_hits
    from german_rules.phrases import opening
    from prose_language import ParagraphLanguage

LETTER_FRAME = Rule(
    "de_letter_frame",
    Wording(
        "German letter frame",
        "Flags a German letter shell like Betreff:, a Liebe salutation, or Mit freundlichen Grüßen around content",
        "Delete the letter shell and keep the content.",
    ),
    Wording(
        "Briefartiges Schreiben",
        "Meldet Briefhüllen wie „Betreff:“, eine Anrede mit „Liebe“ oder „Mit freundlichen Grüßen“ um den Inhalt",
        "Streich die Briefhülle und behalte den Inhalt.",
    ),
    state="off",
)
CHATBOT_TALK = Rule(
    "de_chatbot_talk",
    Wording(
        "German chatbot talk",
        "Flags a German assistant phrase like Ich hoffe, das hilft, Natürlich!, or Gute Frage",
        "Delete the phrase and start with the content.",
    ),
    Wording(
        "Kollaborative Chatbot-Sprache",
        "Meldet Assistenten-Wendungen wie „Ich hoffe, das hilft“, „Natürlich!“ oder „Gute Frage“",
        "Streich die Wendung und fang mit dem Inhalt an.",
    ),
)
KNOWLEDGE_CUTOFF = Rule(
    "de_knowledge_cutoff",
    Wording(
        "German knowledge cutoff remark",
        "Flags a German phrase like Bis zu meinem letzten Update that points at a model's training cutoff",
        "Delete the remark or name a dated source.",
    ),
    Wording(
        "Hinweis auf Wissensgrenze",
        "Meldet Wendungen wie „Bis zu meinem letzten Update“, die auf den Trainingsstand eines Modells verweisen",
        "Streich den Hinweis oder nenn eine datierte Quelle.",
    ),
)
PROMPT_REFUSAL = Rule(
    "de_prompt_refusal",
    Wording(
        "German prompt refusal",
        "Flags a German refusal like Als KI-Sprachmodell kann ich nicht that a chatbot left in the text",
        "Delete the refusal.",
    ),
    Wording(
        "Prompt-Ablehnung",
        "Meldet Ablehnungen wie „Als KI-Sprachmodell kann ich nicht“, die ein Chatbot im Text gelassen hat",
        "Streich die Ablehnung.",
    ),
)
THERAPEUTIC_VALIDATION = Rule(
    "de_therapeutic_validation",
    Wording(
        "German pseudo-therapeutic validation",
        "Flags a German line like Du bist nicht zu sensibel that diagnoses the reader without evidence",
        "Delete the diagnosis and state what is missing, what went wrong, or what to do.",
    ),
    Wording(
        "Pseudotherapeutische Validierung",
        "Meldet Sätze wie „Du bist nicht zu sensibel“, die dem Leser ohne Beleg eine Innenwelt zuschreiben",
        "Streich die Diagnose und sag, was fehlt, was schiefging oder was zu tun ist.",
    ),
)

# Muster 17. No Vielen Dank, because docs use it.
LETTER_FRAME_RE = re.compile(
    r"(?im:^[ \t]*Betreff:|^[ \t]*(?:Liebe[rs]?|Sehr\s+geehrte[rs]?)\s+[^\n,]{1,60},[ \t]*$"
    r"|\bmit\s+freundlichen\s+Grüßen\b)"
)
# humanizer-de Muster 18 plus du forms, because Q13.
CHATBOT_TALK_RE = re.compile(
    r"(?i:\bich\s+hoffe,?\s+(?:das|dies)\s+hilft\b|\bnatürlich!|\bselbstverständlich!"
    r"|\b(?:du\s+hast|Sie\s+haben)\s+völlig\s+recht\b|\blass(?:en\s+Sie)?\s+mich\s+wissen\b"
    r"|\bbitte\s+frag(?:en\s+Sie|e)?,?\s+wenn\b|\bwie\s+(?:Sie\s+sehen\s+können|du\s+sehen\s+kannst)\b"
    r"|\bich\s+helfe\s+(?:Ihnen|dir)\s+gerne?\b)"
)
# Muster 18 openers, because praise mid-text is fine.
PRAISE_OPENER_RE = re.compile(r"(?i:gute\s+Frage|starker\s+Punkt|was\s+für\s+eine\s+großartige\s+Frage)\s*[!.,]")
# Muster 19. No Stand [Datum], because docs date it.
KNOWLEDGE_CUTOFF_RE = re.compile(
    r"(?i:\bbis\s+zu\s+meinem\s+letzten\s+(?:Update|Wissensstand|Trainingsstand)\b"
    r"|\bnach\s+meinem\s+(?:aktuellen\s+)?(?:Wissen|Wissensstand|Kenntnisstand)\b|\[Aktualisierung\s+erforderlich\])"
)
# Muster 20 in first person, because docs name models.
PROMPT_REFUSAL_RE = re.compile(
    r"(?i:\bals\s+KI(?:-Sprachmodell|-Modell)?\s*,?\s+(?:kann|darf|habe|bin|werde|möchte|verfüge)\s+ich\b"
    r"|\bich\s+kann\s+keine\s+aktuellen?\s+Informationen?\s+bereitstellen\b"
    r"|\bdas\s+liegt\s+außerhalb\s+meiner\s+Fähigkeiten\b)"
)
# humanizer-de Muster 72, because Q13 credits it.
THERAPEUTIC_VALIDATION_RE = re.compile(
    r"\b(?:du\s+bist\s+nicht\s+(?:zu\s+|einfach\s+nur\s+)?"
    r"(?:sensibel|empfindlich|emotional|bedürftig|anspruchsvoll|schwierig|schwach|faul|anstrengend)"
    r"|du\s+(?:überreagierst\s+nicht|reagierst\s+nicht\s+über|fühlst\s+nicht\s+falsch)"
    r"|deine\s+gefühle\s+sind\s+(?:völlig\s+)?(?:berechtigt|valide|verständlich)"
    r"|deine\s+reaktion(?:en)?\s+(?:ist|sind)\s+(?:völlig\s+)?(?:berechtigt|valide|verständlich)"
    r"|du\s+wurdest\s+(?:nur\s+)?(?:zu\s+lange\s+)?"
    r"(?:nicht\s+ernst\s+genommen|kleingehalten|emotional\s+vernachlässigt))\b",
    re.IGNORECASE,
)


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *phrase_hits(LETTER_FRAME.name, paragraphs, LETTER_FRAME_RE),
        *phrase_hits(CHATBOT_TALK.name, paragraphs, CHATBOT_TALK_RE),
        *sentence_hits(CHATBOT_TALK.name, paragraphs, opening(PRAISE_OPENER_RE)),
        *phrase_hits(KNOWLEDGE_CUTOFF.name, paragraphs, KNOWLEDGE_CUTOFF_RE),
        *phrase_hits(PROMPT_REFUSAL.name, paragraphs, PROMPT_REFUSAL_RE),
        *phrase_hits(THERAPEUTIC_VALIDATION.name, paragraphs, THERAPEUTIC_VALIDATION_RE),
    ]


RULE_SET = RuleSet(
    rules=(LETTER_FRAME, CHATBOT_TALK, KNOWLEDGE_CUTOFF, PROMPT_REFUSAL, THERAPEUTIC_VALIDATION),
    check=_check,
)
