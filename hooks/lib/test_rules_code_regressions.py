"""Because examples resemble calls, scanner decisions need execution-scope coverage."""

import json
from pathlib import Path

import pytest
import pre_write

from lib.scanner import scan_all
from lib.test_units import extract


FIXTURES = Path(__file__).parent / "fixtures" / "rules_code"


def cases() -> list:
    """Because review results need comparison, retain their exact inputs."""
    names = ("batch1", "batch2", "extra", "scope_edges", "string_edges", "batch5")
    batches = [
        json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")) for name in names
    ]
    selected = [case for batch in batches for case in batch if relevant(case)]
    return [pytest.param(case, case["kind"] == "FN" or case["name"] == "long_docstring",
                         id=case["name"]) for case in selected]


def relevant(case: dict) -> bool:
    """Because external types remain unknown, omit guesses and unrelated calibration rows."""
    if case["name"] == "patch_imported_concrete" or case["rule"] == "test_write_gate":
        return False
    return case.get("batch") != "batch5.json" or case["rule"] == "function_too_long"


@pytest.mark.parametrize("case, expected", cases())
def test_scanner_distinguishes_executable_smells_from_examples(
    case: dict, expected: bool, tmp_path: Path,
) -> None:
    findings = scan_all(
        str(tmp_path / case["path"]), case["text"],
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )

    assert (case["rule"] in {row["rule"] for row in findings}) is expected


@pytest.mark.parametrize(
    "scenario",
    [
        ("exposing_private_methods_for_testing",
         "# Because obj._private() must stay unused.", False),
        ("incomplete_mock_call_verification",
         "# Because mock.assert_called_once() misses arguments.", False),
        ("exposing_private_methods_for_testing",
         "# Because monkeypatch.setattr(client, '_send') hides the seam.", False),
        ("exposing_private_methods_for_testing", "client._send()", True),
        ("incomplete_mock_call_verification", "mock.assert_called_once()", True),
    ],
)
def test_comments_do_not_impersonate_private_calls_or_mock_checks(
    scenario: tuple[str, str, bool], tmp_path: Path,
) -> None:
    rule, text, expected = scenario
    findings = scan_all(
        str(tmp_path / "test_note.py"), f"def test_note():\n    {text}\n    assert True\n",
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )

    assert (rule in {row["rule"] for row in findings}) is expected


def test_mock_call_arguments_complete_count_verification(tmp_path: Path) -> None:
    source = (
        "from unittest.mock import Mock, call\n"
        "def test_send():\n"
        "    sender = Mock()\n"
        "    sender.send('payload')\n"
        "    assert sender.send.call_count == 1\n"
        "    assert sender.send.call_args == call('payload')\n"
    )

    findings = scan_all(
        str(tmp_path / "test_send.py"), source,
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )

    assert "incomplete_mock_call_verification" not in {row["rule"] for row in findings}


def test_describe_suite_yields_only_inner_test_span() -> None:
    source = (
        "describe('suite', () => {\n"
        "  it('case', () => {\n"
        "    for (const v of values) { expect(v).toBe(1); }\n"
        "  });\n"
        "});\n"
    )

    units = extract("sample.test.ts", source)

    assert [(unit.start, unit.end) for unit in units] == [(2, 4)]


def test_declared_typescript_test_in_source_still_blocks_writing(tmp_path: Path) -> None:
    payload = {
        "cwd": str(tmp_path), "session_id": "source-test", "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "src" / "helpers.ts"),
                       "content": "test('value', () => { expect(value).toBe(1); });\n"},
    }
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}

    response = pre_write.run(payload, config)

    assert response["decision"] == "block"
    ledger = tmp_path / "ledger" / "ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert any(row["rule"] == "test_write_gate" and row["outcome"] == "block" for row in rows)
