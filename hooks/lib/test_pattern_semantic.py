from __future__ import annotations

import pytest

from lib import embedding_session, pattern_semantic
from lib.pattern_judge import JudgedOutcome
from lib.pattern_semantic import Exemplar, Layer, Sentence

EXEMPLARS = (
    Exemplar("ai_closer", "violating", "Let me know if you need anything else."),
    Exemplar("ai_closer", "violating", "I hope this helps with your project."),
    Exemplar("ai_closer", "clean", "The cache holds 4096 entries."),
    Exemplar("ai_closer", "clean", "The build finished in nine seconds."),
)
VECTORS = {
    "Let me know if you need anything else.": (1.0, 0.0),
    "I hope this helps with your project.": (0.9, 0.1),
    "The cache holds 4096 entries.": (0.0, 1.0),
    "The build finished in nine seconds.": (0.1, 0.9),
    "Feel free to ask me anything else.": (0.95, 0.05),
    "The lease expires after 900 seconds.": (0.05, 0.95),
}
MANIFEST = {"rules": {"ai_closer": {"action": "End when the answer is done.", "judge_precision": 1.0}}}
VOTING = Layer(
    exemplars=lambda: EXEMPLARS,
    manifest=lambda: MANIFEST,
    exemplar_vectors=lambda _exemplars: VECTORS,
    vectors=lambda _texts: VECTORS,
)


@pytest.fixture(name="opted_in")
def _opted_in(monkeypatch) -> None:
    monkeypatch.delenv(embedding_session.DISABLE_ENV, raising=False)
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")


def test_the_shipped_exemplars_carry_both_sides_for_every_rule() -> None:
    exemplars = pattern_semantic.load_exemplars()
    rules = {row.rule for row in exemplars}

    assert rules
    for rule in rules:
        sides = {row.label for row in exemplars if row.rule == rule}
        assert sides == {"violating", "clean"}, rule


def test_every_shipped_rule_carries_an_action_for_the_judge() -> None:
    manifest = pattern_semantic.load_manifest()

    for rule, row in manifest["rules"].items():
        assert row["action"].strip(), rule


def test_an_unmeasured_rule_never_speaks() -> None:
    manifest = {"rules": {"measured": {"judge_precision": 0.94}, "unmeasured": {"judge_precision": None}}}

    assert pattern_semantic.measured_rules(manifest) == ("measured",)


def test_only_a_measured_rule_blocks() -> None:
    manifest = {
        "rules": {
            "measured_high": {"judge_precision": 0.94},
            "measured_low": {"judge_precision": 0.60},
            "unmeasured": {"judge_precision": None},
        }
    }

    assert pattern_semantic.blocking_rules(manifest) == frozenset({"measured_high"})


def test_the_shipped_gate_matches_the_recorded_measurement() -> None:
    manifest = pattern_semantic.load_manifest()
    blocking = pattern_semantic.blocking_rules(manifest)

    assert "ai_closer" in blocking
    for rule in blocking:
        assert manifest["rules"][rule]["judge_precision"] >= pattern_semantic.ENFORCE_PRECISION


def test_a_near_neighbour_of_the_violating_side_becomes_a_candidate() -> None:
    sentences = (Sentence(3, "Feel free to ask me anything else."),)

    found = pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md")

    assert [item.line for item in found] == [3]


def test_a_near_neighbour_of_the_clean_side_is_not_a_candidate() -> None:
    sentences = (Sentence(4, "The lease expires after 900 seconds."),)

    assert pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md") == ()


def test_a_sentence_without_a_vector_is_never_flagged() -> None:
    sentences = (Sentence(5, "This sentence was never embedded at all."),)

    assert pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md") == ()


def test_a_rule_without_exemplar_vectors_is_skipped_with_one_notice(capsys) -> None:
    sentences = (Sentence(3, "Feel free to ask me anything else."), Sentence(4, "The lease expires after 900 seconds."))
    only_sentences = {text: VECTORS[text] for _line, text in sentences}

    assert pattern_semantic.candidates_for("ai_closer", sentences, only_sentences, EXEMPLARS, "a.md") == ()
    assert capsys.readouterr().err.count("ai_closer") == 1


@pytest.mark.usefixtures("opted_in")
def test_an_absent_server_yields_no_finding_rather_than_a_clean_verdict() -> None:
    silent = Layer(exemplar_vectors=lambda _exemplars: {}, vectors=lambda _texts: {})

    assert pattern_semantic.scan("a.md", "The cache was rebuilt overnight by the scheduler.\n", layer=silent) == ()


