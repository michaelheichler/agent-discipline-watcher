"""Wording for every gated name, because a reader cannot act on an identifier like banned_adverb."""
from __future__ import annotations

from typing import NamedTuple

try:
    from . import config
except ImportError:
    import config


class Entry(NamedTuple):
    """Pair the title with its consequence because a title alone still leaves the reader guessing."""

    title: str
    description: str


RULES: dict[str, Entry] = {
    "ai_closer": Entry(
        "Wrap-up flourish",
        "Cuts the closing gesture that restates the point instead of ending",
    ),
    "banned_adverb": Entry(
        "Empty intensifiers",
        "Cuts really, just, literally, simply, actually, and eleven more that add no meaning",
    ),
    "binary_contrast": Entry(
        "Not X but Y framing",
        "Cuts the false either-or that sounds decisive and says little",
    ),
    "business_jargon": Entry(
        "Corporate vocabulary",
        "Cuts navigate the, unpack the, lean into, and the X landscape",
    ),
    "corporate_idiom": Entry(
        "Office idiom",
        "Cuts stock office phrasing that carries no specific claim",
    ),
    "dramatic_fragmentation": Entry(
        "Fragments used for drama",
        "Cuts the one-word paragraph that leans on white space for weight",
    ),
    "emphasis_crutch": Entry(
        "Manufactured emphasis",
        "Cuts full stop, let that sink in, make no mistake, and this matters because",
    ),
    "false_agency": Entry(
        "Objects acting on their own",
        "Cuts phrasing that hands agency to a thing that cannot act",
    ),
    "file_length_critical": Entry(
        "File far past its limit",
        "Reports a file grown well beyond the configured length",
    ),
    "file_length_warning": Entry(
        "File nearing its limit",
        "Reports a file approaching the configured length before it blocks",
    ),
    "filler_phrase": Entry(
        "Filler openers",
        "Cuts at its core, when it comes to, the reality is, and in today's X",
    ),
    "formulaic_construction": Entry(
        "Template sentence shapes",
        "Cuts the repeated structural mould that marks generated prose",
    ),
    "formulaic_filler": Entry(
        "Balanced-hands filler",
        "Cuts it is important to note, on one hand, and first and foremost",
    ),
    "formulaic_opener": Entry(
        "Stock opening line",
        "Cuts in a world where, imagine this, and whether you are a beginner",
    ),
    "greeting_opener": Entry(
        "Greeting before the answer",
        "Cuts the salutation that delays the first useful sentence",
    ),
    "hedge_stack": Entry(
        "Stacked hedges",
        "Cuts piled qualifiers that soften a claim until it says nothing",
    ),
    "lazy_extreme": Entry(
        "Absolute claims",
        "Cuts every, always, never, and nothing where the claim is not absolute",
    ),
    "long_sentence": Entry(
        "Overlong sentence",
        "Reports a sentence past the word cap, which defaults to 40 words",
    ),
    "low_sentence_variance": Entry(
        "Uniform sentence length",
        "Reports prose where every sentence runs the same length",
    ),
    "meta_commentary": Entry(
        "Asides about the writing",
        "Cuts hint, plot twist, spoiler, and is a feature not a bug",
    ),
    "narrator_distance": Entry(
        "Narrator steps back",
        "Cuts the move that comments on the subject instead of stating it",
    ),
    "negative_listing": Entry(
        "Defining by what it is not",
        "Cuts the run of negations that describes nothing concrete",
    ),
    "oversized_list": Entry(
        "List too long to scan",
        "Reports a list past the item cap, which defaults to 8 items",
    ),
    "passive_voice": Entry(
        "Actor hidden by passive",
        "Asks for the actor and an active verb in place of the passive",
    ),
    "performative_emphasis": Entry(
        "Performed sincerity",
        "Cuts creeps in, they exist I promise, and I promise",
    ),
    "rhetorical_setup": Entry(
        "Question asked to answer it",
        "Cuts the rhetorical question that stages a point already underway",
    ),
    "telling_not_showing": Entry(
        "Asserting instead of showing",
        "Cuts this is genuinely hard and actually matters in place of evidence",
    ),
    "three_item_list": Entry(
        "Three-item rhythm",
        "Sends the triad to a judge, because three items can be real or a cadence tic",
    ),
    "throat_clearing_opener": Entry(
        "Warm-up before the point",
        "Cuts here is the thing, it turns out, and the real X is",
    ),
    "uniform_paragraph_endings": Entry(
        "Paragraphs ending alike",
        "Reports prose where paragraph after paragraph closes the same way",
    ),
    "vague_declarative": Entry(
        "Grand claim without content",
        "Cuts the reasons are structural and the implications are significant",
    ),
    "weak_sentence_starter": Entry(
        "Buried subject",
        "Cuts there is and it is openings that push the real subject back",
    ),
    "weighted_slop_marker": Entry(
        "Marker density too high",
        "Reports prose where weighted generated-text markers cluster past the threshold",
    ),
    "cap_override": Entry(
        "Discipline cap overridden",
        "Raises a cap or escape on the command line instead of fixing the code shape",
    ),
    "commit_gate_bypass": Entry(
        "Commit skips the gate",
        "Drops the pre-commit gate through a no-verify flag",
    ),
    "config_seal": Entry(
        "Config edit routes around a gate",
        "Edits policy to disable a rule that no project config may weaken",
    ),
    "decode_pipe_write": Entry(
        "Decode pipe writes a file",
        "Pipes decoded content into a file, which hides the body from the scanner",
    ),
    "docstring_narration": Entry(
        "Docstring narrates the code",
        "States what the code does rather than why it exists",
    ),
    "dynamic_heredoc_write": Entry(
        "Dynamic heredoc writes a file",
        "Aims an expanded or unterminated heredoc at a file the scanner cannot read",
    ),
    "file_too_long": Entry(
        "File past the hard limit",
        "Grows a file beyond the length the policy allows",
    ),
    "inline_interpreter_write": Entry(
        "Inline interpreter can write",
        "Hands python, node, or a peer a payload that can write or cannot be read",
    ),
    "inplace_edit_write": Entry(
        "In-place editor rewrites a file",
        "Rewrites through sed -i, awk -i, or a peer, which skips the scanner",
    ),
    "install_without_sandbox_home": Entry(
        "Installer aimed at the real HOME",
        "Runs an installer or merge script against the live home directory",
    ),
    "interpreter_heredoc_write": Entry(
        "Heredoc feeds an interpreter",
        "Feeds interpreter stdin a body that can write or that nothing can read",
    ),
    "opaque_source_write": Entry(
        "Unscannable write source",
        "Copies from a source the scanner cannot read, such as process substitution",
    ),
    "prose_comment_block": Entry(
        "Comment block reads as prose",
        "Carries paragraphs of narration where the code should speak",
    ),
    "shell_payload_block": Entry(
        "Shell payload unreadable",
        "Nests a shell -c payload past one level or hides it behind a variable",
    ),
    "state_deletion": Entry(
        "Watcher state deleted",
        "Removes watcher state or gate config instead of repairing the finding",
    ),
    "state_mutation": Entry(
        "Watcher state altered",
        "Edits watcher state or gate config that belongs to the host",
    ),
    "suppression_escape_hatch": Entry(
        "Suppression marker added",
        "Silences a finding through an ignore marker rather than fixing the cause",
    ),
    "unscannable_file": Entry(
        "File cannot be scanned",
        "Writes content in a form the scanner cannot read and therefore cannot gate",
    ),
    "watcher_install_surface": Entry(
        "Live install edited",
        "Mutates the installed watcher instead of changing the repo and reinstalling",
    ),
    "watcher_wiring_removal": Entry(
        "Hook wiring removed",
        "Unwires a hook event so the gate stops running",
    ),
    "weak_why_comment": Entry(
        "Why comment says nothing",
        "Labels a case by letter or apologises where a reason belongs",
    ),
    "what_comment": Entry(
        "Comment restates the code",
        "Narrates the line below instead of explaining why it exists",
    ),
    "what_docstring": Entry(
        "Docstring restates the signature",
        "Repeats the parameters rather than naming why the function exists",
    ),
}

