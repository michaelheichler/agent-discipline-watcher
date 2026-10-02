"""Prove the German rule seam, because a new German rule must land as one module file and nothing else."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import catalog, config, german_rules
from lib.finding_output import format_row
from lib.findings import Outcome
from lib.german_rules import Hit, Rule, RuleSet, Wording
from lib.prose_language import ParagraphLanguage

PARAGRAPH = ParagraphLanguage(line=3, text="Der Hund bellt.", language="de", weak=False)
FAKE_RULE = Rule(
    "de_fake_bark",
    Wording("Barking dog", "Flags a barking dog", "Quiet the dog."),
    Wording("Bellender Hund", "Meldet einen bellenden Hund", "Beruhig den Hund."),
)
MODULE = (
    "from lib.german_rules import Hit, Rule, RuleSet, Wording\n"
    "RULE = Rule({name!r}, Wording('Found', 'Finds it', 'Fix it.'), Wording('Gefunden', 'Findet es', 'Behebe es.'))\n"
    "RULE_SET = RuleSet(rules=(RULE,), check=lambda path, paragraphs: [Hit(RULE.name, p.line, p.text, 'Hund') for p in paragraphs])\n"
)


def _write_package(root: Path, package_name: str, modules: dict[str, str]) -> Path:
    package = root / package_name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, body in modules.items():
        (package / (name + ".py")).write_text(body, encoding="utf-8")
    return package


def test_discovery_picks_up_a_new_module_without_an_import_line(tmp_path, monkeypatch) -> None:
    package = _write_package(tmp_path, "added_german_rules", {"extra": MODULE.format(name="de_extra")})
    monkeypatch.syspath_prepend(str(tmp_path))

    found = german_rules.discover([str(package)], "added_german_rules")
    rows = german_rules.check_paragraphs("doc.md", [PARAGRAPH], found)

    assert [(row["rule"], row["line"], row["match"], row["family"]) for row in rows] == [("de_extra", 3, "Hund", "english")]
    assert german_rules.default_gates(found) == {"de_extra": "observe"}


def test_discovery_rejects_two_modules_declaring_one_rule(tmp_path, monkeypatch) -> None:
    body = MODULE.format(name="de_same")
    package = _write_package(tmp_path, "clashing_german_rules", {"first": body, "second": body})
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ValueError, match="same rule"):
        german_rules.discover([str(package)], "clashing_german_rules")


def test_a_hit_naming_an_undeclared_rule_fails_loudly() -> None:
    stray = RuleSet(rules=(FAKE_RULE,), check=lambda path, paragraphs: [Hit("de_typo", 1, "", "")])

    with pytest.raises(ValueError, match="de_typo"):
        german_rules.check_paragraphs("doc.md", [PARAGRAPH], (stray,))


def test_no_german_paragraph_runs_no_check() -> None:
    exploding = RuleSet(rules=(FAKE_RULE,), check=lambda path, paragraphs: 1 / 0)

    assert german_rules.check_paragraphs("doc.md", [], (exploding,)) == []


STATE_OUTCOME = {"enforce": Outcome.BLOCK, "off": Outcome.RELEASE}


@pytest.mark.parametrize("rule", german_rules.declared(), ids=lambda rule: rule.name)
def test_every_registered_rule_blocks_only_when_its_measured_state_says_so(rule: Rule) -> None:
    expected = STATE_OUTCOME.get(rule.state, Outcome.WOULD_BLOCK)

    assert config.resolve_outcome({"family": "english", "rule": rule.name}, {}) == expected


@pytest.mark.parametrize("rule", german_rules.declared(), ids=lambda rule: rule.name)
def test_every_registered_rule_renders_its_own_wording_in_each_language(rule: Rule) -> None:
    row = {"path": "doc.md", "line": 1, "rule": rule.name, "match": "x", "action": rule.english.action}

    assert catalog.rule_entry(rule.name).title == rule.english.title
    assert rule.german.title in format_row({**row, "language": "de"})


EVALS = Path(__file__).resolve().parents[2] / "evals"
PRECISION_BAR = 0.7
# Skipped, because a family gate already decides these two.
RULE_GATE_EXEMPT = frozenset({"banned_dash", "spaced_hyphen"})


def _static_precisions() -> dict[str, float]:
    payload = json.loads((EVALS / "german_static_precision.json").read_text(encoding="utf-8"))
    return {
        name: info["precision"]
        for name, info in payload["rules"].items()
        if name not in RULE_GATE_EXEMPT and info.get("precision") is not None
    }


def _semantic_precisions() -> dict[str, float]:
    payload = json.loads((EVALS / "judge_stage_de.json").read_text(encoding="utf-8"))
    runs = payload["gpt-6-luna"]
    return {
        name: info["after_judge"]["precision"]
        for name, info in runs.items()
        if info.get("after_judge", {}).get("precision") is not None
    }


def _measured_precisions() -> dict[str, float]:
    merged = dict(_static_precisions())
    merged.update(_semantic_precisions())
    return merged


def _declared_state(name: str) -> str:
    rule = next((candidate for candidate in german_rules.declared() if candidate.name == name), None)
    if rule is not None:
        return rule.state
    return config.DEFAULTS["rule_gates"][name]


@pytest.mark.parametrize("name,precision", sorted(_measured_precisions().items()))
def test_every_measured_german_rule_state_follows_the_point_precision_bar(name: str, precision: float) -> None:
    """Hold the 2026-10-02 decision, because a measured rule reports only above 0.7 point precision."""
    reports = _declared_state(name) in ("observe", "enforce")

    assert reports == (precision > PRECISION_BAR)
