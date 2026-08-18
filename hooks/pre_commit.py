from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

from lib.baseline import strip_against
from lib.config import effective_config
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.reporting import record_findings, run_with_ledger, verdict_message
from lib.scanner import file_length_findings, scan_all, scannable_text
from lib.shell_parse import SEPARATORS

# Suffixed so that scanner._is_prose treats the message as prose and the english family reaches it.
COMMIT_MESSAGE_PATH = "commit_message.md"

# Because git reserves exit code 128 exclusively for "not a git repository", any other code means something else broke.
NOT_A_REPOSITORY_EXIT_CODE = 128


class _UnresolvableRepoLocation(Exception):
    """Raised because a probe run without GIT_DIR or GIT_WORK_TREE cannot see the repository the real commit would use."""


def run(
    payload: dict,
    config: dict | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Scan the staged tree behind a pending commit, blocking rather than letting it through when the gate cannot decide."""
    return fail_closed("commit", lambda: _checked_run(payload, config, ledger_root, state_root))


def _checked_run(
    payload: dict,
    config: dict | None,
    ledger_root: str | os.PathLike[str] | None,
    state_root: str | os.PathLike[str] | None,
) -> dict:
    if payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    return _run(payload, config, ledger_root, state_root)


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
    repo_rows = _repo_findings_by_repo(commit_cwds, config)
    outer_cfg = effective_config(config, cwd)
    message_findings = _message_findings(command, outer_cfg)
    stamp = _RecordStamp(
        session_id=str(payload.get("session_id") or ""),
        tool_use_id=str(payload.get("tool_use_id") or ""),
        turn_id=turn_id,
        duration_ms=int((time.monotonic() - started) * 1000),
        ledger_root=ledger_root,
    )
    decisions = _record_all(repo_rows, message_findings, outer_cfg, stamp)
    if not decisions:
        return allow()
    kind, message = verdict_message(decisions, outer_cfg)
    if kind == "block":
        return deny(message)
    return advise(message, "PreToolUse") if kind == "observe" else allow()


class _RecordStamp(NamedTuple):
    """Because every record_findings call in one commit shares the same turn, bundle the ledger fields once instead of repeating them."""
    session_id: str
    tool_use_id: str
    turn_id: str
    duration_ms: int
    ledger_root: str | os.PathLike[str] | None


def _record_all(
    repo_rows: list[tuple[Path, dict, list[dict]]],
    message_findings: list[dict],
    outer_cfg: dict,
    stamp: _RecordStamp,
) -> list[tuple[dict, str]]:
    decisions: list[tuple[dict, str]] = []
    for _repo, cfg, findings in repo_rows:
        decisions.extend(record_findings(
            session_id=stamp.session_id, hook="pre_commit", event="PreCommit",
            findings=findings, turn_id=stamp.turn_id, tool_use_id=stamp.tool_use_id,
            duration_ms=stamp.duration_ms, root=stamp.ledger_root, config=cfg,
        ))
    decisions.extend(record_findings(
        session_id=stamp.session_id, hook="pre_commit", event="PreCommit",
        findings=message_findings, turn_id=stamp.turn_id, tool_use_id=stamp.tool_use_id,
        duration_ms=stamp.duration_ms, root=stamp.ledger_root, config=outer_cfg,
    ))
    return decisions


def _repo_findings_by_repo(
    commit_cwds: list[Path], config: dict | None
) -> list[tuple[Path, dict, list[dict]]]:
    """Because two repos in one commit command can carry different gate configs, adjudicate each under its own, not the caller's cwd."""
    rows: list[tuple[Path, dict, list[dict]]] = []
    seen: set[Path] = set()
    for commit_cwd in commit_cwds:
        repo = _repo_root(commit_cwd)
        if repo is None or repo in seen:
            continue
        seen.add(repo)
        cfg = effective_config(config, repo)
        rows.append((repo, cfg, _repo_findings(repo, cfg)))
    return rows


def _repo_findings(repo: Path, cfg: dict) -> list[dict]:
    findings = []
    for path in _staged(repo):
        text = _staged_text(repo, path)
        if text is None or scannable_text(text, cfg) is None:
            findings.extend({**finding, "path": path} for finding in file_length_findings(path, text or ""))
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


def _message_findings(command: str | list[str], cfg: dict) -> list[dict]:
    """Scan the message the agent typed, because a commit's prose ships with the same authority as its code."""
    # Blank line between parts, because git itself joins repeated -m values as paragraphs.
    text = "\n\n".join(_commit_messages(command))
    if not text:
        return []
    return [
        {**finding, "path": COMMIT_MESSAGE_PATH}
        for finding in scan_all(COMMIT_MESSAGE_PATH, text, cfg)
    ]


def _commit_messages(command: str | list[str]) -> list[str]:
    messages: list[str] = []
    for segment in _segments(command):
        tokens = _unwrap_command(_strip_group_tokens(segment))
        messages.extend(_messages_after_commit(tokens))
    return messages


def _messages_after_commit(tokens: list[str]) -> list[str]:
    if len(tokens) < 2 or tokens[0] != "git" or "commit" not in tokens:
        return []
    return _message_values(tokens[tokens.index("commit") + 1:])


def _message_values(tokens: list[str]) -> list[str]:
    values: list[str] = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if token in {"-m", "--message"} or _is_message_bundle(token):
            if cursor + 1 < len(tokens):
                values.append(_decode_ansi_c_value(tokens[cursor + 1]))
            cursor += 2
            continue
        name, separator, inline = token.partition("=")
        if separator and name == "--message":
            values.append(_decode_ansi_c_value(inline))
        elif token.startswith("-m") and len(token) > 2:
            values.append(_decode_ansi_c_value(token[2:]))
        cursor += 1
    return values


_BOOLEAN_BUNDLE_CHARS = frozenset("anqvoe")


def _is_message_bundle(token: str) -> bool:
    if not token.startswith("-") or token.startswith("--") or len(token) <= 2:
        return False
    if token[-1] != "m":
        return False
    return all(char in _BOOLEAN_BUNDLE_CHARS for char in token[1:-1])


def _decode_ansi_c_value(value: str) -> str:
    if not value.startswith("$'"):
        return value
    end, decoded = _ansi_c_quote(value, 2)
    return decoded if end == len(value) - 1 else value


PATH_FLAGS = frozenset({"-C", "--work-tree", "--git-dir"})


def _bash_command(payload: dict) -> str | list[str]:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    for key in ("command", "cmd", "input"):
        if key in tool_input:
            command = tool_input[key]
            return list(command) if isinstance(command, list) else str(command)
    return ""


def _commit_cwds(command: str | list[str], cwd: Path) -> list[Path]:
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


def _segments(command: str | list[str]) -> list[list[str]]:
    if isinstance(command, list):
        return _split_segments(command)
    try:
        lexer = shlex.shlex(_normalize_ansi_c_quotes(command), posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        parts = list(lexer)
    except ValueError:
        return []
    return _split_segments(parts)


def _split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            segments.append(current)
            segments.append([token])
            current = []
            continue
        current.append(token)
    segments.append(current)
    return segments


def _normalize_ansi_c_quotes(command: str) -> str:
    parts: list[str] = []
    cursor = 0
    while cursor < len(command):
        start = command.find("$'", cursor)
        if start < 0:
            parts.append(command[cursor:])
            break
        parts.append(command[cursor:start])
        end, value = _ansi_c_quote(command, start + 2)
        if end < 0:
            return command
        parts.append(shlex.quote(value))
        cursor = end + 1
    return "".join(parts)


def _ansi_c_quote(command: str, cursor: int) -> tuple[int, str]:
    chars: list[str] = []
    while cursor < len(command):
        char = command[cursor]
        if char == "'":
            return cursor, "".join(chars)
        if char == "\\" and cursor + 1 < len(command):
            chars.append(command[cursor + 1])
            cursor += 2
            continue
        chars.append(char)
        cursor += 1
    return -1, ""


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


GIT_LOCATION_ENV_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE"})


def _names_git_location_override(assignments: list[str]) -> bool:
    return any(token.partition("=")[0] in GIT_LOCATION_ENV_VARS for token in assignments)


def _git_commit_cwd(segment: list[str], cwd: Path) -> Path | None:
    start = _unwrap_start(segment)
    unwrapped = segment[start:]
    if not unwrapped or unwrapped[0] != "git":
        return None
    current = cwd
    pinned = False
    cursor = 1
    while cursor < len(unwrapped):
        token = unwrapped[cursor]
        if token.startswith("-"):
            step = _skip_git_flag(unwrapped, cursor, current)
            if step is None:
                return None
            cursor, candidate, pins = step
            if pins or not pinned:
                current = candidate
            pinned = pinned or pins
            continue
        if token != "commit":
            return None
        if _names_git_location_override(segment[:start]):
            raise _UnresolvableRepoLocation(
                "GIT_DIR or GIT_WORK_TREE overrides the commit's repository location"
            )
        return current
    return None


def _strip_group_tokens(segment: list[str]) -> list[str]:
    return [token for token in segment if token not in {"(", ")"}]


def _unwrap_command(segment: list[str]) -> list[str]:
    return segment[_unwrap_start(segment):]


def _unwrap_start(segment: list[str]) -> int:
    cursor = 0
    while cursor < len(segment):
        token = segment[cursor]
        if token == "command" or _is_assignment(token):
            cursor += 1
            continue
        if token != "env":
            break
        cursor = _skip_env_prefix(segment, cursor + 1)
    return cursor


def _skip_env_prefix(segment: list[str], cursor: int) -> int:
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
    return cursor


def _is_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator and name and name.isidentifier())


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
    except subprocess.CalledProcessError as exc:
        if exc.returncode == NOT_A_REPOSITORY_EXIT_CODE:
            return None
        raise
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
    except subprocess.CalledProcessError as exc:
        if exc.returncode == NOT_A_REPOSITORY_EXIT_CODE:
            return []
        raise
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
    except subprocess.CalledProcessError as exc:
        if exc.returncode == NOT_A_REPOSITORY_EXIT_CODE:
            return None
        raise
    return result.stdout


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
