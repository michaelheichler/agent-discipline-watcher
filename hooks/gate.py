from __future__ import annotations

from pathlib import Path

from lib.config import effective_config
from lib.hookio import read_payload, stop_block, system_message, write_payload
from lib.ledger import touched_files
from lib.reporting import compact_block, compact_system_message, split_findings
from lib.scanner import _is_exempt, read_scannable, scan_all


def current_findings(config: dict) -> list[dict]:
    rows: list[dict] = []
    for raw_path in touched_files(config):
        if _is_exempt(raw_path, config):
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        text = read_scannable(path, config)
        if text is None:
            continue
        for finding in scan_all(str(path), text, config):
            item = dict(finding)
            item["path"] = str(path)
            rows.append(item)
    return rows


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    payload = payload or {}
    cfg = effective_config(config, payload.get("cwd") or None)
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    findings = current_findings(cfg)
    forced, advisory = split_findings(findings)
    if forced:
        reason, _ = compact_block(forced, cfg, report_findings=findings, advisory_count=len(advisory))
        return stop_block(reason)
    if advisory:
        message, _ = compact_system_message(advisory, cfg)
        return system_message(message)
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
