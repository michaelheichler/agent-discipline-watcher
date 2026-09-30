from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_presets, luna_provider
from lib.luna_provider import LunaJudge

CODEX_HOOKS = Path(__file__).parents[1] / "codex-hooks.json"


def _hook_timeouts() -> set[int]:
    claude = {
        hook["timeout"]
        for groups in claude_presets.generated_hooks("luna").values()
        for group in groups
        for hook in group["hooks"]
    }
    codex = json.loads(CODEX_HOOKS.read_text(encoding="utf-8"))["hooks"]["Stop"]
    return claude | {hook["timeout"] for group in codex for hook in group["hooks"]}


def test_the_provider_deadline_ends_before_the_host_kills_the_hook() -> None:
    """Shorter, because a killed hook reports no reason."""
    assert all(luna_provider.JUDGE_TIMEOUT_SECONDS < timeout for timeout in _hook_timeouts())


@pytest.mark.parametrize("timeout_seconds", (float("nan"), float("inf"), -float("inf"), 10**400))
def test_timeout_rejects_nonfinite_and_unrepresentably_large_values(timeout_seconds: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        LunaJudge(timeout_seconds=timeout_seconds)
