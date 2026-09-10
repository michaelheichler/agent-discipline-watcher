import json
from pathlib import Path

from lib import retention


def test_compaction_resolves_the_reports_root_once_and_filters_nonreports(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "kept.json"
    report.write_text("[]", encoding="utf-8")
    expected = report.resolve()
    ledger = tmp_path / "ledger.jsonl"
    ordinary = {"session_id": "live", "ts": "2026-09-10T00:00:00+00:00", "hook": "pre_write", "path": "/tmp/source.py"}
    rows = [ordinary] * 100 + [{"nested": [{"report": str(report)}]}]
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    resolved = []
    original = Path.resolve

    def tracked(path, *args, **kwargs):
        resolved.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", tracked)
    kept = retention._compact_ledger(ledger, 0, frozenset(), reports)

    assert kept == {expected}
    assert resolved.count(reports) == 1
    assert resolved == [reports, report]
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == len(rows)


def test_report_references_preserve_relative_paths_and_resolve_symlinks(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "kept.json"
    report.write_text("[]", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    (tmp_path / "shortcut.json").symlink_to(report)
    (reports / "escape.json").symlink_to(outside)
    monkeypatch.chdir(tmp_path)

    kept = retention._referenced_reports({"references": ["reports/kept.json", "shortcut.json", "reports/escape.json"]}, reports)

    assert kept == {report.resolve()}


def test_malformed_nonpaths_cannot_interrupt_retention(tmp_path):
    reports = tmp_path / "reports"
    malformed = {"snippet": "invalid\0.json", "message": "An ordinary sentence.", "counter": 3}

    assert retention._referenced_reports(malformed, reports) == set()


def test_invalid_reports_root_does_not_prevent_ledger_compaction(tmp_path):
    reports = tmp_path / "reports"
    reports.symlink_to(reports)
    ledger = tmp_path / "ledger.jsonl"
    old = {"ts": "2000-01-01T00:00:00+00:00", "report": str(reports / "old.json")}
    live = {"session_id": "live", "report": str(reports / "live.json")}
    ledger.write_text(json.dumps(old) + "\n" + json.dumps(live) + "\n", encoding="utf-8")

    assert retention._compact_ledger(ledger, 1_000_000_000, frozenset({"live"}), reports) == set()
    assert ledger.read_text(encoding="utf-8") == json.dumps(live) + "\n"
