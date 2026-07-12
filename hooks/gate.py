from __future__ import annotations

from lib.config import effective_config
from lib.hookio import read_payload, stop_block, system_message, write_payload
from lib.ledger import all_findings
from lib.model_jury import judge_touched
from lib.reporting import compact_block, compact_system_message, split_findings


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    payload = payload or {}
    cfg = effective_config(config, payload.get("cwd") or None)
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    findings = all_findings(cfg)
    try:
        findings.extend(judge_touched(payload, cfg))
    except Exception:
        pass
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
