"""ADW-owned process boundary for the official openai-codex SDK."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .judge_contracts import JudgeRequest, ReviewKind
from .luna_provider import LunaJudge, LunaProviderFailure


def main() -> int:
    try:
        row = json.loads(sys.stdin.read())
        request = JudgeRequest(
            review_kind=ReviewKind(row["review_kind"]), candidates=tuple(row["candidates"]),
            source_context=row["source_context"], rule_name=row["rule_name"],
            rule_action=row["rule_action"], violating_examples=tuple(row["violating_examples"]),
            clean_examples=tuple(row["clean_examples"]), rubric_version=row["rubric_version"],
        )
        judge = LunaJudge(
            runtime_root=Path(row["runtime_root"]), cache_root=Path(row["cache_root"]),
            auth_source=Path(row["auth_source"]), worker_mode=True,
        )
        result = judge.judge(request)
        print(json.dumps({"result": result.__dict__}, ensure_ascii=True))
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print(json.dumps({"error": "invalid worker request"}))
        return 2
    except LunaProviderFailure as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
