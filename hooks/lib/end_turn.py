from __future__ import annotations

from pathlib import Path

from . import blocker_state, payloads, scan_input
from .baseline import strip_committed
from .config import resolve_outcome
from .reporting import compact_block
from .scanner import read_scannable, scan_all


def _blocking_rows(paths: list[str], cwd: Path, cfg: dict) -> tuple[list[dict], list[str]]:
    findings = []
    existing = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file():
            continue
        existing.append(str(path))
        text = read_scannable(path, cfg)
        if text is None:
            rows = scan_input.fallback_findings(path)
        else:
            rows = strip_committed(path, scan_all(str(path), text, cfg), cfg)
        findings.extend({**row, "path": str(path)} for row in rows if resolve_outcome(row, cfg) == "block")
    return findings, existing


def _batch_findings(session_id: str, cwd: str, paths: list[str], cfg: dict) -> list[dict]:
    if len(paths) < 2:
        return []
    import batch
    calls = [
        {
            "tool_name": "Write",
            "tool_use_id": f"end-{index}",
            "tool_input": {"file_path": path},
        }
        for index, path in enumerate(paths)
    ]
    rows = batch.findings_for_batch(
        {"session_id": session_id, "cwd": cwd, "tool_calls": calls}, cfg, "end-turn",
    )
    return [row for row in rows if resolve_outcome(row, cfg) == "block"]


def _remaining_reason(session_id: str, agent_id: str, root) -> str:
    pending, _paths, _revision = blocker_state.details(session_id, agent_id, root)
    return "\n".join(dict.fromkeys(pending.values()))


def _residual_reasons(pending: dict[str, str], paths: list[str]) -> list[str]:
    resolved = set(paths) | {"<batch>"}
    return [value for key, value in pending.items() if key not in resolved]


def _scope_reason(payload: dict, cfg: dict, agent_id: str) -> str:
    session_id = payloads.session_id(payload)
    root = cfg.get("state_root")
    pending, paths, revision = blocker_state.details(session_id, agent_id, root)
    cwd = payloads.cwd(payload)
    findings, existing = _blocking_rows(paths, Path(cwd or "."), cfg)
    findings.extend(_batch_findings(session_id, cwd, existing, cfg))
    if findings:
        reason = compact_block(findings, cfg)[0]
        return "\n".join(dict.fromkeys([reason, *_residual_reasons(pending, paths)]))
    path_keys = set(paths)
    cleared = [key for key in pending if key in path_keys]
    if paths:
        cleared.append("<batch>")
    blocker_state.reconcile(session_id, agent_id, revision, cleared, paths, root)
    return _remaining_reason(session_id, agent_id, root)


def unresolved_reason(payload: dict, cfg: dict) -> str:
    session_id = payloads.session_id(payload)
    if not session_id:
        return ""
    agent_id = payloads.agent_id(payload)
    scopes = [agent_id] if agent_id else blocker_state.scope_ids(session_id, cfg.get("state_root"))
    reasons = [_scope_reason(payload, cfg, scope) for scope in scopes]
    return "\n".join(dict.fromkeys(reason for reason in reasons if reason))
