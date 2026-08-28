from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import blocker_state, document_review, payloads, scan_input
from .baseline import strip_committed
from .config import resolve_outcome
from .reporting import compact_block
from .scanner import read_scannable, scan_all


@dataclass(frozen=True, slots=True)
class BatchScanRequest:
    session_id: str
    cwd: str
    paths: tuple[str, ...]
    config: dict


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


def _batch_findings(request: BatchScanRequest) -> list[dict]:
    """Call batch directly here because a fabricated multi-call payload never correlated with a real journal row, so its ledger dedup was always inert."""
    if len(request.paths) < 2:
        return []
    import batch
    rows = batch.findings_for_paths(
        request.session_id,
        request.cwd,
        list(request.paths),
        request.config,
        "<end-turn>",
    )
    return [row for row in rows if resolve_outcome(row, request.config) == "block"]


def _remaining_reason(session_id: str, agent_id: str, root) -> str:
    pending, _paths, _revision = blocker_state.details(session_id, agent_id, root)
    return "\n".join(dict.fromkeys(pending.values()))


def _document_target_is_gone(key: str) -> bool:
    prefix = document_review.BLOCKER_KEY_PREFIX
    return key.startswith(prefix) and not Path(key[len(prefix):]).is_file()


def _residual_reasons(pending: dict[str, str], paths: list[str]) -> list[str]:
    # WHY: A deleted file can never clear a blocker keyed on its path.
    resolved = set(paths) | {"<batch>"}
    return [
        value for key, value in pending.items()
        if key not in resolved and not _document_target_is_gone(key)
    ]


def _scope_reason(payload: dict, cfg: dict, agent_id: str) -> str:
    session_id = payloads.session_id(payload)
    root = cfg.get("state_root")
    pending, paths, revision = blocker_state.details(session_id, agent_id, root)
    cwd = payloads.cwd(payload)
    findings, existing = _blocking_rows(paths, Path(cwd or "."), cfg)
    findings.extend(_batch_findings(BatchScanRequest(session_id, cwd, tuple(existing), cfg)))
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
