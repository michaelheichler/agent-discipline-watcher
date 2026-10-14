import json

from lib import scanner, slop_semantic
from lib.slop_semantic import EXEMPLAR_PATH, Exemplar, load_exemplars, matches, prose_sentences

EXEMPLARS = (Exemplar("binary_contrast", "The answer isn't this. It's that."),)
EXEMPLAR_VECTORS = ((1.0, 0.0),)


def test_exemplars_carry_a_rule_and_a_phrase() -> None:
    rows = load_exemplars(EXEMPLAR_PATH)

    assert len(rows) > 50
    assert all(row.rule and len(row.text.split()) >= 3 for row in rows)


def test_the_exemplar_file_holds_one_json_object_per_line() -> None:
    lines = EXEMPLAR_PATH.read_text(encoding="utf-8").splitlines()

    assert all(set(json.loads(line)) == {"rule", "source", "text"} for line in lines)


def test_sentences_below_the_word_floor_are_not_scored() -> None:
    text = "Short one.\n\nThis sentence carries enough words to be scored at all.\n"

    assert prose_sentences(text) == ((3, "This sentence carries enough words to be scored at all."),)


def test_each_sentence_reports_the_line_it_starts_on() -> None:
    text = (
        "Intro\n\n"
        "The first sentence sits here. The second sentence starts here and\n"
        "spans onto the next line.\n"
        "The third sentence opens a line. The fourth sentence starts mid line.\n"
    )

    assert [number for number, _sentence in prose_sentences(text)] == [3, 3, 5, 5]


def test_a_long_paragraph_keeps_every_sentence_on_its_own_line() -> None:
    lines = range(1, slop_semantic.MAX_SENTENCES + 1)
    text = "\n".join(f"Line {number} ends right here." for number in lines)

    assert [number for number, _sentence in prose_sentences(text)] == list(lines)


def test_a_match_needs_the_threshold() -> None:
    sentences = ((1, "aligned"), (2, "orthogonal"))
    vectors = ((1.0, 0.0), (0.0, 1.0))

    found = matches(sentences, vectors, EXEMPLARS, EXEMPLAR_VECTORS, 0.5)

    assert [item.line for item in found] == [1]
    assert found[0].exemplar.rule == "binary_contrast"


def test_the_measured_layer_stays_out_of_the_blocking_scanner() -> None:
    """Asserted because the recorded measurement gives it no recall to enforce on, so it must not reach a gate by accident."""
    assert "slop_semantic" not in scanner.__dict__
    assert slop_semantic.scan_semantic not in scanner.__dict__.values()
