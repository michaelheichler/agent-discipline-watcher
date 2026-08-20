"""Shapes a literal Bash write's findings against the committed baseline, because an overwrite inherits the file's existing debt while an append only ever adds lines the command itself wrote."""
from __future__ import annotations

from pathlib import Path

from lib.baseline import split_committed
from lib.scan_input import file_length_policy, file_line_count, scannable_text
from lib.scanner import _code_file, scan_all
from lib.shell_parse import LiteralWrite, literal_writes


def shaped_write_findings(
    command: str, config: dict | None, cwd: str | Path | None,
) -> tuple[list[dict], list[dict]]:
    """Split an overwrite against the committed baseline and treat an append as fully owned, because appending only ever adds lines the command itself wrote."""
    resolved_cwd = Path(cwd) if cwd is not None else Path(".")
    owned: list[dict] = []
    inherited: list[dict] = []
    for write in literal_writes(command):
        body = scannable_text(write.text, config or {})
        if body is None:
            continue
        if write.append:
            owned.extend(_append_shape_findings(write, body, resolved_cwd, config))
        else:
            shape_owned, shape_inherited = _overwrite_shape_findings(write, body, resolved_cwd, config)
            owned.extend(shape_owned)
            inherited.extend(shape_inherited)
    return owned, inherited


def _overwrite_shape_findings(
    write: LiteralWrite, body: str, cwd: Path, config: dict | None,
) -> tuple[list[dict], list[dict]]:
    findings = _stamped_findings(write.path, body, config)
    return split_committed(_resolved_path(write.path, cwd), findings, config or {})


def _append_shape_findings(write: LiteralWrite, body: str, cwd: Path, config: dict | None) -> list[dict]:
    findings = _label_appended_text(_stamped_findings(write.path, body, config))
    length_finding = _append_length_finding(write.path, body, _resolved_path(write.path, cwd))
    return findings + ([length_finding] if length_finding is not None else [])


def _stamped_findings(path: str, body: str, config: dict | None) -> list[dict]:
    findings = []
    for finding in scan_all(path, body, config):
        item = dict(finding)
        item["path"] = path
        findings.append(item)
    return findings


def _label_appended_text(findings: list[dict]) -> list[dict]:
    return [
        {**finding, "detail": finding["detail"] + " (line " + str(finding["line"]) + " of appended text)"}
        for finding in findings
    ]


def _append_length_finding(path: str, body: str, resolved_path: Path) -> dict | None:
    """Report only a length tier this append newly crosses, gated on the same code-file predicate the scanner uses, because a non-code target or debt the file already carried belongs to no one this append owns."""
    if not _code_file(path, body):
        return None
    disk = file_line_count(resolved_path)
    before = disk[0] if disk is not None else 0
    total = before + len(body.splitlines())
    policy = file_length_policy(total)
    if policy is None or policy == file_length_policy(before):
        return None
    rule, action = policy
    return {
        "family": "clean_code",
        "rule": rule,
        "line": 1,
        "detail": f"File has {total} lines in {path}",
        "force": True,
        "path": path,
        "snippet": path.strip()[:180],
        "action": action,
    }


def _resolved_path(path: str, cwd: Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else cwd / candidate
