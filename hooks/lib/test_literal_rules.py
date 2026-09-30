"""Pin the literal rules, because each must spare real tests."""
from __future__ import annotations

from lib import test_rules
from lib.test_rules import literals

SPEC_RUST = '''#[test]
fn every_sex_the_profile_form_offers_keeps_the_mechanistic_method_ready() {
    for sex in ["m\\u{e4}nnlich", "weiblich", "divers", "keine-angabe"] {
        let (mut profile, events, command, cutoff) = saved();
        profile["sex"] = json!(sex);
        let prepared = prepare_from_saved(&profile, &events, &command, cutoff).unwrap();
        let response = forecast_pathways(&prepared.request()).unwrap();
        assert_eq!(response["pathways"][0]["status"], "ready", "{sex}: {response}");
    }
}
'''

LOOP_PYTHON = '''import unittest


def test_each_rule_blocks() -> None:
    for rule in ("a", "b"):
        assert scan(rule) == ["block"], rule


class Cases(unittest.TestCase):
    def test_each_rule_reports_alone(self) -> None:
        for rule in ("a", "b"):
            with self.subTest(rule=rule):
                self.assertEqual(scan(rule), ["block"])


def test_rows_are_checked_after_the_loop() -> None:
    rows = [scan(rule) for rule in ("a", "b")]
    assert rows == [["block"], ["block"]]
'''

NAME_PYTHON = '''from lib import catalog
from lib.models import CLAUDE_SONNET_MODEL, FAMILIES


def test_the_closer_is_listed() -> None:
    assert "ai_closer" in catalog.RULES


def test_the_model_is_pinned() -> None:
    assert CLAUDE_SONNET_MODEL == "claude-sonnet-5-5"


class Families(unittest.TestCase):
    def test_english_is_a_family(self) -> None:
        self.assertIn("english", FAMILIES)


def test_render_returns_the_heading() -> None:
    assert render(PAGE) == "# Title"


def test_the_job_turns_ready() -> None:
    result = run_job(JOB)
    assert result["status"] == "ready"
    STATUS = run_job(JOB)
    assert STATUS == "ready"
'''

SOURCE_PYTHON = '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "hooks" / "run.sh"


def test_the_launcher_drops_the_old_runtime() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "run.sh Stop" not in launcher


def test_the_manifest_names_the_plugin() -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text())
    assert manifest["name"] == "agent-discipline-watcher"


def test_the_report_names_the_rule(tmp_path) -> None:
    report = tmp_path / "report.md"
    write_report(report, FINDINGS)
    assert "ai_closer" in report.read_text()


def test_the_scanner_flags_the_readme() -> None:
    rows = scan_all(Path("README.md").read_text())
    assert "ai_closer" in rows
'''

RUST_LITERALS = '''#[test]
fn the_model_is_pinned() {
    assert_eq!(MODEL, "claude-sonnet-5-5");
    assert!(config::RULES.contains_key("ai_closer"));
}

#[test]
fn the_manifest_names_the_stop_hook() {
    let manifest = include_str!("../hooks.json");
    assert!(manifest.contains("Stop"));
}

#[test]
fn the_forecast_turns_ready() {
    let response = forecast(&input());
    assert_eq!(response.status, "ready");
    let written = fs::read_to_string(dir.path().join("out.txt")).unwrap();
    assert!(written.contains("ready"));
}
'''


def _hits(path: str, source: str) -> list[tuple[str, int]]:
    rows = test_rules.check_file(path, source, (literals.RULE_SET,))
    return [(row["rule"], row["line"]) for row in rows]


def test_the_spec_rust_example_asserts_inside_its_loop() -> None:
    assert _hits("src/forecast.rs", SPEC_RUST) == [("assert_in_loop", 8)]


def test_a_python_loop_hits_unless_each_case_reports_through_subtest() -> None:
    assert _hits("tests/test_loops.py", LOOP_PYTHON) == [("assert_in_loop", 6)]


def test_a_literal_checked_against_a_static_table_pins_a_name() -> None:
    expected = [("hardcoded_name_presence", line) for line in (6, 10, 15)]

    assert _hits("tests/test_names.py", NAME_PYTHON) == expected


def test_a_literal_in_a_read_source_file_restates_the_source() -> None:
    expected = [("hardcoded_literal_in_source", 9), ("hardcoded_literal_in_source", 14)]

    assert _hits("tests/test_source.py", SOURCE_PYTHON) == expected


def test_rust_pins_names_and_source_text_but_spares_computed_output() -> None:
    assert _hits("src/lib.rs", RUST_LITERALS) == [
        ("hardcoded_name_presence", 3),
        ("hardcoded_name_presence", 4),
        ("hardcoded_literal_in_source", 10),
    ]
