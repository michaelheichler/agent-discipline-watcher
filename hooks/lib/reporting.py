from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def split_findings(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    forced = [item for item in findings if item.get("force")]
    advisory = [item for item in findings if not item.get("force")]
    return forced, advisory


def write_full_report(findings: list[dict]) -> str:
    fd, raw_path = tempfile.mkstemp(prefix="agent-discipline-watcher-", suffix=".json")
    path = Path(raw_path)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, ensure_ascii=True, indent=2)
    return str(path)


def compact_block(
    findings: list[dict],
    config: dict | None = None,
    report_findings: list[dict] | None = None,
    advisory_count: int = 0,
) -> tuple[str, str]:
    max_rows = int((config or {}).get("max_rows", 8))
    report = write_full_report(report_findings if report_findings is not None else findings)
    rows = [format_row(item) for item in findings[:max_rows]]
    extra = len(findings) - len(rows)
    if extra > 0:
        rows.append(f"... {extra} more")
    if advisory_count:
        rows.append(f"... {advisory_count} advisory findings in full report")
    reason = "agent-discipline-watcher blocked forced findings:\n" + "\n".join(rows)
    reason += "\nFull report: " + report
    return reason, report


def compact_system_message(findings: list[dict], config: dict | None = None) -> tuple[str, str]:
    max_rows = int((config or {}).get("max_rows", 8))
    report = write_full_report(findings)
    rows = [format_row(item) for item in findings[:max_rows]]
    extra = len(findings) - len(rows)
    if extra > 0:
        rows.append(f"... {extra} more")
    message = "agent-discipline-watcher advisory findings:\n" + "\n".join(rows)
    message += "\nFull report: " + report
    return message, report


def format_row(item: dict) -> str:
    path = item.get("path") or item.get("file") or "<pending>"
    return (
        f"{path}:{item.get('line')} "
        f"{item.get('family')}/{item.get('rule')}: "
        f"{item.get('action')}"
    )
