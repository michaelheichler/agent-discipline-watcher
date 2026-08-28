from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_worker_rejects_an_invalid_protocol_request(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "lib.luna_worker"], input="not-json", text=True,
        capture_output=True, cwd=Path(__file__).parents[1], check=False,
    )

    body = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert body["error"] == "invalid worker request"
