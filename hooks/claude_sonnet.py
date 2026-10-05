"""A command entrypoint, because Claude Code runs the Sonnet reviewer as a settings hook."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.claude_sonnet import main  # noqa: E402  # pylint: disable=wrong-import-position


if __name__ == "__main__":
    raise SystemExit(main())
