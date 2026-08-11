from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from lib.baseline import strip_against
from lib.config import effective_config
from lib.hookio import PARSE_FAILURE, advise, allow, deny, read_payload, write_payload
from lib.reporting import record_findings, run_with_ledger, verdict_message
from lib.scanner import scan_all, scannable_text

# Suffixed so that scanner._is_prose treats the message as prose and the english family reaches it.
COMMIT_MESSAGE_PATH = "commit_message.md"


UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this commit and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)


def run(
    payload: dict,
    config: dict | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Scan the staged tree behind a pending commit, blocking rather than letting it through when the gate cannot decide."""
    try:
        if payload is PARSE_FAILURE:
            return deny(UNDECIDABLE + "unreadable hook payload")
        return _run(payload, config, ledger_root, state_root)
    except Exception as exc:
        return deny(UNDECIDABLE + str(exc))


def _run(
    payload: dict,
    config: dict | None,
    ledger_root: str | os.PathLike[str] | None,
    state_root: str | os.PathLike[str] | None,
) -> dict:
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
    findings.extend(_message_findings(command, cfg))
    if not findings:
        return allow()
    decisions = record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_commit",
        event="PreCommit", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=ledger_root, config=cfg,
    )
    kind, message = verdict_message(decisions, cfg)
    if kind == "block":
        return deny(message)
    elif kind == "must_fix":
        return advise(message, "PreToolUse")
    return advise(message, "PreToolUse") if kind == "observe" else allow()


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
        owned = strip_against(_head_text(repo, path), path, scan_all(path, text, cfg), cfg)
        for finding in owned:
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def _head_text(repo: Path, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", "HEAD:" + path], cwd=repo, text=True,
            capture_output=True, check=True, timeout=30, errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout


def _message_findings(command: str, cfg: dict) -> list[dict]:
    """Scan the message the agent typed, because a commit's prose ships with the same authority as its code."""
    # Blank line between parts, because git itself joins repeated -m values as paragraphs.
    text = "\n\n".join(_commit_messages(command))
    if not text:
        return []
    return [
        {**finding, "path": COMMIT_MESSAGE_PATH}
        for finding in scan_all(COMMIT_MESSAGE_PATH, text, cfg)
    ]


def _commit_messages(command: str) -> list[str]:
    messages: list[str] = []
    for segment in _segments(command):
        tokens = _unwrap_command(_strip_group_tokens(segment))
        if len(tokens) < 2 or tokens[0] != "git" or "commit" not in tokens:
            continue
        messages.extend(_message_values(tokens[tokens.index("commit") + 1:]))
    return messages


def _message_values(tokens: list[str]) -> list[str]:
    values: list[str] = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if token in {"-m", "--message"}:
            if cursor + 1 < len(tokens):
                values.append(tokens[cursor + 1])
            cursor += 2
            continue
        name, separator, inline = token.partition("=")
        if separator and name == "--message":
            values.append(inline)
        elif token.startswith("-m") and len(token) > 2:
            values.append(token[2:])
        cursor += 1
    return values


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
    resolved = _resolve_cwd(current, value)
    if flag == "--git-dir" and resolved.name == ".git":
        return resolved.parent
    return resolved


def _skip_git_flag(segment: list[str], cursor: int, current: Path) -> tuple[int, Path, bool] | None:
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
