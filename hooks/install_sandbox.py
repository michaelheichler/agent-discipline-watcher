"""Offline, because a real install fetches a 60 MB KB."""
from __future__ import annotations

import os
from pathlib import Path


def sandbox_env(home: Path | str, *, inherit: bool = False, **extra: str) -> dict[str, str]:
    """Offline always, because every test run would download."""
    base = dict(os.environ) if inherit else {}
    return {**base, "HOME": str(home), "ADW_OFFLINE": "1", **extra}
