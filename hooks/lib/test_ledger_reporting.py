import os

import reporting
from reporting import compact_block


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


def test_reporting_has_no_advisory_path():
    assert not hasattr(reporting, "split_findings")
    assert not hasattr(reporting, "compact_system_message")


if __name__ == "__main__":
    test_compact_block_writes_private_full_report()
    test_reporting_has_no_advisory_path()
