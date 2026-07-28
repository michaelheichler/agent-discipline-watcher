from __future__ import annotations

import re

from lib.config import effective_config
from lib.hookio import allow, deny, read_payload, write_payload
from lib.protected import path_findings
from lib.reporting import compact_block
from lib.scanner import scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)


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
    cfg = effective_config(config, payload.get("cwd") or None)
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    findings = []
    for path, text in pending_writes(payload):
        for finding in list(path_findings(path, cfg)) + scan_all(path, text, cfg):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    if not findings:
        return allow()
    reason, _ = compact_block(findings, cfg)
    return deny(reason)


if __name__ == "__main__":
    write_payload(run(read_payload()))
