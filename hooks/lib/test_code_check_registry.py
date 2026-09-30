"""Prove the Code Check seam, because four tickets plug into it."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from lib import config, test_rules
from lib.findings import Outcome
from lib.scanner import scan_all
from lib.test_rules import Hit, Rule, RuleSet
from lib.test_units import Unit, extract

PYTHON_SOURCE = '''import pytest


def helper() -> int:
    return 1


def test_plain() -> None:
    assert helper() == 1


class TestGroup:
    def test_method(self) -> None:
        for value in (1, 2):
            assert value


async def test_async() -> None:
    assert await thing()
'''

RUST_SOURCE = '''fn helper<'a>(text: &'a str) -> &'a str { text }

#[test]
fn every_sex_keeps_the_method_ready() {
    for sex in ["m", "w"] {
        assert_eq!(status(sex), "ready", "{sex}: }");
    }
}

#[tokio::test(flavor = "multi_thread")]
#[ignore]
async fn later() -> Result<(), Error> {
    let brace = '{';
    Ok(())
}

fn not_a_test() {}
'''

LOOP_RULE = Rule("fake_loop", "Test loops over cases", "Parameterize the cases.")


def _loop_hits(unit: Unit, _text: str) -> list[Hit]:
    lines = unit.body.splitlines()
    return [
        Hit(LOOP_RULE.name, unit.start + offset, line)
        for offset, line in enumerate(lines) if line.lstrip().startswith("for ")
    ]


FAKE = RuleSet(rules=(LOOP_RULE,), check=_loop_hits)


def _spans(units: list[Unit]) -> list[tuple[str, int, int]]:
    return [(unit.name, unit.start, unit.end) for unit in units]


def test_python_units_cover_functions_methods_and_async_tests() -> None:
    units = extract("tests/test_sample.py", PYTHON_SOURCE)

    assert _spans(units) == [("test_plain", 8, 9), ("test_method", 13, 15), ("test_async", 18, 19)]
    assert units[1].body.splitlines()[-1].strip() == "assert value"
    assert {unit.language for unit in units} == {"python"}


def test_python_that_does_not_parse_yields_no_units() -> None:
    assert not extract("tests/test_broken.py", "def test_x(:\n    assert 1\n")


def test_rust_units_follow_test_attributes_across_lifetimes_and_quoted_braces() -> None:
    units = extract("src/lib.rs", RUST_SOURCE)

    assert _spans(units) == [("every_sex_keeps_the_method_ready", 4, 8), ("later", 12, 15)]
    assert units[0].body.startswith("fn every_sex") and units[0].body.endswith("}\n}")
    assert units[1].body.rstrip().endswith("Ok(())\n}")


def test_other_languages_yield_no_units() -> None:
    assert not extract("src/app.ts", "test('x', () => { expect(1).toBe(1) })\n")


def test_a_registered_rule_turns_each_hit_into_a_code_finding() -> None:
    rows = test_rules.check_file("src/lib.rs", RUST_SOURCE, (FAKE,))

    assert [(row["family"], row["rule"], row["line"]) for row in rows] == [("code", "fake_loop", 5)]
    assert "every_sex_keeps_the_method_ready" in rows[0]["detail"]
    assert rows[0]["action"] == LOOP_RULE.action


def test_a_hit_naming_an_undeclared_rule_fails_loudly() -> None:
    stray = RuleSet(rules=(LOOP_RULE,), check=lambda unit, text: [Hit("typo", unit.start, "")])

    with pytest.raises(ValueError, match="typo"):
        test_rules.check_file("tests/test_sample.py", PYTHON_SOURCE, (stray,))


def _write_package(root: Path, package_name: str, modules: dict[str, str]) -> Path:
    package = root / package_name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, body in modules.items():
        (package / (name + ".py")).write_text(body, encoding="utf-8")
    return package


MODULE = (
    "from lib.test_rules import Hit, Rule, RuleSet\n"
    "RULE_SET = RuleSet(rules=(Rule({name!r}, 'Found', 'Fix it.'),), "
    "check=lambda unit, text: [Hit({name!r}, unit.start, unit.name)])\n"
)


def test_discovery_picks_up_a_new_module_without_an_import_line(tmp_path, monkeypatch) -> None:
    package = _write_package(tmp_path, "added_rules", {"extra": MODULE.format(name="extra_rule")})
    monkeypatch.syspath_prepend(str(tmp_path))

    found = test_rules.discover([str(package)], "added_rules")
    rows = test_rules.check_file("tests/test_sample.py", PYTHON_SOURCE, found)

    assert [(row["rule"], row["snippet"]) for row in rows][:1] == [("extra_rule", "test_plain")]


def test_discovery_rejects_two_modules_declaring_one_rule(tmp_path, monkeypatch) -> None:
    body = MODULE.format(name="same")
    package = _write_package(tmp_path, "clashing_rules", {"first": body, "second": body})
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ValueError, match="same rule"):
        test_rules.discover([str(package)], "clashing_rules")


def test_an_unmeasured_rule_reports_without_blocking() -> None:
    finding = {"family": "code", "rule": LOOP_RULE.name}
    gates = {"rule_gates": test_rules.default_gates((FAKE,))}

    assert config.resolve_outcome(finding, {}) == Outcome.BLOCK
    assert config.resolve_outcome(finding, gates) == Outcome.WOULD_BLOCK


def test_every_registered_rule_starts_at_observe() -> None:
    names = [rule.name for rule_set in test_rules.RULE_SETS for rule in rule_set.rules]
    outcomes = {config.resolve_outcome({"family": "code", "rule": name}, {}) for name in names}

    assert outcomes <= {Outcome.WOULD_BLOCK}


def test_the_scanner_runs_the_registry_only_with_code_check_on(monkeypatch) -> None:
    monkeypatch.setattr(test_rules, "RULE_SETS", (FAKE,))

    enabled = [row["line"] for row in scan_all("src/lib.rs", RUST_SOURCE, {}) if row["rule"] == "fake_loop"]
    disabled = [row for row in scan_all("src/lib.rs", RUST_SOURCE, {"code": False}) if row["rule"] == "fake_loop"]

    assert (enabled, disabled) == ([5], [])


def _audit_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "evals" / "code_check_audit.py"
    spec = importlib.util.spec_from_file_location("code_check_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_audit_counts_tests_and_hits_per_rule(tmp_path) -> None:
    (tmp_path / "test_sample.py").write_text(PYTHON_SOURCE, encoding="utf-8")
    (tmp_path / "lib.rs").write_text(RUST_SOURCE, encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "test_copy.py").write_text(PYTHON_SOURCE, encoding="utf-8")

    report = _audit_module().audit(tmp_path, (FAKE,))

    assert (report["test_files"], report["test_functions"], report["total_hits"]) == (2, 5, 2)
    assert report["rules"]["fake_loop"]["hits"][0] == {"path": "lib.rs", "line": 5, "test": "every_sex_keeps_the_method_ready"}


def test_the_audit_writes_only_its_report(tmp_path) -> None:
    source = tmp_path / "tree"
    source.mkdir()
    (source / "test_sample.py").write_text(PYTHON_SOURCE, encoding="utf-8")
    report = tmp_path / "report.json"

    status = _audit_module().main([str(source), "--out", str(report)])

    assert status == 0
    assert sorted(path.name for path in tmp_path.rglob("*")) == ["report.json", "test_sample.py", "tree"]
    assert json.loads(report.read_text(encoding="utf-8"))["test_functions"] == 3
