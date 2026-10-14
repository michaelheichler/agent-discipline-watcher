from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import blocker_state, imported_baseline, payloads, stop_scan
from .config import resolve_outcome
from .reporting import compact_block
from .stop_stall import BlockingSet, ReasonBuilder, StopCall, StopOutcome, guarded

NOTICE_LEAD = "agent-discipline-watcher: subagents ended with findings you did not write."
NOTICE_MAX_SCOPES = 5
NOTICE_MAX_FILES = 3


@dataclass(frozen=True, slots=True)
class BatchScanRequest:
    session_id: str
    cwd: str
    paths: tuple[str, ...]
    config: dict
    deadline: float = float("inf")


def _agent_written(paths: tuple[str, ...], cfg: dict) -> list[str]:
    """Kept out while unchanged since import, because the agent wrote neither copy."""
    kept = []
    for path in paths:
        snapshot = imported_baseline.lookup(cfg, path)
        if snapshot is None or imported_baseline.file_digest(path) != snapshot.digest:
            kept.append(path)
    return kept


def _batch_findings(request: BatchScanRequest, pending: dict[str, str]) -> list[dict]:
    """Only while the batch gate holds a block, because Stop must not find duplicates across batches that the batch gate never judged."""
    if "<batch>" not in pending or len(request.paths) < 2 or time.monotonic() > request.deadline:
        return []
    import batch
    rows = batch.duplicate_findings_for_paths(request.cwd, _agent_written(request.paths, request.config), request.config)
    return [row for row in rows if resolve_outcome(row, request.config) == "block"]


def _remaining_reason(session_id: str, agent_id: str, root) -> str:
    pending, _paths, _revision = blocker_state.details(session_id, agent_id, root)
    return "\n".join(dict.fromkeys(pending.values()))


def _residual_reasons(pending: dict[str, str], paths: list[str]) -> list[str]:
    resolved = set(paths) | {"<batch>"}
    return [value for key, value in pending.items() if key not in resolved]


def _finding_reason(blocking: BlockingSet, cfg: dict) -> ReasonBuilder:
    def build(report: str | None) -> tuple[str, str]:
        if not blocking.findings:
            return "\n".join(dict.fromkeys(blocking.residual)), ""
        reason, written = compact_block(blocking.findings, cfg, report_path=report)
        return "\n".join(dict.fromkeys([reason, *blocking.residual])), written

    return build


def _scope_outcome(payload: dict, call: StopCall) -> StopOutcome:
    scope, cfg = call.scope, call.cfg
    pending, paths, revision = blocker_state.details(scope.session_id, scope.agent_id, scope.root)
    cwd = payloads.cwd(payload)
    until = stop_scan.deadline()
    scanned = stop_scan.rescan(paths, Path(cwd or "."), cfg, until)
    request = BatchScanRequest(scope.session_id, cwd, tuple(scanned.existing), cfg, until)
    findings = scanned.findings + _batch_findings(request, pending)
    if findings or scanned.skipped:
        residual = _residual_reasons(pending, paths)
        if scanned.skipped:
            residual.append(stop_scan.skipped_reason(scanned.skipped))
        blocking = BlockingSet(findings, residual)
        return guarded(call, blocking, _finding_reason(blocking, cfg))
    path_keys = set(paths)
    cleared = [key for key in pending if key in path_keys]
    if paths:
        cleared.extend(["<batch>", *blocker_state.RESCAN_RELEASED_KEYS])
    blocker_state.reconcile(scope.session_id, scope.agent_id, revision, cleared, paths, scope.root)
    remaining = _remaining_reason(scope.session_id, scope.agent_id, scope.root)
    if not remaining:
        return StopOutcome("", "")
    return guarded(call, BlockingSet([], remaining.split("\n")), lambda _report: (remaining, ""))


def stop_outcome(payload: dict, cfg: dict, *, hook: str = "stop", turn_id: str = "") -> StopOutcome:
    """Own scope only, because a parent cannot repair a file a subagent owns and loops on it."""
    session_id = payloads.session_id(payload)
    if not session_id:
        return StopOutcome("", "")
    scope = blocker_state.BlockerScope(session_id, payloads.agent_id(payload), cfg.get("state_root"))
    event = "SubagentStop" if scope.agent_id else "Stop"
    call = StopCall(scope, {**cfg, "session_id": session_id}, hook, event, turn_id)
    outcome = _scope_outcome(payload, call)
    dropped = blocker_state.take_dropped(scope)
    if not dropped:
        return outcome
    capped = (
        f"agent-discipline-watcher: {dropped} older edited files left the Stop rescan, "
        f"because one scope tracks at most {blocker_state.MAX_SCOPE_PATHS} files."
    )
    return StopOutcome(outcome.reason, "\n".join(part for part in (outcome.notice, capped) if part))


def unresolved_reason(payload: dict, cfg: dict) -> str:
    return stop_outcome(payload, cfg).reason


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
