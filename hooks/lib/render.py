"""Render review records for humans and machines without changing their meaning."""

import json
from collections import Counter

SEVERITIES = ("block", "would_block", "release")


def _groups(findings: list[dict]) -> dict[str, list[dict]]:
    grouped = {}
    for item in findings:
        grouped.setdefault(item["path"], []).append(item)
    return grouped


def _counts(findings: list[dict]) -> dict[str, int]:
    found = Counter(item["severity"] for item in findings)
    return {severity: found.get(severity, 0) for severity in SEVERITIES}


def render_text(findings: list[dict], scope: str, revision: str = "working tree") -> str:
    """Group concise terminal findings under stable file headings."""
    counts = _counts(findings)
    summary = ", ".join(f"{key}={counts[key]}" for key in SEVERITIES)
    lines = [f"Review: {scope}", f"Revision: {revision}", f"Summary: {summary}"]
    for path, rows in sorted(_groups(findings).items()):
        lines.append(path)
        for item in sorted(rows, key=lambda row: (row["line"], row["rule"])):
            lines.append(
                f"  {item['line']}: {item['rule']} [{item['severity']}] "
                f"{item['excerpt']} Fix: {item['hint']}"
            )
    return "\n".join(lines) + "\n"


def _markdown_rows(rows: list[dict], lines: list[str]) -> None:
    for path, grouped in sorted(_groups(rows).items()):
        lines.append(f"### `{path}`")
        for item in sorted(grouped, key=lambda row: (row["line"], row["rule"])):
            excerpt = item["excerpt"].replace("`", "\\`")
            lines.append(
                f"- Line {item['line']}, `{item['rule']}`: {excerpt}. "
                f"Fix: {item['hint']}"
            )


def render_md(findings: list[dict], scope: str, revision: str = "working tree") -> str:
    """Shape findings for reports with scope, revision, and severity sections."""
    counts = _counts(findings)
    lines = [
        "# Agent Discipline Review",
        "",
        f"- Scope: `{scope}`",
        f"- Revision: `{revision}`",
        "",
        "## Summary",
        "",
        "| Severity | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {severity} | {counts[severity]} |" for severity in SEVERITIES)
    for severity in SEVERITIES:
        rows = [item for item in findings if item["severity"] == severity]
        if rows:
            lines.extend(["", f"## {severity}"])
            _markdown_rows(rows, lines)
    return "\n".join(lines) + "\n"


def render_json(findings: list[dict]) -> str:
    """Encode the fixed version-one positional schema without extra fields."""
    rows = [
        [
            item["rule"],
            item["severity"],
            item["path"],
            item["line"],
            item["excerpt"],
            item["hint"],
        ]
        for item in findings
    ]
    payload = {"v": 1, "s": _counts(findings), "f": rows}
    return json.dumps(payload, separators=(",", ":")) + "\n"
