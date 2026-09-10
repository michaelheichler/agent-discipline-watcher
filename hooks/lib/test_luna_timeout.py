from __future__ import annotations

import pytest

from lib.luna_provider import LunaJudge


@pytest.mark.parametrize("timeout_seconds", (float("nan"), float("inf"), -float("inf"), 10**400))
def test_timeout_rejects_nonfinite_and_unrepresentably_large_values(timeout_seconds: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        LunaJudge(timeout_seconds=timeout_seconds)
