import json
from pathlib import Path

import pytest

from lib.mcp_paths import mcp_arguments, mcp_is_mutation, mcp_operation


FIXTURES = Path(__file__).parent / "fixtures" / "mcp_golden.json"
CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))
LIMITS = json.loads((Path(__file__).parent / "mcp_contract.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", [case for case in CASES if not case.get("error")])
def test_shared_mcp_cases_preserve_targets_operation_and_mutation(case) -> None:
    arguments = case["arguments"]
    name = case["tool_name"]

    assert mcp_arguments(arguments).paths == case["targets"]
    assert mcp_operation(name, arguments) == tuple(case["operation"])
    assert mcp_is_mutation(name, arguments) is case["mutation"]


@pytest.mark.parametrize("case", [case for case in CASES if case.get("error")])
def test_shared_mcp_cases_reject_unsafe_file_uris(case) -> None:
    with pytest.raises(ValueError):
        mcp_arguments(case["arguments"])


def nested_arguments(depth: int) -> object:
    value = "body"
    for _ in range(depth):
        value = {"payload": value}
    return value


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param([None] * (LIMITS["max_argument_nodes"] - 1), id="node-boundary"),
        pytest.param(nested_arguments(LIMITS["max_argument_depth"]), id="depth-boundary"),
    ],
)
def test_mcp_inspection_accepts_the_shared_limit(arguments) -> None:
    assert mcp_arguments(arguments).paths == []


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param([None] * LIMITS["max_argument_nodes"], id="too-many-nodes"),
        pytest.param(nested_arguments(LIMITS["max_argument_depth"] + 1), id="too-deep"),
    ],
)
def test_mcp_inspection_rejects_arguments_beyond_the_shared_limit(arguments) -> None:
    with pytest.raises(ValueError):
        mcp_arguments(arguments)
