from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from lib.config import effective_config
from lib.hookio import allow, deny, read_payload, write_payload
from lib.reporting import compact_block
from lib.scanner import scan_all


def run(payload: dict, config: dict | None = None) -> dict:
    command = _bash_command(payload)
    cwd = Path(payload.get("cwd") or os.getcwd())
    commit_cwds = _commit_cwds(command, cwd)
    if not commit_cwds:
        return allow()
    findings = []
    for commit_cwd in commit_cwds:
        repo = _repo_root(commit_cwd)
        if repo is None:
            continue
        cfg = effective_config(config, commit_cwd)
        for path in _staged(repo):
            text = _staged_text(repo, path)
            if text is None:
                continue
            for finding in scan_all(path, text, cfg):
                if not finding.get("force"):
                    continue
                item = dict(finding)
                item["path"] = path
                findings.append(item)
    if not findings:
        return allow()
    reason, _ = compact_block(findings, cfg)
    return deny(reason)


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


def _skip_git_flag(segment: list[str], cursor: int, current: Path) -> tuple[int, Path] | None:
    """Step over one leading git flag, returning (next_cursor, cwd) or None on a malformed -C."""
    token = segment[cursor]
    if token == "-C":
        if cursor + 1 >= len(segment):
            return None
        return cursor + 2, _resolve_cwd(current, segment[cursor + 1])
    if token.startswith("-C") and len(token) > 2:
        return cursor + 1, _resolve_cwd(current, token[2:])
    if token in {"-c", "--git-dir", "--work-tree"}:
        return cursor + 2, current
    return cursor + 1, current


def _git_commit_cwd(segment: list[str], cwd: Path) -> Path | None:
    segment = _unwrap_command(segment)
    if not segment or segment[0] != "git":
        return None
    current = cwd
    cursor = 1
    while cursor < len(segment):
        token = segment[cursor]
        if token.startswith("-"):
            step = _skip_git_flag(segment, cursor, current)
            if step is None:
                return None
            cursor, current = step
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
