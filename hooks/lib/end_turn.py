from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import blocker_state, document_review, payloads, scan_input, session_state
from .baseline import strip_committed
from .config import resolve_outcome
from .reporting import compact_block
from .scanner import read_scannable, scan_all

NOTICE_LEAD = "agent-discipline-watcher: subagents ended with findings you did not write."
NOTICE_MAX_SCOPES = 5
NOTICE_MAX_FILES = 3


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


def _document_digest(path: Path) -> str:
    try:
        return document_review.digest_of(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ""


def _stale_document_keys(pending: dict[str, str], state: dict) -> set[str]:
    # WHY: An edit moves the lines a note quotes.
    prefix = document_review.BLOCKER_KEY_PREFIX
    stale = set()
    for key in pending:
        if not key.startswith(prefix):
            continue
        path = Path(key[len(prefix):])
        digest = _document_digest(path)
        if not digest or digest != document_review.previous(state, str(path))[0]:
            stale.add(key)
    return stale


def _residual_reasons(pending: dict[str, str], paths: list[str], stale: set[str]) -> list[str]:
    resolved = set(paths) | stale | {"<batch>"}
    return [value for key, value in pending.items() if key not in resolved]


def _scope_reason(payload: dict, cfg: dict, agent_id: str) -> str:
    session_id = payloads.session_id(payload)
    root = cfg.get("state_root")
    pending, paths, revision = blocker_state.details(session_id, agent_id, root)
    stale = _stale_document_keys(pending, session_state.read_state_strict(session_id, root))
    cwd = payloads.cwd(payload)
    findings, existing = _blocking_rows(paths, Path(cwd or "."), cfg)
    findings.extend(_batch_findings(BatchScanRequest(session_id, cwd, tuple(existing), cfg)))
    if findings:
        reason = compact_block(findings, cfg)[0]
        return "\n".join(dict.fromkeys([reason, *_residual_reasons(pending, paths, stale)]))
    path_keys = set(paths)
    cleared = [key for key in pending if key in path_keys or key in stale]
    if paths:
        cleared.append("<batch>")
    blocker_state.reconcile(session_id, agent_id, revision, cleared, paths, root)
    return _remaining_reason(session_id, agent_id, root)


def unresolved_reason(payload: dict, cfg: dict) -> str:
    """Own scope only, because a parent cannot repair a file a subagent owns and loops on it."""
    session_id = payloads.session_id(payload)
    if not session_id:
        return ""
    return _scope_reason(payload, cfg, payloads.agent_id(payload))


def _notice_files(pending: dict[str, str], paths: list[str]) -> str:
    names = {Path(key).name for key in list(pending) + paths if "/" in key}
    listed = sorted(names)[:NOTICE_MAX_FILES]
    return ", ".join(listed) if listed else "files it edited"


def _notice_line(scope: str, pending: dict[str, str], paths: list[str]) -> str:
    count = len(pending)
    plural = "" if count == 1 else "s"
    return f"{scope} left {count} unresolved finding{plural} in {_notice_files(pending, paths)}."


def foreign_scope_notice(payload: dict, cfg: dict) -> str:
    """A count, because the parent must learn work was left without paying for the checklist twice."""
    session_id = payloads.session_id(payload)
    if not session_id or payloads.agent_id(payload):
        return ""
    root = cfg.get("state_root")
    lines = []
    for scope in blocker_state.scope_ids(session_id, root):
        if not scope:
            continue
        pending, paths, revision = blocker_state.details(session_id, scope, root)
        if not pending:
            continue
        lines.append(_notice_line(scope, pending, paths))
        blocker_state.reconcile(session_id, scope, revision, list(pending), paths, root)
    if len(lines) > NOTICE_MAX_SCOPES:
        lines = lines[:NOTICE_MAX_SCOPES] + [f"... {len(lines) - NOTICE_MAX_SCOPES} more agents left findings."]
    return "\n".join([NOTICE_LEAD, *lines]) if lines else ""