LOCKED_RULES = frozenset(config.ALWAYS_BLOCKING_RULES)

FAMILIES: dict[str, Entry] = {
    "punctuation": Entry(
        "Punctuation discipline",
        "Bans dash characters, semicolon splices, prose colons, and stray apostrophes",
    ),
    "english": Entry(
        "Prose quality",
        "Cuts filler, hedging, jargon, and generated-text patterns from reader-facing English",
    ),
    "clean_code": Entry(
        "Code hygiene",
        "Blocks narration comments, dead code, hollow tests, and oversized files",
    ),
}

THRESHOLDS: dict[str, Entry] = {
    "max_rows": Entry(
        "Findings shown per file",
        "How many rows one report lists before it truncates. Default 8",
    ),
    "sentence_word_cap": Entry(
        "Sentence word limit",
        "Word count that trips the overlong sentence rule. Default 40",
    ),
    "list_item_cap": Entry(
        "List item limit",
        "Item count that trips the oversized list rule. Default 8",
    ),
}

RULE_STATES: dict[str, Entry] = {
    "off": Entry("Off", "The rule never runs and reports nothing"),
    "observe": Entry("Reports only", "The finding reaches the report and the write goes through"),
    "enforce": Entry("Blocks", "The finding stops the write until you repair it"),
    "judged": Entry("Model decides", "A judge reads each finding and blocks only what it confirms"),
}

FAMILY_STATES: dict[str, Entry] = {
    "off": Entry("Off", "No rule in this family runs"),
    "observe": Entry("Reports only", "Findings reach the report and writes go through"),
    "enforce": Entry("Blocks", "Findings stop the write until you repair them"),
}

BASELINE_MODES: dict[str, Entry] = {
    "git": Entry(
        "Compare against git",
        "Splits findings against the committed baseline, so inherited debt reports without blocking",
    ),
    "report": Entry("Report everything", "Every finding surfaces with no baseline comparison"),
    "none": Entry("No baseline", "Findings cover the whole file with no inherited-debt allowance"),
}

LOCKED_STATE = Entry(
    "Always blocks",
    "This rule guards the gate itself, and no project config can change it",
)

_UNWRITTEN = "No wording written for this name yet"


def _derived(name: str) -> Entry:
    return Entry(name.replace("_", " ").capitalize(), _UNWRITTEN)


def rule_entry(name: str) -> Entry:
    """Derive a title because a rule added later must not break the screen."""
    return RULES.get(name) or _derived(name)


def family_entry(name: str) -> Entry:
    """Derive a title because a family added later must still render."""
    return FAMILIES.get(name) or _derived(name)


def threshold_entry(name: str) -> Entry:
    """Derive a title because a threshold added later must still render."""
    return THRESHOLDS.get(name) or _derived(name)


def state_entry(name: str, *, locked: bool) -> Entry:
    """Report the lock first because a locked row offers the reader no choice."""
    if locked:
        return LOCKED_STATE
    return RULE_STATES.get(name) or _derived(name)


def family_state_entry(name: str) -> Entry:
    """Read the family scale separately because it carries no judged state."""
    return FAMILY_STATES.get(name) or _derived(name)


def baseline_entry(name: str) -> Entry:
    """Derive a title because a mode added later must still render."""
    return BASELINE_MODES.get(name) or _derived(name)
