import pytest

from lib.findings import finding_row


def test_rule_rows_trim_bound_and_omit_absent_metadata() -> None:
    row = finding_row(
        "english", "filler", 2, "literal fixture", "  " + "s" * 200 + "  ",
        "Rewrite.", match="m" * 200,
    )

    assert row == {
        "family": "english", "rule": "filler", "line": 2,
        "detail": "literal fixture", "force": True, "snippet": "s" * 180,
        "action": "Rewrite.", "match": "m" * 180,
    }


@pytest.mark.parametrize(
    "line, detail",
    [pytest.param(True, "fixture", id="boolean-line"), pytest.param(2, 17, id="numeric-detail")],
)
def test_rule_rows_reject_invalid_coordinates_and_details(line, detail) -> None:
    with pytest.raises(TypeError):
        finding_row("english", "filler", line, detail, "snippet", "Rewrite.")
