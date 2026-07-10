from __future__ import annotations

import json
import os

from lib.config import effective_config
from lib.hookio import read_payload, stop_block, system_message, write_payload
from lib.ledger import all_findings
from lib.model_jury import judge_touched
from lib.reporting import compact_block, compact_system_message, split_findings
from lib.tells import scan_tells


def _message_text(record: dict) -> str:
    source = record.get("message") if isinstance(record.get("message"), dict) else record
    content = source.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _is_assistant(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("type") == "assistant" or record.get("role") == "assistant":
        return True
    message = record.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def _from_transcript(path: object) -> str:
    if not isinstance(path, str) or not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if _is_assistant(record):
                    text = _message_text(record)
                    if text:
                        last = text
    except OSError:
        return ""
    return last


def _reply_text(payload: dict) -> str:
    direct = payload.get("last_assistant_message")
    if isinstance(direct, str) and direct.strip():
        return direct
    return _from_transcript(payload.get("transcript_path"))


def _pah_advisory_tail(reason: str, findings: list[dict], cfg: dict, advisory: list[dict]) -> str:
    pah_finding = {
        "path": "<assistant>",
        "family": "professional_agent_helper",
        "rule": findings[0]["rule"],
        "line": 1,
        "force": True,
        "action": reason,
        "tells": findings,
    }
    compact, _ = compact_block(
        [pah_finding],
        cfg,
        report_findings=[pah_finding] + advisory,
        advisory_count=len(advisory),
    )
    return "\n".join(
        line for line in compact.splitlines()
        if line.startswith("... ") or line.startswith("Full report:")
    )


def _pah_tell_block(payload: dict, cfg: dict, advisory: list[dict]) -> dict:
    if payload.get("stop_hook_active"):
        return {}
    findings = scan_tells(_reply_text(payload))
    if not findings:
        return {}
    items = ", ".join(f'{finding["rule"]} ("{finding["snippet"]}")' for finding in findings)
    reason = (
        "Professional Agent Helper blocked this reply for empty validators or "
        f"flattery: {items}. Rewrite it. Lead with the substance. If the user is "
        "right, say what is right and why, with no filler."
    )
    if advisory:
        reason = reason + "\n" + _pah_advisory_tail(reason, findings, cfg, advisory)
    return stop_block(reason)


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
    pah_block = _pah_tell_block(payload, cfg, advisory)
    if pah_block:
        return pah_block
    if advisory:
        message, _ = compact_system_message(advisory, cfg)
        return system_message(message)
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
