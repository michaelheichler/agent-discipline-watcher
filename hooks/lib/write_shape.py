from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.baseline import split_committed
from lib.findings import Finding
from lib.scan_input import file_length_policy, file_line_count, scannable_text
from lib.scanner import _code_file, scan_all
from lib.shell_parse import LiteralWrite, literal_writes


@dataclass(frozen=True, slots=True)
class FileLength:
    count: int = 0
    capped: bool = False
    ends_with_newline: bool = True


def shaped_write_findings(
    command: str, config: dict | None, cwd: str | Path | None,
) -> tuple[list[dict], list[dict]]:
    resolved_cwd = Path(cwd) if cwd is not None else Path(".")
    owned: list[dict] = []
    inherited: list[dict] = []
    lengths: dict[Path, FileLength] = {}
    for write in literal_writes(command):
        body = scannable_text(write.text, config or {})
        if body is None:
            continue
        shape = ShapedWrite(write, body, resolved_cwd, config)
        path = _resolved_path(write.path, resolved_cwd).resolve()
        if write.append:
            before = lengths[path] if path in lengths else _file_length(path)
            lengths[path] = _appended_length(before, body)
            owned.extend(_append_shape_findings(shape, before, lengths[path]))
        else:
            lengths[path] = _appended_length(FileLength(), body)
            shape_owned, shape_inherited = _overwrite_shape_findings(shape)
            owned.extend(shape_owned)
            inherited.extend(shape_inherited)
    return owned, inherited


@dataclass(frozen=True, slots=True)
class ShapedWrite:
    write: LiteralWrite
    body: str
    cwd: Path
    config: dict | None


def _overwrite_shape_findings(shape: ShapedWrite) -> tuple[list[dict], list[dict]]:
    findings = _stamped_findings(shape.write.path, shape.body, shape.config)
    return split_committed(
        _resolved_path(shape.write.path, shape.cwd), findings, shape.config or {}
    )


def _append_shape_findings(shape: ShapedWrite, before: FileLength, after: FileLength) -> list[dict]:
    findings = _label_appended_text([
        finding for finding in _stamped_findings(shape.write.path, shape.body, shape.config)
        if finding["rule"] not in {"file_length_warning", "file_length_critical", "file_too_long"}
    ])
    length_finding = _append_length_finding(shape.write.path, shape.body, before, after)
    return findings + ([length_finding] if length_finding is not None else [])


def _stamped_findings(path: str, body: str, config: dict | None) -> list[dict]:
    return [Finding.from_dict(finding).with_path(path).to_dict() for finding in scan_all(path, body, config)]


def _label_appended_text(findings: list[dict]) -> list[dict]:
    return [
        Finding.from_dict(finding).with_detail(
            finding["detail"] + " (line " + str(finding["line"]) + " of appended text)"
        ).to_dict()
        for finding in findings
    ]


def _append_length_row(finding: Finding) -> dict:
    return {
        "family": finding.family,
        "rule": finding.rule,
        "line": finding.line,
        "detail": finding.detail,
        "force": finding.force,
        "path": finding.path,
        "snippet": finding.snippet,
        "action": finding.action,
    }


def _append_length_finding(path: str, body: str, before: FileLength, after: FileLength) -> dict | None:
    if not _code_file(path, body):
        return None
    policy = file_length_policy(after.count)
    if policy is None or (policy[0] != "file_too_long" and policy == file_length_policy(before.count)):
        return None
    rule, action = policy
    shown = f"at least {after.count}" if after.capped else str(after.count)
    finding = Finding(
        family="clean_code",
        rule=rule,
        line=1,
        detail=f"File has {shown} lines in {path}",
        force=True,
        snippet=path.strip()[:180],
        action=action,
        path=path,
        severity=None,
        tool_use_id=None,
    )
    return _append_length_row(finding)


def _file_length(path: Path) -> FileLength:
    counted = file_line_count(path)
    count, capped = counted if counted is not None else (0, False)
    return FileLength(count, capped, _ends_with_newline(path))


def _appended_length(before: FileLength, body: str) -> FileLength:
    if not body:
        return before
    total = before.count + len(body.splitlines())
    if before.count and not before.ends_with_newline:
        total -= 1
    return FileLength(total, before.capped, body.endswith("\n"))


def _ends_with_newline(resolved_path: Path) -> bool:
    try:
        with resolved_path.open("rb") as handle:
            handle.seek(-1, 2)
            return handle.read(1) == b"\n"
    except OSError:
        return True


def _resolved_path(path: str, cwd: Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else cwd / candidate
