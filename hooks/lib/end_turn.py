from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from . import blocker_state, payloads, scan_input
from .baseline import split_fallback, strip_committed
from .config import resolve_outcome
from .reporting import compact_block
from .scanner import read_scannable, scan_all
from .stop_stall import BlockingSet, ReasonBuilder, StopCall, StopOutcome, guarded
from .temp_scope import outside_project_temp

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
        if not path.is_file() or outside_project_temp(path, cwd):
            continue
        existing.append(str(path))
        text = read_scannable(path, cfg)
        if text is None:
            stamp = path.stat()
            rows = split_fallback(path, scan_input.fallback_findings(path), cfg)[0]
            rows = [{**row, "content_hash": f"{stamp.st_size}:{stamp.st_mtime_ns}"} for row in rows]
        else:
            rows = strip_committed(path, scan_all(str(path), text, cfg), cfg, text)
            digest = sha256(text.encode("utf-8")).hexdigest()
            rows = [{**row, "content_hash": digest} for row in rows]
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


def _residual_reasons(pending: dict[str, str], paths: list[str]) -> list[str]:
    resolved = set(paths) | {"<batch>"}
    return [value for key, value in pending.items() if key not in resolved]


def _finding_reason(blocking: BlockingSet, cfg: dict) -> ReasonBuilder:
    def build(report: str | None) -> tuple[str, str]:
        reason, written = compact_block(blocking.findings, cfg, report_path=report)
        return "\n".join(dict.fromkeys([reason, *blocking.residual])), written

    return build


def _scope_outcome(payload: dict, call: StopCall) -> StopOutcome:
    scope, cfg = call.scope, call.cfg
    pending, paths, revision = blocker_state.details(scope.session_id, scope.agent_id, scope.root)
    cwd = payloads.cwd(payload)
    findings, existing = _blocking_rows(paths, Path(cwd or "."), cfg)
    findings.extend(_batch_findings(BatchScanRequest(scope.session_id, cwd, tuple(existing), cfg)))
    if findings:
        blocking = BlockingSet(findings, _residual_reasons(pending, paths))
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
    return _scope_outcome(payload, call)


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
