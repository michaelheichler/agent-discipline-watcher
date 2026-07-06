import os

from ledger import all_findings, clear_ledger, record_findings, read_ledger
from reporting import compact_block


def test_ledger_record_read_clear_and_replace(tmp_path):
    cfg = {"ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json")}
    one = {"family": "english", "rule": "utilize", "line": 1, "force": True, "action": "Use 'use'."}
    two = {"family": "punctuation", "rule": "banned_dash", "line": 2, "force": True, "action": "Use hyphen."}
    record_findings("a.txt", [one], cfg)
    record_findings("a.txt", [two], cfg)
    assert read_ledger(cfg) == [{"path": "a.txt", "findings": [two], "touched": True}]
    assert all_findings(cfg)[0]["path"] == "a.txt"
    clear_ledger(cfg)
    assert read_ledger(cfg) == []


def test_compact_block_writes_private_full_report():
    finding = {
        "path": "a.txt",
        "family": "english",
        "rule": "utilize",
        "line": 1,
        "force": True,
        "action": "Use 'use'.",
        "snippet": "We util" + "ize this source line",
    }
    reason, report = compact_block([finding], {"max_rows": 4})
    assert "snippet" not in reason
    assert "Full report:" in reason
    assert oct(os.stat(report).st_mode & 0o777) == "0o600"


if __name__ == "__main__":
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_ledger_record_read_clear_and_replace(Path(directory))
    test_compact_block_writes_private_full_report()
