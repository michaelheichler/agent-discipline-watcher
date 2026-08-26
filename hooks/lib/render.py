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


def _sanitize(value: object) -> str:
    return "".join(
        character if ord(character) > 31 and ord(character) != 127 else f"\\x{ord(character):02x}"
        for character in str(value)
    )


def _markdown(value: object) -> str:
    return "".join(
        f"\\{character}" if character in "\\`*_{}[]<>()#+-.!|~" else character
        for character in _sanitize(value)
    )


def render_text(findings: list[dict], scope: str, revision: str = "working tree") -> str:
    """Sort headings and rows because deterministic output keeps repeated reviews diffable."""
    counts = _counts(findings)
    summary = ", ".join(f"{key}={counts[key]}" for key in SEVERITIES)
    lines = [
        f"Review: {_sanitize(scope)}",
        f"Revision: {_sanitize(revision)}",
        f"Summary: {summary}",
    ]
    for path, rows in sorted(_groups(findings).items()):
        lines.append(_sanitize(path))
        for item in sorted(rows, key=lambda row: (row["line"], row["rule"])):
            lines.append(
                f"  {item['line']}: {_sanitize(item['rule'])} [{item['severity']}] "
                f"{_sanitize(item['excerpt'])} Fix: {_sanitize(item['hint'])}"
            )
    return "\n".join(lines) + "\n"


def _markdown_rows(rows: list[dict]) -> list[str]:
    lines: list[str] = []
    for path, grouped in sorted(_groups(rows).items()):
        lines.append(f"### `{_markdown(path)}`")
        for item in sorted(grouped, key=lambda row: (row["line"], row["rule"])):
            lines.append(
                f"- Line {item['line']}, `{_markdown(item['rule'])}`: "
                f"{_markdown(item['excerpt'])}. Fix: {_markdown(item['hint'])}"
            )
    return lines


def render_md(findings: list[dict], scope: str, revision: str = "working tree") -> str:
    counts = _counts(findings)
    lines = [
        "# Agent Discipline Review",
        "",
        f"- Scope: `{_markdown(scope)}`",
        f"- Revision: `{_markdown(revision)}`",
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
            lines.extend(_markdown_rows(rows))
    return "\n".join(lines) + "\n"


def render_json(findings: list[dict]) -> str:
    """Version the positional schema because consumers need to reject incompatible row layouts."""
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
    return json.dumps(payload, indent=2) + "\n"