def test_a_document_without_prose_costs_no_embedding() -> None:
    def forbidden(*_args: object) -> dict:
        pytest.fail("embedded a document carrying no prose")

    assert pattern_semantic.scan("a.md", "", layer=Layer(exemplar_vectors=forbidden, vectors=forbidden)) == ()


def test_the_layer_is_silent_until_the_reader_opts_in() -> None:
    switched_off = Layer(vectors=lambda _texts: pytest.fail("embedded while the layer was switched off"))

    assert pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n", layer=switched_off) == ()


@pytest.mark.usefixtures("opted_in")
def test_the_judge_decides_which_candidates_become_findings() -> None:
    layer = VOTING._replace(confirm=lambda work, _model: JudgedOutcome(
        {rule.name: candidates[:1] for rule, candidates in work if candidates}, (), ""),
    )

    findings = pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n", layer=layer)

    assert [(item.rule, item.blocking) for item in findings] == [("ai_closer", True)]


@pytest.fixture(name="cache_root")
def _cache_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ADW_EMBEDDING_URL", "http://127.0.0.1:1111/v1/embeddings")
    root = pattern_semantic.exemplar_cache_root()
    root.mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    ("variable", "value"),
    [("ADW_EMBEDDING_MODEL", "another-model"), ("ADW_EMBEDDING_URL", "http://127.0.0.1:2222/v1/embeddings")],
)
def test_the_cache_key_changes_with_model_and_endpoint(cache_root, monkeypatch, variable, value) -> None:
    before = pattern_semantic._cache_path(None)
    monkeypatch.setenv(variable, value)

    assert pattern_semantic._cache_path(None) != before


def test_a_failed_cache_write_leaves_the_old_cache_whole(cache_root, monkeypatch) -> None:
    path = pattern_semantic._cache_path(None)
    path.write_text('[["old", [1.0]]]', encoding="utf-8")

    def interrupted(_source, _target) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pattern_semantic.os, "replace", interrupted)
    with pytest.raises(OSError):
        pattern_semantic.exemplar_vectors(EXEMPLARS, vectors=lambda texts, config=None: {text: (0.5,) for text in texts})

    assert path.read_text(encoding="utf-8") == '[["old", [1.0]]]'


@pytest.mark.usefixtures("opted_in")
def test_a_judge_that_confirms_nothing_produces_no_finding() -> None:
    layer = VOTING._replace(confirm=lambda _work, _model: JudgedOutcome({}, (), ""))

    assert pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n", layer=layer) == ()


@pytest.mark.usefixtures("opted_in")
def test_the_candidate_stage_votes_without_calling_a_judge() -> None:
    layer = VOTING._replace(confirm=lambda *_args: pytest.fail("called the judge"))
    text = "Feel free to ask me anything else.\n\nThe lease expires after 900 seconds.\n"

    voted = pattern_semantic.candidates("a.md", text, layer=layer)

    assert {rule: [(item.line, item.text) for item in found] for rule, found in voted.items()} == {
        "ai_closer": [(1, "Feel free to ask me anything else.")],
    }


@pytest.mark.usefixtures("opted_in")
def test_the_vote_embeds_only_the_exemplars_a_measured_rule_needs() -> None:
    unmeasured = Exemplar("unmeasured", "violating", "This exemplar belongs to a silent rule.")
    embedded: list[tuple[Exemplar, ...]] = []
    layer = VOTING._replace(
        exemplars=lambda: (*EXEMPLARS, unmeasured),
        manifest=lambda: {"rules": {
            "ai_closer": {"action": "End when the answer is done.", "judge_precision": 1.0},
            "unmeasured": {"action": "Say it plainly.", "judge_precision": None},
        }},
        exemplar_vectors=lambda rows: embedded.append(rows) or VECTORS,
    )

    pattern_semantic.candidates("a.md", "Feel free to ask me anything else.\n", layer=layer)

    assert {row.rule for row in embedded[0]} == {"ai_closer"}


def test_the_candidate_stage_is_silent_until_the_reader_opts_in() -> None:
    switched_off = Layer(vectors=lambda _texts: pytest.fail("embedded while switched off"))

    assert pattern_semantic.candidates("a.md", "Feel free to ask me anything else.\n", layer=switched_off) == {}
