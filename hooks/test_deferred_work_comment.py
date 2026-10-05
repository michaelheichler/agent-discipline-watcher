"""Keep the marker a warning only because long and multi-line comments must still block."""
from __future__ import annotations

import pytest

import pre_write
from lib import reporting
from lib.comment_rules import COMMENT_CHAR_CAP
from lib.config import resolve_outcome
from lib.findings import Outcome
from lib.scanner import scan_all

DEFERRED_TAG = "TO" + "DO"


def _outcomes(source: str) -> dict[str, Outcome]:
    return {row["rule"]: resolve_outcome(row, {}) for row in scan_all("sample.py", source, {})}


@pytest.mark.parametrize("line", [
    DEFERRED_TAG + ": handle retries",
    DEFERRED_TAG + " handle retries",
    "FIX" + "ME: handle retries",
])
def test_a_short_marker_line_gives_only_the_observed_finding(line: str) -> None:
    assert _outcomes("# " + line + "\nx = 1\n") == {"deferred_work_comment": Outcome.WOULD_BLOCK}


def test_a_short_marker_line_reaches_the_agent_as_a_warning() -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "sample.py", "content": "# " + DEFERRED_TAG + ": handle retries\nx = 1\n"},
    }
    response = pre_write.run(payload, {"baseline": "none"})
    context = response["hookSpecificOutput"]["additionalContext"]
    assert "decision" not in response
    assert reporting.OBSERVE_LEAD in context
    assert "deferred_work_comment" in context


def test_a_project_can_gate_the_marker_rule_off() -> None:
    rows = scan_all("sample.py", "# " + DEFERRED_TAG + ": handle retries\nx = 1\n", {})
    gates = {"rule_gates": {"deferred_work_comment": "off"}}
    assert [resolve_outcome(row, gates) for row in rows] == [Outcome.RELEASE]


def test_a_marker_line_over_the_cap_still_blocks_as_a_long_comment() -> None:
    source = "# " + DEFERRED_TAG + ": " + "x" * COMMENT_CHAR_CAP + "\nx = 1\n"
    assert _outcomes(source)["long_comment"] == Outcome.BLOCK


def test_a_marker_line_followed_by_prose_still_blocks_as_a_comment_block() -> None:
    source = "# " + DEFERRED_TAG + ": handle retries\n# and back off on a 429\nx = 1\n"
    assert _outcomes(source)["prose_comment_block"] == Outcome.BLOCK


def test_only_the_tag_colon_is_exempt_from_the_prose_colon_rule() -> None:
    source = "# " + DEFERRED_TAG + ": handle retries: soon\nx = 1\n"
    assert _outcomes(source)["prose_colon"] == Outcome.BLOCK
