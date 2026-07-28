from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from lib.config import effective_config
from lib.hookio import allow, deny, read_payload, write_payload
from lib.reporting import compact_block, record_decision, run_with_ledger
from lib.scanner import scan_all, scannable_text


def run(
    payload: dict,
    config: dict | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Scan the staged tree behind a pending git commit, recording the decision so the gate leaves ledger evidence."""
    return run_with_ledger(
        hook="pre_commit",
        payload=payload,
        gate=lambda turn_id: _gate(payload, config, turn_id, ledger_root),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def _gate(payload: dict, config: dict | None, turn_id: str, ledger_root) -> dict:
    started = time.monotonic()
    command = _bash_command(payload)
    cwd = Path(payload.get("cwd") or os.getcwd())
    commit_cwds = _commit_cwds(command, cwd)
    if not commit_cwds:
        return allow()
    cfg = effective_config(config, cwd)
    findings = _staged_findings(commit_cwds, config)
    if not findings:
        return allow()
    reason, _ = compact_block(findings, cfg)
    _record(payload, findings, turn_id, ledger_root, int((time.monotonic() - started) * 1000))
    return deny(reason)


def _staged_findings(commit_cwds: list[Path], config: dict | None) -> list[dict]:
    findings = []
    for commit_cwd in commit_cwds:
        repo = _repo_root(commit_cwd)
        if repo is None:
            continue
        cfg = effective_config(config, commit_cwd)
        findings.extend(_repo_findings(repo, cfg))
    return findings


def _repo_findings(repo: Path, cfg: dict) -> list[dict]:
    findings = []
    for path in _staged(repo):
        text = _staged_text(repo, path)
        if text is None or scannable_text(text, cfg) is None:
            continue
        for finding in scan_all(path, text, cfg):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def _record(payload: dict, findings: list[dict], turn_id: str, ledger_root, duration_ms: int) -> None:
    """Log the first blocking finding, because one row per commit attempt is enough to prove the gate ran."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    first = findings[0]
    record_decision(
        session_id=session_id, hook="pre_commit", event="PreCommit",
        family=str(first.get("family", "")), rule=str(first.get("rule", "")),
        path=str(first.get("path", "")), tool_use_id=str(payload.get("tool_use_id") or ""),
        outcome="block", duration_ms=duration_ms, turn_id=turn_id, root=ledger_root,
    )


PATH_FLAGS = frozenset({"-C", "--work-tree", "--git-dir"})


def _bash_command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def _commit_cwds(command: str, cwd: Path) -> list[Path]:
    current = cwd
    stack: list[Path] = []
    commits: list[Path] = []
    for segment in _segments(command):
        if not segment:
            continue
        if segment == ["("]:
            stack.append(current)
            continue
        if segment == [")"]:
            current = stack.pop() if stack else current
            continue
        segment = _strip_group_tokens(segment)
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) >= 2:
            current = _resolve_cwd(current, segment[1])
            continue
        git_cwd = _git_commit_cwd(segment, current)
        if git_cwd is not None:
            commits.append(git_cwd)
    return commits


def _segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        parts = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for part in parts:
        if part in {"&&", "||", ";", "|", "(", ")"}:
            segments.append(current)
            segments.append([part])
            current = []
            continue
        current.append(part)
    segments.append(current)
    return segments


def _flag_cwd(flag: str, current: Path, value: str) -> Path:
    """Resolve one path-bearing git flag, mapping a .git directory back to its work tree."""
    resolved = _resolve_cwd(current, value)
    if flag == "--git-dir" and resolved.name == ".git":
        return resolved.parent
    return resolved


def _skip_git_flag(segment: list[str], cursor: int, current: Path) -> tuple[int, Path, bool] | None:
    """Step over one leading git flag, returning (next_cursor, cwd, pins_work_tree) or None when malformed."""
    token = segment[cursor]
    if token.startswith("-C") and len(token) > 2:
        return cursor + 1, _resolve_cwd(current, token[2:]), False
    name, separator, inline = token.partition("=")
    if separator and name in PATH_FLAGS:
        return cursor + 1, _flag_cwd(name, current, inline), name == "--work-tree"
    if token in PATH_FLAGS:
        if cursor + 1 >= len(segment):
            return None
        return cursor + 2, _flag_cwd(token, current, segment[cursor + 1]), token == "--work-tree"
    if token == "-c":
        return cursor + 2, current, False
    return cursor + 1, current, False


def _git_commit_cwd(segment: list[str], cwd: Path) -> Path | None:
    segment = _unwrap_command(segment)
    if not segment or segment[0] != "git":
        return None
    current = cwd
    pinned = False
    cursor = 1
    while cursor < len(segment):
        token = segment[cursor]
        if token.startswith("-"):
            step = _skip_git_flag(segment, cursor, current)
            if step is None:
                return None
            cursor, candidate, pins = step
            if pins or not pinned:
                current = candidate
            pinned = pinned or pins
            continue
        return current if token == "commit" else None
    return None


def _strip_group_tokens(segment: list[str]) -> list[str]:
    return [token for token in segment if token not in {"(", ")"}]


def _unwrap_command(segment: list[str]) -> list[str]:
    cursor = 0
    while cursor < len(segment):
        token = segment[cursor]
        if token == "command":
            cursor += 1
            continue
        if token == "env":
            cursor += 1
            while cursor < len(segment):
                current = segment[cursor]
                if current in {"-i", "--ignore-environment"}:
                    cursor += 1
                    continue
                if current in {"-u", "--unset"}:
                    cursor += 2
                    continue
                if "=" in current and not current.startswith("="):
                    cursor += 1
                    continue
                break
            continue
        break
    return segment[cursor:]


def _resolve_cwd(cwd: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path


def _repo_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _staged(cwd: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _staged_text(repo: Path, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", ":" + path],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout


if __name__ == "__main__":
    write_payload(run(read_payload()))
