"""Kept to one notice, because the agent cannot be asked to own copied text it never wrote."""
from __future__ import annotations

from lib import catalog_de
from lib.config import resolve_outcome
from lib.finding_output import Lead
from lib.findings import Finding, Outcome
from lib.reporting import compact_block


def imported_advice(findings: list[dict | Finding], config: dict | None = None) -> str:
    rows = [finding.to_dict() if isinstance(finding, Finding) else finding for finding in findings]
    live = [finding for finding in rows if resolve_outcome(finding, config) != Outcome.RELEASE]
    if not live:
        return ""
    files = len({str(finding.get("path") or "") for finding in live})
    lead = (
        f"agent-discipline-watcher: imported content, not yours. {len(live)} findings in {files} "
        "copied files. Nothing blocks. Fix them only if you now own this content."
    )
    german = catalog_de.IMPORTED_LEAD.format(count=len(live), files=files)
    return compact_block(live, config, lead=Lead(lead, german))[0]
