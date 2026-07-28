from __future__ import annotations

import re
import time

from lib.config import effective_config
from lib.hookio import advise, allow, deny, read_payload, write_payload
from lib.protected import path_findings
from lib.reporting import compact_block, record_findings, run_with_ledger
from lib.scanner import scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)
OBSERVE_PREFIX = (
    "agent-discipline-watcher is observing these, not blocking. "
    "Judge each one and either repair it or state why it stands.\n"
)


def pending_writes(payload: dict) -> list[tuple[str, str]]:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or "<pending>"
    if "content" in tool_input:
        return [(path, str(tool_input.get("content") or ""))]
    if "new_string" in tool_input:
        return [(path, str(tool_input.get("new_string") or ""))]
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return [(path, "\n".join(str(edit.get("new_string", "")) for edit in edits if isinstance(edit, dict)))]
    patch = tool_input.get("patch") or tool_input.get("command") or tool_input.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    if isinstance(patch, str) and patch:
        split = split_patch(patch)
        return split if split else [(path, patch)]
    return []


def split_patch(patch: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    current = ""
    lines: list[str] = []
    for line in patch.splitlines():
        match = PATCH_FILE.match(line)
        if match:
            if current and lines:
                rows.append((current, "\n".join(lines)))
            current = match.group(1).strip().strip('"')
            lines = []
            continue
        if current and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if current and lines:
        rows.append((current, "\n".join(lines)))
    return rows


def run(payload: dict, config: dict | None = None) -> dict:
    """Scan a pending write, recording the decision so the edit gate leaves the same evidence the commit gate does."""
    cfg = effective_config(config, payload.get("cwd") or None)
    return run_with_ledger(
        hook="pre_write",
        payload=payload,
        gate=lambda turn_id: _gate(payload, cfg, turn_id),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _gate(payload: dict, cfg: dict, turn_id: str) -> dict:
    started = time.monotonic()
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    findings = _pending_findings(payload, cfg)
    if not findings:
        return allow()
    decisions = record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_write",
        event="PreToolUse", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=cfg.get("ledger_root"), config=cfg,
    )
    return _verdict(decisions, cfg)


def _verdict(decisions: list[tuple[dict, str]], cfg: dict) -> dict:
    """Deny on an enforced finding, otherwise report an observed one so the agent must weigh it before moving on."""
    blocking = [finding for finding, outcome in decisions if outcome == "block"]
    if blocking:
        reason, _ = compact_block(blocking, cfg)
        return deny(reason)
    observed = [finding for finding, outcome in decisions if outcome == "would_block"]
    if not observed:
        return allow()
    reason, _ = compact_block(observed, cfg)
    return advise(OBSERVE_PREFIX + reason, "PreToolUse")


def _pending_findings(payload: dict, cfg: dict) -> list[dict]:
    findings = []
    for path, text in pending_writes(payload):
        for finding in list(path_findings(path, cfg)) + scan_all(path, text, cfg):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


if __name__ == "__main__":
    write_payload(run(read_payload()))
